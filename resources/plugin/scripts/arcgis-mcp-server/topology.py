# -*- coding: utf-8 -*-
"""拓扑检查与自动修复（进程内，无 arcpy）。

为 arcgis-mcp-server 的 `execute_gis_tool` 提供「执行前/后自动拓扑检查与修复」能力。

设计要点（与 main.py 一致，避免已知陷阱）：
- shapely / pyogrio / geopandas / whitebox 全部在 main.py 顶部已 import 过一次，
  本模块函数体内再 import 仅取引用，不触发 GDAL C 扩展首次初始化（否则在事件循环
  启动后与 stdio 传输死锁，见记忆 [[mcp-stdio-gdal-import-deadlock]]）。
- 不依赖任何顶层局部变量跨函数共享状态（见记忆 [[arcgis-mcp-tool-script-scoping]]），
  所有共享信息显式作为函数参数/返回值传递。
- 全程 best-effort：任何异常都吞掉返回带 error 的结构，绝不中断 execute_gis_tool 主流程。

检查后端 = shapely（is_valid / explain_validity / make_valid），无 whitebox 子进程开销。
修复组合 = shapely make_valid（修自相交等无效几何，whitebox 做不了）
          + whitebox clean_vector（修要素间拓扑：重叠/碎片/空几何）。
两者都只在 scan_topology 报告 issues 时才触发，避免对干净数据的冗余开销。
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

# ─── 开关 ────────────────────────────────────────────────────────────────────
# 全局开关：环境变量 ARCGIS_MCP_TOPOLOGY=off 时关闭（批量/性能敏感场景）。
_TOPO_OFF_ENV = "ARCGIS_MCP_TOPOLOGY"
# 单次开关：parameters["_topo_skip"]=true 时跳过本次。
TOPO_SKIP_KEY = "_topo_skip"

# 拓扑修复中 whitebox clean_vector 的独立超时（秒）。修复不应长时间阻塞主工具。
TOPO_REPAIR_TIMEOUT = 120

# explain_validity 采样上限（避免无效几何极多时撑爆摘要）。
_MAX_REASON_SAMPLES = 5


def topo_enabled(parameters: dict | None) -> bool:
    """是否启用拓扑检查/修复。

    关闭路径（任一即关）：
      - 环境变量 ARCGIS_MCP_TOPOLOGY=off（大小写不敏感）；
      - parameters['_topo_skip'] 为真值。
    """
    if os.environ.get(_TOPO_OFF_ENV, "").strip().lower() == "off":
        return False
    if parameters and parameters.get(TOPO_SKIP_KEY):
        return False
    return True


# ─── 路径解析（复用 gis_io._split_path，统一 GDB 逻辑路径解析）──────────────────
def _resolve_layer(path: str) -> tuple[str, str | None]:
    """把路径解析为 (datasource, layer)，GDB 逻辑路径按 .gdb/ 拆分。"""
    import sys

    shared = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
    if shared not in sys.path:
        sys.path.insert(0, shared)
    from gis_io import _split_path  # type: ignore

    return _split_path(path)


def _is_raster_path(path: str) -> bool:
    """栅格文件扩展名判定（栅格不进入矢量拓扑流程）。"""
    low = path.lower()
    return low.endswith((".tif", ".tiff", ".vrt", ".img", ".asc", ".grd"))


def _read_df(datasource: str, layer: str | None):
    import geopandas as gpd  # type: ignore

    if layer:
        return gpd.read_file(datasource, layer=layer)
    return gpd.read_file(datasource)


def _write_df(df, datasource: str, layer: str | None) -> None:
    """写回原位置（原地覆盖）。

    GDB 逻辑路径 → pyogrio OpenFileGDB（与 main._shp_to_gdb_fc 同源写法）；
    .shp → 写临时同名再替换整族（.shp/.shx/.dbf/.prj/.cpg），避免读着写冲突。
    """
    import pyogrio  # type: ignore

    if datasource.lower().endswith(".gdb"):
        gdb_parent = os.path.dirname(datasource)
        if gdb_parent:
            os.makedirs(gdb_parent, exist_ok=True)
        pyogrio.write_dataframe(
            df, datasource, layer=layer, driver="OpenFileGDB",
            layer_options={"TARGET_ARCGIS_VERSION": "ARCGIS_PRO_3_2_OR_LATER"},
        )
        return

    tmp_dir = tempfile.mkdtemp(prefix="topowrite_")
    tmp_base = os.path.join(tmp_dir, "topo_out")
    tmp_shp = tmp_base + ".shp"
    try:
        pyogrio.write_dataframe(df, tmp_shp, driver="ESRI Shapefile")
        _swap_shp_family(tmp_base, _shp_base(datasource))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _shp_base(path: str) -> str:
    """.shp 路径 -> 去扩展名基底（如 .../bad）。"""
    low = path.lower()
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        if low.endswith(ext):
            return path[: -len(ext)]
    noext, _ = os.path.splitext(path)
    return noext


def _swap_shp_family(src_base: str, dst_base: str) -> None:
    """把 src_base 的 shapefile 族文件覆盖到 dst_base（两者均为去扩展名基底）。"""
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        s = src_base + ext
        d = dst_base + ext
        if os.path.exists(s):
            if os.path.exists(d):
                try:
                    os.remove(d)
                except Exception:  # noqa: BLE001
                    pass
            try:
                os.replace(s, d)
            except Exception:  # noqa: BLE001
                pass


# ─── 检查 ────────────────────────────────────────────────────────────────────
def scan_topology(path: str) -> dict[str, Any]:
    """扫描矢量数据的拓扑/几何健康度（只读，不修改）。

    返回：
      {checked: bool, total, valid, invalid, empty, null_geom, reasons:[...], issues: bool}
      矢量读取失败 / 栅格 / 路径不存在 → {checked: False, ...}（调用方据此跳过）。
      任何异常 → {checked: False, error: str}。
    """
    try:
        if not isinstance(path, str) or not path.strip():
            return {"checked": False}
        if _is_raster_path(path):
            return {"checked": False, "reason": "raster"}
        datasource, layer = _resolve_layer(path)
        if not os.path.exists(datasource):
            return {"checked": False, "reason": "not_found"}

        from shapely.validation import explain_validity  # type: ignore

        df = _read_df(datasource, layer)
        if df is None or len(df) == 0:
            return {"checked": True, "total": 0, "valid": 0, "invalid": 0,
                    "empty": 0, "null_geom": 0, "reasons": [], "issues": False}

        geom = df.geometry
        is_valid_arr = list(geom.is_valid)
        is_empty_arr = list(geom.is_empty)
        null_geom = int(sum(1 for g in geom if g is None))

        total = len(df)
        valid = int(sum(1 for v in is_valid_arr if v))
        invalid = total - valid
        empty = int(sum(1 for e in is_empty_arr if e))

        reasons: list[str] = []
        for g, v in zip(geom, is_valid_arr):
            if not v and g is not None and len(reasons) < _MAX_REASON_SAMPLES:
                try:
                    reasons.append(str(explain_validity(g)))
                except Exception:  # noqa: BLE001
                    reasons.append("invalid geometry")

        issues = invalid > 0 or empty > 0 or null_geom > 0
        return {
            "checked": True,
            "total": total,
            "valid": valid,
            "invalid": invalid,
            "empty": empty,
            "null_geom": null_geom,
            "reasons": reasons,
            "issues": issues,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[topology] scan_topology(%s) failed: %s", path, e)
        return {"checked": False, "error": str(e)}


# ─── 修复 ────────────────────────────────────────────────────────────────────
def _collapse_to_largest(geom) -> Any:
    """make_valid 可能返回 GeometryCollection/Multi*，取面积最大的有效单一组成。

    避免 whitebox/shapefile 对 GeometryCollection 的兼容问题。
    """
    try:
        gt = geom.geom_type
    except Exception:  # noqa: BLE001
        return geom
    if gt in ("GeometryCollection", "MultiPolygon", "MultiLineString", "MultiPoint"):
        parts = list(getattr(geom, "geoms", []))
        valid = [p for p in parts if p is not None and not p.is_empty and p.is_valid]
        if not valid:
            return geom

        def _score(p):
            try:
                return p.area or (p.length if hasattr(p, "length") else 0) or 0
            except Exception:  # noqa: BLE001
                return 0

        return max(valid, key=_score)
    return geom


def _run_clean_vector(input_path: str, output_path: str) -> dict[str, Any]:
    """同步调 whitebox clean_vector 修要素间拓扑。

    repair_topology 经 main 的 asyncio.to_thread 在工作线程内运行，此处直接同步
    调 wbt.run_tool（Rust 子进程，阻塞本线程），不走 main 的 async 包装（避免
    在工作线程里 await 协程）。复用 main 的 _wbt 单例与 _CallbackCollector 收日志。
    """
    import main as _main  # type: ignore

    wbt = _main._wbt()
    work_dir = os.environ.get("AGENT_WORK_DIR", os.getcwd())
    try:
        wbt.set_working_dir(work_dir)
    except Exception:  # noqa: BLE001
        pass
    wbt.verbose = True
    collector = _main._CallbackCollector()
    args = [f"--input={input_path}", f"--output={output_path}"]
    try:
        ret = wbt.run_tool("clean_vector", args, callback=collector)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "returncode": None, "error": str(e)}
    rc = int(ret)
    return {"success": rc == 0, "returncode": rc, "error": None if rc == 0 else f"clean_vector 退出码 {rc}"}


def repair_topology(path: str, reasons: list[str] | None = None) -> dict[str, Any]:
    """自动修复矢量拓扑/几何问题（原地覆盖）。

    组合：
      1) shapely make_valid：修自相交/方向错误环/退化几何；空/None 几何交由 clean_vector 剔除。
      2) whitebox clean_vector：修要素间拓扑（重叠/碎片/悬挂/空几何）。

    返回：
      {repaired: bool, before:{...}, after:{...}, method:[...], whitebox_rc: int|None, error: str|None}
    """
    out: dict[str, Any] = {
        "repaired": False, "before": {}, "after": {},
        "method": [], "whitebox_rc": None, "error": None,
    }
    tmp_dir: str | None = None
    try:
        datasource, layer = _resolve_layer(path)
        df = _read_df(datasource, layer)
        if df is None or len(df) == 0:
            out["error"] = "空数据，无需修复"
            return out

        from shapely import make_valid  # type: ignore

        before = scan_topology(path)
        b_inv = before.get("invalid", 0)
        b_empty = before.get("empty", 0)
        b_null = before.get("null_geom", 0)
        out["before"] = {"invalid": b_inv, "empty": b_empty, "null_geom": b_null}

        changed = False

        # step1: shapely make_valid（仅修无效几何；空/None 留给 clean_vector）
        if b_inv > 0:
            import geopandas as gpd  # type: ignore

            new_geoms = []
            fixed_n = 0
            for g in df.geometry:
                if g is None or g.is_empty:
                    new_geoms.append(g)
                    continue
                if not g.is_valid:
                    try:
                        fixed = _collapse_to_largest(make_valid(g))
                        new_geoms.append(fixed)
                        fixed_n += 1
                    except Exception:  # noqa: BLE001
                        new_geoms.append(g)
                else:
                    new_geoms.append(g)
            df = df.set_geometry(gpd.GeoSeries(new_geoms, crs=df.crs))
            if fixed_n:
                out["method"].append(f"shapely make_valid（{fixed_n} 个无效几何）")
                changed = True

        # step2: whitebox clean_vector（修要素间拓扑）。
        # 仅当 shapely 修了东西、有空几何，或 reasons 暗示要素间问题时才调用。
        reasons_str = " ".join(reasons or []).lower()
        need_clean = (
            changed or b_empty > 0 or b_null > 0
            or "overlap" in reasons_str or "gap" in reasons_str
        )
        if need_clean:
            # 所有 whitebox I/O 都在临时目录，绝不污染用户数据目录
            tmp_dir = tempfile.mkdtemp(prefix="topoclean_")
            clean_in = os.path.join(tmp_dir, "in.shp")
            clean_out = os.path.join(tmp_dir, "out.shp")
            df.to_file(clean_in, driver="ESRI Shapefile", engine="pyogrio")
            res = _run_clean_vector(clean_in, clean_out)
            out["whitebox_rc"] = res.get("returncode")
            if res.get("success") and os.path.exists(clean_out):
                import geopandas as gpd  # type: ignore

                cleaned = gpd.read_file(clean_out)
                if cleaned.crs is None and df.crs is not None:
                    cleaned = cleaned.set_crs(df.crs)
                _write_df(cleaned, datasource, layer)
                out["method"].append("whitebox clean_vector")
                changed = True
            else:
                err = str(res.get("error", "")).strip()
                out["error"] = (out.get("error") + " " + err).strip() if out.get("error") else err
                # clean_vector 失败时，至少把 step1 的 make_valid 落盘
                if changed:
                    _write_df(df, datasource, layer)
        elif changed:
            # 无需 clean_vector，但 shapely 已改 → 落盘 make_valid 结果
            _write_df(df, datasource, layer)

        after = scan_topology(path)
        out["after"] = {
            "invalid": after.get("invalid", 0),
            "empty": after.get("empty", 0),
            "null_geom": after.get("null_geom", 0),
        }
        out["repaired"] = changed
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[topology] repair_topology(%s) failed: %s", path, e)
        out["error"] = str(e)
        return out
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
