# -*- coding: utf-8 -*-
"""在 MCP 服务器启动时预生成/更新 schema.json。

调用时机：
1. main.py 启动时（main() 函数内）调用
2. 若 schema.json 不存在或过旧（>7 天），自动重新生成

生成内容（四引擎工具列表 + 参数 schema）：
- inner: 从 native_tools.CUSTOM_TOOL_REGISTRY + INNER_PARAM_SCHEMA
- whitebox: 从 wbt.list_tools() + wbt.toolbox() + wbt.tool_parameters()
- gdal: 从 gdal_engine.GDAL_TOOL_CATALOG + GDAL_PARAM_SCHEMA（gdal:* 直执行）
- qgis: 从 qgis_process list --json

生成后由 schema_loader.load_schema() 加载到内存缓存。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# 共享目录（shared/）
_SHARED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)


# ─── 导出 inner ────────────────────────────────────────────────────────────────
def _export_inner() -> dict[str, Any]:
    """从 native_tools 导出内置工具 schema。"""
    try:
        from native_tools import CUSTOM_TOOL_REGISTRY, INNER_PARAM_SCHEMA  # type: ignore
    except Exception as e:
        logger.warning("[generate_schema] failed to import native_tools: %s", e)
        return {}

    out = {}
    for name, (func, desc) in sorted(CUSTOM_TOOL_REGISTRY.items()):
        out[name] = {
            "description": desc or "",
            "category": "内置(纯Python)",
            "required": INNER_PARAM_SCHEMA.get(name, {}).get("required", []),
            "params": INNER_PARAM_SCHEMA.get(name, {}).get("params", {}),
        }
    return out


# ─── 导出 whitebox ─────────────────────────────────────────────────────────────
def _camel_to_snake(name: str) -> str:
    """CamelCase → snake_case。"""
    import re
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def _export_whitebox() -> dict[str, Any]:
    """从 whitebox 导出工具 schema（含参数详情）。"""
    try:
        import whitebox  # type: ignore
    except Exception as e:
        logger.warning("[generate_schema] failed to import whitebox: %s", e)
        return {}

    try:
        w = whitebox.WhiteboxTools()
    except Exception as e:
        logger.warning("[generate_schema] failed to create WhiteboxTools: %s", e)
        return {}

    schema: dict[str, Any] = {}

    # 工具列表（name → 简短描述）
    try:
        tools = w.list_tools()  # {snake_case: "brief description"}
    except Exception as e:
        logger.warning("[generate_schema] list_tools failed: %s", e)
        return schema

    # 工具分类（snake_case → 分类名）
    categories: dict[str, str] = {}
    try:
        toolbox_raw = w.toolbox()
        for line in toolbox_raw.splitlines():
            if ":" not in line:
                continue
            camel, c = line.split(":", 1)
            snake = _camel_to_snake(camel.strip())
            if snake:
                categories[snake] = c.strip()
    except Exception as e:
        logger.warning("[generate_schema] toolbox() failed: %s", e)

    def _datatype_from_pt(pt: Any) -> str | None:
        if isinstance(pt, dict):
            for key in pt:
                return key
        if isinstance(pt, str):
            return pt
        return None

    def _subdatatype(pt: Any) -> str | None:
        if isinstance(pt, dict):
            for val in pt.values():
                if isinstance(val, dict):
                    return "/".join(f"{k}:{v_}" for k, v_ in val.items())
                return str(val)
        return None

    # 逐工具取参数 schema（可选，按需开启以避免启动耗时过长）
    # 默认只导出工具列表+分类，参数详情在首次调用时由 execute_gis_tool 的 _tool_params 缓存
    # 若需要完整参数，可设置环境变量 ARCGIS_MCP_FULL_SCHEMA=1
    full_params = os.environ.get("ARCGIS_MCP_FULL_SCHEMA", "0") == "1"

    for name in sorted(tools.keys()):
        info = {
            "description": tools.get(name, ""),
            "category": categories.get(name, ""),
            "required": [],
            "params": {},
        }
        if full_params:
            try:
                params_raw = w.tool_parameters(name)
                params_list = json.loads(params_raw).get("parameters", []) if params_raw else []
                required = []
                params_map = {}
                for p in params_list:
                    flags = p.get("flags") or []
                    longflag = next((f for f in flags if f.startswith("--")), flags[0] if flags else "")
                    if not longflag:
                        continue
                    key = longflag.lstrip("-")
                    optional = bool(p.get("optional", False))
                    pt = p.get("parameter_type")
                    params_map[key] = {
                        "flags": flags,
                        "optional": optional,
                        "parameter_type": _datatype_from_pt(pt),
                        "datatype": _subdatatype(pt),
                        "name": p.get("name", ""),
                        "description": p.get("description", ""),
                    }
                    if not optional:
                        # required 与 params 键同形（裸名），param-validate 直接按参数名比对
                        required.append(key)
                info["required"] = required
                info["params"] = params_map
            except Exception:  # noqa: BLE001
                pass
        schema[name] = info

    return schema


# ─── 导出 gdal ─────────────────────────────────────────────────────────────────
def _export_gdal() -> dict[str, Any]:
    """从 gdal_engine 导出 gdal:* 工具 schema（含必填/参数描述）。

    gdal:* 工具由 gdal_engine 进程内（rasterio/pyogrio）或 GDAL CLI 直接执行，
    不依赖 qgis_process；schema 含 GDAL_PARAM_SCHEMA 的 required/params。
    """
    try:
        from gdal_engine import GDAL_TOOL_CATALOG, GDAL_PARAM_SCHEMA  # type: ignore
    except Exception as e:  # noqa: BLE001
        logger.warning("[generate_schema] failed to import gdal_engine: %s", e)
        return {}

    out: dict[str, Any] = {}
    for name, (_func, desc, group) in GDAL_TOOL_CATALOG.items():
        schema = GDAL_PARAM_SCHEMA.get(name, {})
        out[name] = {
            "description": desc,
            "category": group,
            "required": schema.get("required", []),
            "params": schema.get("params", {}),
            "name": name.split(":", 1)[1].replace("_", " ").title() if ":" in name else name,
            "provider": "gdal",
            "group": group,
        }
    return out


# ─── 导出 qgis ─────────────────────────────────────────────────────────────────
def _find_qgis_bat() -> str | None:
    """定位 qgis_process*.bat（正式版 qgis_process-qgis.bat 或 LTR 版 qgis_process-qgis-ltr.bat）。"""
    import glob as _glob
    env_path = os.environ.get("QGIS_PROCESS_BAT", "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path
    for c in _glob.glob(r"C:\Program Files\QGIS *\bin\qgis_process*.bat"):
        if os.path.isfile(c):
            return c
    return None


def _export_qgis() -> dict[str, Any]:
    """导出 qgis 算法 schema（含 required/params，供 param-validate 校验）。

    优先进程内注册表（qgis_engine.export_qgis_schemas，逐算法读参数定义）；
    不可用时降级为元数据目录（Windows 经 qgis_process*.bat 子进程，POSIX 经
    qgis_engine.list_qgis_algorithms 的 CLI 模式）——降级产物无参数 schema，
    param-validate 对这类条目仅做引擎归属提示，不做必填校验。
    """
    try:
        from qgis_engine import export_qgis_schemas  # type: ignore

        full = export_qgis_schemas()
        if full:
            logger.info("[generate_schema] qgis 段进程内导出 %d 个算法（含参数 schema）", len(full))
            return full
    except Exception as e:  # noqa: BLE001
        logger.warning("[generate_schema] qgis 段进程内导出失败: %s", e)

    bat = _find_qgis_bat()
    if not bat:
        try:
            from qgis_engine import list_qgis_algorithms  # type: ignore

            catalog = list_qgis_algorithms()
            if catalog:
                logger.info("[generate_schema] qgis 段经 qgis_engine 导出 %d 个算法（仅元数据）", len(catalog))
            else:
                logger.info("[generate_schema] QGIS 未安装，qgis 段为空")
            return catalog
        except Exception as e:  # noqa: BLE001
            logger.warning("[generate_schema] qgis 段导出失败: %s", e)
            return {}

    try:
        proc = subprocess.run(
            [bat, "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if proc.returncode != 0:
            logger.warning("[generate_schema] qgis list 失败 rc=%s", proc.returncode)
            return {}
        data = json.loads(proc.stdout)
    except Exception as e:
        logger.warning("[generate_schema] qgis list 异常: %s", e)
        return {}

    providers = data.get("providers", {}) if isinstance(data, dict) else {}
    catalog: dict[str, Any] = {}
    for prov_id, prov in providers.items():
        for algo_id, info in (prov or {}).get("algorithms", {}).items():
            # gdal:* 已由 gdal_engine 直执行接管，不在 qgis 段重复（与 qgis_engine.list_qgis_algorithms 一致）。
            if prov_id == "gdal":
                continue
            catalog[algo_id] = {
                "name": info.get("name", ""),
                "provider": prov_id,
                "group": info.get("group", ""),
                "description": info.get("short_description", "") or info.get("name", ""),
            }
    return catalog


# ─── 主函数 ────────────────────────────────────────────────────────────────────
def generate_schema(output_path: str, force: bool = False) -> dict[str, Any]:
    """生成/更新 schema.json。

    Args:
        output_path: 输出文件路径。
        force: 强制重新生成（忽略缓存过期检查）。

    Returns:
        生成的 schema dict。
    """
    now = datetime.now()

    # 缓存过期检查（默认 7 天）
    if not force and os.path.isfile(output_path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(output_path))
            if (now - mtime) < timedelta(days=7):
                logger.info("[generate_schema] schema.json 缓存未过期（<7天），跳过生成")
                with open(output_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:  # noqa: BLE001
            pass

    logger.info("[generate_schema] 开始生成 schema.json ...")
    inner = _export_inner()
    whitebox = _export_whitebox()
    gdal = _export_gdal()
    qgis = _export_qgis()

    schema = {
        "engines": {
            "inner": inner,
            "whitebox": whitebox,
            "gdal": gdal,
            "qgis": qgis,
        },
        "generated_at": now.isoformat(),
        "wbt_count": len(whitebox),
        "inner_count": len(inner),
        "gdal_count": len(gdal),
        "qgis_count": len(qgis),
    }

    # 确保输出目录存在
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=1)

    logger.info(
        "[generate_schema] 完成：inner=%d whitebox=%d gdal=%d qgis=%d → %s",
        len(inner), len(whitebox), len(gdal), len(qgis), output_path,
    )
    return schema


if __name__ == "__main__":
    # 命令行直接运行：生成到当前目录
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "schema.json")
    schema = generate_schema(out, force=True)
    print(json.dumps({
        "generated": out,
        "inner": schema.get("inner_count", 0),
        "whitebox": schema.get("wbt_count", 0),
        "gdal": schema.get("gdal_count", 0),
        "qgis": schema.get("qgis_count", 0),
    }, ensure_ascii=False, indent=2))
