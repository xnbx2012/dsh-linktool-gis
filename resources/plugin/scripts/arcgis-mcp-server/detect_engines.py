# -*- coding: utf-8 -*-
"""引擎可用性探测脚本（设置页「GIS 引擎 → 刷新」的宿主侧执行体）。

在 arcgis-mcp-server 的 uv 环境内运行（复用 pyproject.toml 依赖），逐引擎探测：
  inner  内置纯 Python 工具（native_tools 注册表）
  wbt    WhiteboxTools（首次 import 会下载 Rust 二进制，可能耗时数分钟）
  gdal   GDAL 直执行（进程内 rasterio/pyogrio + CLI 二进制探测）
  qgis   QGIS（Windows: qgis_process*.bat 进程内；POSIX: PATH 上的 qgis_process）
  arcpy  ArcGIS Pro（arcgispro-py3 解释器定位）

stdout 输出单个 JSON 文档（适配层从中解析）：
  {"engines": {"<name>": {"available": bool, "detail": str, "version": str}}, "checked_at": iso}
退出码恒为 0：单引擎探测失败不阻断其余引擎，失败也以 JSON 表达。
"""

import concurrent.futures
import datetime
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SHARED_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "shared"))
for _p in (_SHARED_DIR, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("PYTHONUTF8", "1")

# 机器残留的 PROJ_LIB/GDAL_DATA（PostGIS 老库）会让 EPSG 探测失败；先修复再探测。
try:
    from gis_io import repair_proj_env  # type: ignore

    repair_proj_env()
except Exception:  # noqa: BLE001 —— 修复失败不阻断探测
    pass

# 单引擎探测上限（秒）。qgis 首次进程内初始化 ~10s；wbt 首次下载二进制可能数分钟。
PROBE_TIMEOUT_SECONDS = 600


def _tidy_version(raw: object) -> str | None:
    """从任意探测输出中提取首个版本号形 token（如 2.4.0 / 3.44.12）；无则 None。"""
    match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)", str(raw or ""))
    return match.group(1) if match else None


def _arcpy_pro_version(interpreter: str | None) -> str | None:
    """ArcGIS Pro 产品版本：读 <安装根>/bin/ArcGISPro.exe 的版本信息。

    不 import arcpy（冷启动 10-30s，会拖慢整个探测）；改为经 PowerShell 读
    PE 版本资源（亚秒级）。非 Windows 或读取失败返回 None（UI 隐藏版本号）。
    """
    if os.name != "nt" or not interpreter:
        return None
    # 解释器形如 <安装根>/bin/Python/envs/arcgispro-py3/python.exe（clone 环境层级一致），
    # 逐级向上找 <安装根>/bin/ArcGISPro.exe，不假设固定层级。
    target: Path | None = None
    for ancestor in Path(interpreter).parents:
        candidate = ancestor / "bin" / "ArcGISPro.exe"
        if candidate.is_file():
            target = candidate
            break
    if target is None:
        return None
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item -LiteralPath '{target}').VersionInfo.ProductVersion"],
            capture_output=True, text=True, timeout=30,
        )
        return _tidy_version(proc.stdout)
    except Exception:  # noqa: BLE001 —— 版本号缺失不影响可用性判定
        return None


def _probe(name: str) -> tuple[bool, str, str]:
    """探测单个引擎，返回 (available, detail, version)。异常转 False，不向上抛。"""
    try:
        if name == "inner":
            from native_tools import CUSTOM_TOOL_REGISTRY  # type: ignore

            count = len(CUSTOM_TOOL_REGISTRY)
            version = f"Python {platform.python_version()}" if count > 0 else ""
            return count > 0, f"{count} 个内置工具（geopandas/shapely 进程内，零外部依赖）", version

        if name == "wbt":
            import whitebox  # type: ignore

            tools = whitebox.WhiteboxTools().list_tools()
            count = len(tools) if isinstance(tools, dict) else 0
            try:
                version = _tidy_version(whitebox.WhiteboxTools().version()) or ""
            except Exception:  # noqa: BLE001 —— 版本号失败不影响可用性
                version = ""
            return count > 0, f"{count} 个 WhiteboxTools 工具", version

        if name == "gdal":
            from gdal_engine import GDAL_TOOL_CATALOG, _probe_gdal_bin_dir  # type: ignore

            count = len(GDAL_TOOL_CATALOG)
            bin_dir = _probe_gdal_bin_dir()
            detail = f"{count} 个 gdal:* 工具"
            if bin_dir:
                detail += f"；CLI 二进制：{bin_dir}"
            else:
                detail += "；CLI 二进制未找到（进程内 rasterio/pyogrio 工具仍可用）"
            version = ""
            try:
                import rasterio  # type: ignore

                version = _tidy_version(getattr(rasterio, "__gdal_version__", "")) or ""
            except Exception:  # noqa: BLE001
                pass
            return count > 0, detail, version

        if name == "qgis":
            from qgis_engine import list_qgis_algorithms, qgis_available, qgis_version  # type: ignore

            if not qgis_available():
                return False, (
                    "未找到 QGIS：Windows 需 qgis_process*.bat（Program Files/QGIS），"
                    "Linux/macOS 需 PATH 上的 qgis_process"
                ), ""
            algos = list_qgis_algorithms()
            try:
                version = qgis_version() or ""
            except Exception:  # noqa: BLE001
                version = ""
            return bool(algos), f"{len(algos)} 个 QGIS 处理算法", version

        if name == "arcpy":
            from find_arcpy import find_py_interpreter  # type: ignore

            exe = find_py_interpreter()
            version = _arcpy_pro_version(exe) or ""
            return bool(exe), (exe or "未找到 ArcGIS Pro arcgispro-py3 解释器（Windows 专属引擎）"), version

    except Exception as e:  # noqa: BLE001 —— 探测失败即不可用，不阻断其余引擎
        return False, f"探测异常: {type(e).__name__}: {e}", ""
    return False, "未知引擎", ""


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    engines = ["inner", "wbt", "gdal", "qgis", "arcpy"]
    out: dict[str, dict[str, object]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(engines)) as pool:
        futures = {name: pool.submit(_probe, name) for name in engines}
        for name, fut in futures.items():
            try:
                available, detail, version = fut.result(timeout=PROBE_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                available, detail, version = False, f"探测超时（>{PROBE_TIMEOUT_SECONDS}s）", ""
            except Exception as e:  # noqa: BLE001
                available, detail, version = False, f"探测异常: {e}", ""
            row: dict[str, object] = {"available": bool(available), "detail": str(detail)}
            if version:
                row["version"] = str(version)
            out[name] = row

    print(json.dumps(
        {
            "engines": out,
            "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        },
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
