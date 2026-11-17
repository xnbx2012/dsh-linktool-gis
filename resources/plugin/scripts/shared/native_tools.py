# -*- coding: utf-8 -*-
"""纯 Python 自定义 GIS 工具（geopandas / shapely / rasterio / numpy，无 arcpy、无 whitebox）。

补全 WhiteboxTools 缺失的常用 GIS 能力（投影、矢量缓冲/近邻/空间连接、各类叠加、
字段增删改算、波段合成/栅格统计/常量栅格等）。对外仍由 arcgis-mcp-server 的
`execute_gis_tool` 统一调用：`_is_custom_tool` 命中即走本模块，否则降级 whitebox。

设计约定（与 main.py 一致，避免已知陷阱）：
- 本模块在 main.py 顶部已 `import geoprio/rasterio/geopandas/shapely`（GDAL C 扩展首次
  初始化在 mcp.run() 之前完成）后才被延迟 import，故模块级 import 这些库是安全的
  （二次 import 命中 sys.modules，不再触发 C 扩展初始化）。
- 每个工具 `tool_xxx(parameters: dict) -> dict`，返回与 execute_gis_tool 同形的字典：
  {success, output, error, messages, output_paths}。output_paths 由工具**显式**返回
  （不耦合 whitebox 的 _OUTPUT_KEYS），供 _postprocess_and_serialize 写 .gis-result.json
  与嵌入 GeoJSON。
- 多输入工具先断言 CRS 一致，不一致直接报错（提示用 `project`），绝不静默重投影。
- 网络分析（最短路径/服务区/最近设施点/OD 矩阵）不在本模块范围。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import geopandas as gpd  # noqa: E402  —— 见模块 docstring 说明，二次 import 安全
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from shapely.geometry import LineString, Point, Polygon  # noqa: F401
from shapely import wkt as _wkt  # noqa: F401

# 复用 gis_io 的路径拆分与 GeoJSON 嵌入（与本模块同目录 shared/）。
from gis_io import _split_path, embed_geojson  # noqa: E402


# ─── 通用工具：参数取值 / 路径判定 / 读写封装 ────────────────────────────────────
def _get(parameters: dict, *keys: str, default: Any = ...) -> Any:
    """大小写不敏感取参数：依次尝试 keys（去空白小写）匹配 parameters 的 key。"""
    plower = {k.lower().strip(): k for k in (parameters or {})}
    for k in keys:
        kk = k.lower().strip()
        if kk in plower:
            return parameters[plower[kk]]
    if default is not ...:
        return default
    raise KeyError(keys[0])


def _require(parameters: dict, *keys: str) -> Any:
    """取必填参数；缺失返回友好的 KeyError。"""
    return _get(parameters, *keys)


def _missing(*keys: str) -> dict[str, Any]:
    return {
        "success": False,
        "output": None,
        "error": f"缺少必填参数（候选键名）：{list(keys)}",
        "messages": [],
        "output_paths": [],
    }


def _is_gdb_logical_path(path: str) -> bool:
    """是否为 GDB 内逻辑图层（'xxx.gdb/图层名'，且非 .shp/.tif 等普通文件）。"""
    p = str(path).replace("\\", "/")
    low = p.lower()
    idx = low.find(".gdb/")
    if idx < 0:
        return False
    suffix = p[idx + 5:]
    if suffix.lower().endswith((".shp", ".tif", ".tiff", ".csv", ".txt", ".geojson")):
        return False
    return bool(suffix.strip())


def _is_raster_path(path: str) -> bool:
    return str(path).replace("\\", "/").lower().endswith((".tif", ".tiff", ".vrt"))


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _read_vector(path: str) -> gpd.GeoDataFrame:
    ds, layer = _split_path(str(path))
    if not os.path.exists(ds):
        raise FileNotFoundError(f"数据不存在: {path}")
    return gpd.read_file(ds, layer=layer)


def _write_vector(gdf: gpd.GeoDataFrame, path: str, *, geometry_type: str | None = None) -> str:
    """写矢量到 .shp 或 GDB 要素类。GDB 逻辑路径走 pyogrio OpenFileGDB。

    geometry_type 仅在创建空要素类（create_feature_class）时显式指定；派生输出省略，
    让 pyogrio 推断，避免 Polygon↔MultiPolygon 类型冲突。
    """
    p = str(path).replace("\\", "/")
    low = p.lower()
    kw: dict[str, Any] = {}
    if geometry_type:
        kw["geometry_type"] = geometry_type
    if ".gdb/" in low or low.endswith(".gdb"):
        ds, layer = _split_path(p)
        if not layer:
            raise ValueError(f"无法解析 GDB 要素类输出路径: {path}")
        _ensure_parent(ds)
        pyogrio.write_dataframe(
            gdf, ds, layer=layer, driver="OpenFileGDB",
            layer_options={"TARGET_ARCGIS_VERSION": "ARCGIS_PRO_3_2_OR_LATER"},
            **kw,
        )
    else:
        _ensure_parent(p)
        pyogrio.write_dataframe(gdf, p, **kw)
    return p


def _crs_equal(a: gpd.GeoDataFrame, b: gpd.GeoDataFrame) -> str | None:
    """两输入 CRS 是否一致；不一致返回中文错误（提示先用 project）。"""
    ca, cb = a.crs, b.crs
    if ca is None and cb is None:
        return None
    try:
        if ca is not None and cb is not None and ca.equals(cb):
            return None
    except Exception:  # noqa: BLE001
        pass
    return (
        f"输入 CRS 不一致（{ca} vs {cb}）。请先用 project 工具统一投影后再做空间叠加/连接。"
    )


def _ok(output_paths: list[str], message: str = "", **extra: Any) -> dict[str, Any]:
    """构造成功返回。"""
    r: dict[str, Any] = {
        "success": True,
        "output": message or "完成",
        "error": None,
        "messages": [message] if message else [],
        "output_paths": output_paths,
    }
    r.update(extra)
    return r


def _fail(error: str, **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "success": False,
        "output": None,
        "error": error,
        "messages": [],
        "output_paths": [],
    }
    r.update(extra)
    return r


# ─── 1. 投影（矢量 + 栅格）────────────────────────────────────────────────────
def _parse_crs(crs: Any):
    """EPSG:XXXX / 整数 EPSG / WKT → geopandas/rasterio 可识别的 crs。"""
    if crs is None:
        return None
    if isinstance(crs, int):
        return f"EPSG:{crs}"
    s = str(crs).strip()
    if s.isdigit():
        return f"EPSG:{s}"
    return s


def tool_project(parameters: dict) -> dict[str, Any]:
    """矢量 to_crs / 栅格 warp.reproject。target_crs 支持 EPSG:XXXX 或整数。"""
    try:
        inp = _require(parameters, "input", "in_features", "i")
        target = _require(parameters, "target_crs", "out_crs", "sr", "spatial_reference")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    target_crs = _parse_crs(target)

    # 栅格分支
    if _is_raster_path(inp):
        return _project_raster(inp, target_crs, out)
    # 矢量分支
    try:
        gdf = _read_vector(inp)
        if gdf.crs is None:
            return _fail(f"输入矢量无 CRS，无法投影：{inp}")
        out_gdf = gdf.to_crs(target_crs)
        _write_vector(out_gdf, out)
        return _ok([out], f"矢量投影完成：{gdf.crs} → {target_crs}，{len(out_gdf)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"矢量投影失败：{e}")


def _project_raster(inp: str, target_crs: Any, out: str) -> dict[str, Any]:
    try:
        with rasterio.open(inp) as src:
            if src.crs is None:
                return _fail(f"输入栅格无 CRS，无法投影：{inp}")
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds
            )
            kwargs = src.meta.copy()
            kwargs.update({
                "crs": target_crs, "transform": transform,
                "width": width, "height": height,
            })
            # 若输出目标是 GDB 逻辑路径，降级为旁挂 .tif
            actual_out, note = _resolve_raster_out(out)
            with rasterio.open(actual_out, "w", **kwargs) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform, src_crs=src.crs,
                        dst_transform=transform, dst_crs=target_crs,
                        resampling=Resampling.nearest,
                    )
        msg = f"栅格投影完成：{src.crs} → {target_crs} → {actual_out}"
        if note:
            msg += f"（{note}）"
        return _ok([actual_out], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"栅格投影失败：{e}")


def _resolve_raster_out(out: str) -> tuple[str, str | None]:
    """GDB 逻辑栅格输出 → 旁挂 .tif（GDAL 不支持写 GDB 栅格）。"""
    if _is_gdb_logical_path(out):
        ds, layer = _split_path(str(out))
        side = os.path.join(ds, f"{layer}.tif")
        return side, "GDAL OpenFileGDB 不支持写 GDB 栅格，已降级为旁挂 .tif"
    return str(out), None


# ─── 7b. 矢量简化 ──────────────────────────────────────────────────────────────
def tool_simplify(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features", "i")
        tol = float(_require(parameters, "tolerance", "max_offset"))
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        gdf = _read_vector(inp)
        simp = gdf.copy()
        simp.geometry = gdf.geometry.simplify(tol, preserve_topology=True)
        _write_vector(simp, out)
        return _ok([out], f"简化完成（容差 {tol}）：{len(simp)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"简化失败：{e}")


# ─── 11. 矢量缓冲区 ────────────────────────────────────────────────────────────
def tool_buffer(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features", "i")
        dist = float(_require(parameters, "distance", "buffer_distance"))
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    dissolve = bool(_get(parameters, "dissolve", default=False))
    try:
        gdf = _read_vector(inp)
        if gdf.crs is not None and getattr(gdf.crs, "is_geographic", False):
            return _fail(
                "输入为地理坐标系（度），缓冲距离单位为度无意义。请先用 project 投影到投影坐标系。"
            )
        if dissolve:
            merged = gdf.dissolve()
            merged.geometry = merged.geometry.buffer(dist, resolution=16)
            out_gdf = merged.reset_index(drop=True)
        else:
            out_gdf = gdf.copy()
            out_gdf.geometry = gdf.geometry.buffer(dist, resolution=16)
        _write_vector(out_gdf, out)
        return _ok([out], f"缓冲完成（距离 {dist}，dissolve={dissolve}）：{len(out_gdf)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"缓冲失败：{e}")


# ─── 12. 近邻分析 ──────────────────────────────────────────────────────────────
def tool_near(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features")
        near_f = _require(parameters, "near", "near_features", "join")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    max_distance = _get(parameters, "max_distance", "search_radius", default=None)
    try:
        a = _read_vector(inp)
        b = _read_vector(near_f)
        err = _crs_equal(a, b)
        if err:
            return _fail(err)
        kw: dict[str, Any] = {"how": "left", "distance_col": "NEAR_DIST"}
        if max_distance is not None:
            kw["max_distance"] = float(max_distance)
        res = gpd.sjoin_nearest(a, b, **kw)
        _write_vector(res, out)
        return _ok([out], f"近邻分析完成：{len(res)} 要素，已附 NEAR_DIST → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"近邻分析失败：{e}")


# ─── 10b. 范围内汇总（矢量按面汇总）───────────────────────────────────────────
def tool_summarize_within(parameters: dict) -> dict[str, Any]:
    try:
        zones_p = _require(parameters, "input", "in_polygons", "within_polygons")
        feat_p = _require(parameters, "in_features", "input_features", "summarize_features")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    sum_fields = _get(parameters, "sum_fields", "statistics_fields", default=None) or []
    count_field = _get(parameters, "count_field", default="COUNT")
    predicate = _get(parameters, "predicate", default="within")
    try:
        zones = _read_vector(zones_p)
        feats = _read_vector(feat_p)
        err = _crs_equal(zones, feats)
        if err:
            return _fail(err)
        # 每个要素落在哪个面：features within zones
        joined = gpd.sjoin(feets := feats, zones.reset_index(names="_zidx"), predicate=predicate)
        result = zones.copy().reset_index(names="_zidx")
        counts = joined.groupby("_zidx").size()
        result[count_field] = result["_zidx"].map(counts).fillna(0).astype(int)
        for f in sum_fields:
            f = _match_field(feats, f)
            sums = joined.groupby("_zidx")[f].sum()
            means = joined.groupby("_zidx")[f].mean()
            result[f"{f}_SUM"] = result["_zidx"].map(sums).astype(object)
            result[f"{f}_MEAN"] = result["_zidx"].map(means).astype(object)
        result = result.drop(columns=["_zidx"])
        _write_vector(result, out)
        return _ok([out], f"范围内汇总完成：{len(result)} 面，COUNT+{len(sum_fields)} 字段 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"范围内汇总失败：{e}")


def _match_field(gdf: gpd.GeoDataFrame, name: str) -> str:
    """大小写不敏感匹配 gdf 列名。"""
    lm = {c.lower(): c for c in gdf.columns}
    return lm.get(str(name).strip().lower(), str(name))


# ─── 16g. Identity 叠加 ───────────────────────────────────────────────────────
def _dedupe_cols(df: gpd.GeoDataFrame, geom_name: str) -> gpd.GeoDataFrame:
    """overlay 后丢弃 geopandas 自动产生的同名冲突列（_1/_2 后缀或重复 geometry 派生列）。

    overlay 在两输入含相同列名时会产生 suffixes 冲突；我们只保留首次出现的字段，
    以及必要的几何列。这样写回时不会触发 pyogrio 的重复列报错。
    """
    keep: list[str] = []
    seen: set[str] = set()
    for c in df.columns:
        if c == geom_name:
            keep.append(c)
            seen.add(c)
            continue
        if c in seen:
            continue
        keep.append(c)
        seen.add(c)
    return df[keep]


def tool_identity(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features")
        iden = _require(parameters, "identity", "identity_features", "overlay")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        a = _read_vector(inp)
        b = _read_vector(iden)
        err = _crs_equal(a, b)
        if err:
            return _fail(err)
        # 重命名非几何列为 a_*/b_*，避免 overlay suffixes 冲突（见 geopandas overlay 实现）
        a2 = _prefix_cols(a, "a_")
        b2 = _prefix_cols(b, "b_")
        res = gpd.overlay(a2, b2, how="identity", keep_geom_type=False)
        res = res[~res.geometry.is_empty & res.geometry.notna()].reset_index(drop=True)
        res = _dedupe_cols(res, res.geometry.name)
        _write_vector(res, out)
        return _ok([out], f"Identity 叠加完成：{len(res)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"Identity 叠加失败：{e}")


def _prefix_cols(gdf: gpd.GeoDataFrame, prefix: str) -> gpd.GeoDataFrame:
    """给非几何列加前缀，避免 overlay/sjoin 产生重复列。"""
    geom_name = gdf.geometry.name
    rename = {c: (f"{prefix}{c}" if c != geom_name else c) for c in gdf.columns}
    return gdf.rename(columns=rename)


# ─── 16h. Update 叠加 ──────────────────────────────────────────────────────────
def tool_update(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features")
        upd = _require(parameters, "update", "update_features")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        a = _read_vector(inp)
        b = _read_vector(upd)
        err = _crs_equal(a, b)
        if err:
            return _fail(err)
        kept = gpd.overlay(a, b, how="difference", keep_geom_type=False)
        import pandas as pd

        res = pd.concat([kept, b], ignore_index=True)
        res = gpd.GeoDataFrame(res, geometry="geometry", crs=a.crs)
        res = res[~res.geometry.is_empty & res.geometry.notna()].reset_index(drop=True)
        _write_vector(res, out)
        return _ok([out], f"Update 叠加完成：{len(res)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"Update 叠加失败：{e}")


# ─── 16i. 计数重叠要素 ────────────────────────────────────────────────────────
def tool_count_overlapping(parameters: dict) -> dict[str, Any]:
    """为每个要素统计与之相交的「其它」要素数，写入 OVERLAP_COUNT 字段。"""
    try:
        inp = _require(parameters, "input", "in_features")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        gdf = _read_vector(inp)
        base = gdf.reset_index(names="_oid")
        sj = gpd.sjoin(base, gdf.reset_index(names="_rid"), predicate="intersects", how="inner")
        sj = sj[sj["_oid"] != sj["_rid"]]
        counts = sj.groupby("_oid").size()
        result = gdf.copy().reset_index(names="_oid")
        result["OVERLAP_COUNT"] = result["_oid"].map(counts).fillna(0).astype(int)
        result = result.drop(columns=["_oid"])
        _write_vector(result, out)
        total = int(result["OVERLAP_COUNT"].sum())
        return _ok([out], f"重叠计数完成：共 {total} 处重叠关系 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"重叠计数失败：{e}")


# ─── 16j. 空间连接 ─────────────────────────────────────────────────────────────
def tool_spatial_join(parameters: dict) -> dict[str, Any]:
    try:
        tgt = _require(parameters, "target", "input", "left", "in_features")
        join_p = _require(parameters, "join", "join_features", "right")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    predicate = _get(parameters, "predicate", "match_option", default="intersects")
    how = _get(parameters, "join_operation", "how", default="inner")
    try:
        a = _read_vector(tgt)
        b = _read_vector(join_p)
        err = _crs_equal(a, b)
        if err:
            return _fail(err)
        res = gpd.sjoin(a, b, predicate=predicate, how=how)
        _write_vector(res, out)
        return _ok([out], f"空间连接完成（{predicate}/{how}）：{len(res)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"空间连接失败：{e}")


# ─── 16k. 移除重叠 ─────────────────────────────────────────────────────────────
def tool_remove_overlap(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features")
        rem = _require(parameters, "remove", "erase", "erase_features")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        a = _read_vector(inp)
        b = _read_vector(rem)
        err = _crs_equal(a, b)
        if err:
            return _fail(err)
        res = gpd.overlay(a, b, how="difference", keep_geom_type=False)
        res = res[~res.geometry.is_empty & res.geometry.notna()].reset_index(drop=True)
        _write_vector(res, out)
        return _ok([out], f"移除重叠完成：{len(res)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"移除重叠失败：{e}")


# ─── 16l. 分配面（按最大重叠面积）──────────────────────────────────────────────
def tool_allocate_polygons(parameters: dict) -> dict[str, Any]:
    """把每个目标面分配给与之重叠面积最大的源面，写入 ALLOCATED 字段。"""
    try:
        inp = _require(parameters, "input", "source", "source_features")
        join_p = _require(parameters, "join", "target", "target_features")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    src_field = _get(parameters, "source_field", "source_id", default=None)
    try:
        src = _read_vector(inp)
        tgt = _read_vector(join_p)
        err = _crs_equal(src, tgt)
        if err:
            return _fail(err)
        if getattr(src.crs, "is_geographic", False):
            return _fail("源/目标为地理坐标系，面积比较无意义。请先 project 到投影坐标系。")
        sid_col = src_field or _first_id_col(src)
        # 先加列前缀避免 overlay 列冲突，再单独挂 _tidx/_sidx（不加前缀，供后续 groupby）
        tgt_p = _prefix_cols(tgt, "t_").reset_index(names="_tidx")
        src_p = _prefix_cols(src, "s_").reset_index(names="_sidx")
        inter = gpd.overlay(tgt_p, src_p, how="intersection", keep_geom_type=False)
        if inter.empty:
            return _fail("目标面与源面无重叠，无法分配。")
        inter["_area"] = inter.geometry.area
        sid_actual = f"s_{sid_col}" if f"s_{sid_col}" in inter.columns else sid_col
        best = inter.sort_values("_area", ascending=False).drop_duplicates("_tidx")
        alloc = best.set_index("_tidx")[sid_actual]
        result = tgt.copy().reset_index(names="_tidx")
        result["ALLOCATED"] = result["_tidx"].map(alloc)
        result = result.drop(columns=["_tidx"])
        result = _dedupe_cols(result, result.geometry.name)
        _write_vector(result, out)
        return _ok([out], f"分配面完成：{result['ALLOCATED'].notna().sum()}/{len(result)} 已分配 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"分配面失败：{e}")


def _first_id_col(gdf: gpd.GeoDataFrame) -> str:
    """取第一个非几何列作为默认 id 列。"""
    for c in gdf.columns:
        if c != gdf.geometry.name:
            return c
    return "index"


# ─── 15f. 点转线 ───────────────────────────────────────────────────────────────
def tool_points_to_line(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_features")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    line_field = _get(parameters, "line_field", "group_field", default=None)
    sort_field = _get(parameters, "sort_field", "order_field", default=None)
    try:
        gdf = _read_vector(inp)
        if gdf.geometry.geom_type.iloc[0] if not gdf.empty else "Point" not in ("Point", "MultiPoint"):
            pass
        df = gdf.copy()
        grp = line_field or "ALL"
        if grp == "ALL":
            df["_grp"] = 0
        else:
            df["_grp"] = df[_match_field(df, grp)]
        if sort_field:
            df = df.sort_values([_match_field(df, sort_field)])
        rows = []
        for key, sub in df.groupby("_grp"):
            pts = [p for g in sub.geometry for p in (getattr(g, "geoms", [g]))]
            if len(pts) >= 2:
                rows.append({"LINE_ID": key, "geometry": LineString(pts)})
        if not rows:
            return _fail("点数不足，无法生成线（每组至少 2 个点）。")
        out_gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=gdf.crs)
        _write_vector(out_gdf, out)
        return _ok([out], f"点转线完成：{len(out_gdf)} 条线 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"点转线失败：{e}")


# ─── 17a. 创建空要素类 ─────────────────────────────────────────────────────────
_TYPE_MAP: dict[str, Any] = {
    "TEXT": object, "STRING": object, "STR": object,
    "SHORT": "Int16", "INTEGER": "Int32", "LONG": "Int64", "INT": "Int32", "BIGINT": "Int64",
    "DOUBLE": "float64", "FLOAT": "float64", "SINGLE": "float32",
    "DATE": "datetime64[ns]", "DATETIME": "datetime64[ns]",
}


def _dtype_for(ftype: str):
    return _TYPE_MAP.get(str(ftype).strip().upper(), object)


def tool_create_feature_class(parameters: dict) -> dict[str, Any]:
    try:
        out = _require(parameters, "output", "out_path", "out_feature_class")
        geom_type = _get(parameters, "geometry_type", "shape_type", default="Point")
    except KeyError as e:
        return _missing(str(e))
    crs = _parse_crs(_get(parameters, "spatial_reference", "crs", default=None))
    fields = _get(parameters, "fields", default=None) or []
    try:
        # 构造空 GeoDataFrame
        data: dict[str, Any] = {}
        for f in fields:
            name = f.get("name") if isinstance(f, dict) else f
            ftype = f.get("type", "TEXT") if isinstance(f, dict) else "TEXT"
            data[str(name)] = pd.Series(dtype=_dtype_for(ftype))
        gdf = gpd.GeoDataFrame(data, geometry=gpd.GeoSeries([], crs=crs), crs=crs)
        _write_vector(gdf, out, geometry_type=_norm_geom_type(geom_type))
        return _ok([out], f"空要素类已创建（{geom_type}, {len(fields)} 字段）→ {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"创建要素类失败：{e}")


def _norm_geom_type(gt: str) -> str:
    g = str(gt).strip().lower()
    return {
        "point": "Point", "multipoint": "MultiPoint",
        "line": "LineString", "linestring": "LineString", "polyline": "LineString",
        "polygon": "Polygon", "multipolygon": "MultiPolygon",
    }.get(g, "Point")


# ─── 17b. 创建常量栅格 ─────────────────────────────────────────────────────────
def tool_create_constant_raster(parameters: dict) -> dict[str, Any]:
    try:
        out = _require(parameters, "output", "out")
        value = _require(parameters, "constant_value", "value", "cell_value")
    except KeyError as e:
        return _missing(str(e))
    extent = _get(parameters, "extent", default=None)  # [xmin,ymin,xmax,ymax]
    cell_size = _get(parameters, "cell_size", default=None)  # 数或 [x,y]
    dtype = _get(parameters, "data_type", "pixel_type", default="float32")
    crs = _parse_crs(_get(parameters, "crs", "spatial_reference", default=None))
    try:
        if not extent or cell_size is None:
            return _fail("创建常量栅格需提供 extent=[xmin,ymin,xmax,ymax] 与 cell_size。")
        xmin, ymin, xmax, ymax = [float(v) for v in extent]
        if isinstance(cell_size, (list, tuple)):
            cx, cy = float(cell_size[0]), float(cell_size[1])
        else:
            cx = cy = float(cell_size)
        width = max(1, int(round((xmax - xmin) / cx)))
        height = max(1, int(round((ymax - ymin) / cy)))
        np_dtype = np.dtype(dtype)
        nodata = -9999 if np.issubdtype(np_dtype, np.floating) else None
        actual_out, note = _resolve_raster_out(out)
        _ensure_parent(actual_out)
        arr = np.full((height, width), value, dtype=np_dtype)
        transform = rasterio.transform.from_bounds(xmin, ymin, xmax, ymax, width, height)
        with rasterio.open(
            actual_out, "w", driver="GTiff", height=height, width=width, count=1,
            dtype=np_dtype, crs=crs, transform=transform, nodata=nodata,
        ) as dst:
            dst.write(arr, 1)
        msg = f"常量栅格已创建（{width}x{height}, 值={value}）→ {actual_out}"
        return _ok([actual_out], msg + (f"（{note}）" if note else ""))
    except Exception as e:  # noqa: BLE001
        return _fail(f"创建常量栅格失败：{e}")


# ─── 18g. 波段合成 ─────────────────────────────────────────────────────────────
def tool_composite_bands(parameters: dict) -> dict[str, Any]:
    try:
        inputs = _require(parameters, "inputs", "input_rasters", "rasters")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    if isinstance(inputs, str):
        inputs = [inputs]
    try:
        bands = []
        ref_profile = None
        for rp in inputs:
            with rasterio.open(rp) as src:
                if ref_profile is None:
                    ref_profile = src.profile.copy()
                bands.append(src.read(1))
        if not bands:
            return _fail("无输入波段。")
        stack = np.stack(bands)
        actual_out, note = _resolve_raster_out(out)
        _ensure_parent(actual_out)
        profile = ref_profile.copy()
        profile.update(count=len(bands), driver="GTiff")
        with rasterio.open(actual_out, "w", **profile) as dst:
            for i, b in enumerate(bands, start=1):
                dst.write(b, i)
        return _ok([actual_out], f"波段合成完成：{len(bands)} 波段 → {actual_out}" + (f"（{note}）" if note else ""))
    except Exception as e:  # noqa: BLE001
        return _fail(f"波段合成失败：{e}")


# ─── 18h. 波段运算 ─────────────────────────────────────────────────────────────
def tool_band_math(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "raster")
        expr = _require(parameters, "expression", "expr", "formula")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        with rasterio.open(inp) as src:
            count = src.count
            bands = {f"b{i}": src.read(i, masked=True) for i in range(1, count + 1)}
            profile = src.profile.copy()
            nodata = src.nodata
        namespace = {"np": np, **bands}
        # 安全 eval：禁用内置
        result = eval(str(expr), {"__builtins__": {}}, namespace)  # noqa: S307 —— 受控表达式
        arr = np.ma.filled(result, nodata if nodata is not None else 0) if isinstance(result, np.ma.MaskedArray) else np.asarray(result)
        out_dtype = arr.dtype if not np.issubdtype(arr.dtype, np.floating) else "float32"
        if isinstance(result, np.ma.MaskedArray):
            arr = arr.astype(out_dtype)
        actual_out, note = _resolve_raster_out(out)
        _ensure_parent(actual_out)
        profile.update(count=1, dtype=out_dtype, driver="GTiff")
        with rasterio.open(actual_out, "w", **profile) as dst:
            dst.write(arr.astype(out_dtype), 1)
        return _ok([actual_out], f"波段运算完成（{expr}）→ {actual_out}" + (f"（{note}）" if note else ""))
    except Exception as e:  # noqa: BLE001
        return _fail(f"波段运算失败：{e}")


# ─── 18i. 计算栅格统计数据 ────────────────────────────────────────────────────
def tool_calculate_statistics(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "raster")
    except KeyError as e:
        return _missing(str(e))
    try:
        stats: list[dict[str, Any]] = []
        with rasterio.open(inp) as src:
            for i in range(1, src.count + 1):
                arr = src.read(i, masked=True)
                if arr.count() == 0:
                    stats.append({"band": i, "note": "全为 nodata"})
                    continue
                stats.append({
                    "band": i,
                    "min": float(arr.min()), "max": float(arr.max()),
                    "mean": float(arr.mean()), "std": float(arr.std()),
                    "count": int(arr.count()),
                })
        return _ok([], f"栅格统计完成：{inp}", statistics=stats)
    except Exception as e:  # noqa: BLE001
        return _fail(f"计算统计失败：{e}")


# ─── 19. 字段操作（计算/添加/删除/修改）─────────────────────────────────────────
def tool_calculate_field(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_table", "in_features")
        field = _require(parameters, "field_name", "field")
        expr = _require(parameters, "expression", "expr", "code")
    except KeyError as e:
        return _missing(str(e))
    try:
        gdf = _read_vector(inp)
        geom_name = gdf.geometry.name

        def _eval_row(row):
            ns = {c: row[c] for c in gdf.columns if c != geom_name}
            ns["area"] = float(row[geom_name].area) if row[geom_name] else 0.0
            ns["length"] = float(row[geom_name].length) if row[geom_name] else 0.0
            try:
                return eval(str(expr), {"__builtins__": {}}, ns)  # noqa: S307
            except Exception:  # noqa: BLE001
                return None

        gdf[str(field)] = gdf.apply(_eval_row, axis=1)
        _write_vector(gdf, inp)  # 覆盖写回原图层
        return _ok([inp], f"计算字段完成：{field} = {expr}，{len(gdf)} 行 → {inp}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"计算字段失败：{e}")


def tool_add_field(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_table", "in_features")
        field = _require(parameters, "field_name", "field")
    except KeyError as e:
        return _missing(str(e))
    ftype = _get(parameters, "field_type", default="TEXT")
    default = _get(parameters, "default_value", default=None)
    try:
        gdf = _read_vector(inp)
        if str(field) in gdf.columns:
            return _fail(f"字段已存在：{field}")
        dtype = _dtype_for(ftype)
        gdf[str(field)] = pd.Series(dtype=dtype) if default is None else default
        _write_vector(gdf, inp)
        return _ok([inp], f"添加字段完成：{field}（{ftype}）→ {inp}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"添加字段失败：{e}")


def tool_delete_field(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_table", "in_features")
        fields = _require(parameters, "field_name", "fields", "drop_fields")
    except KeyError as e:
        return _missing(str(e))
    if isinstance(fields, str):
        fields = [fields]
    try:
        gdf = _read_vector(inp)
        to_drop = [_match_field(gdf, f) for f in fields]
        missing = [f for f in to_drop if f not in gdf.columns]
        if missing:
            return _fail(f"字段不存在：{missing}。可用：{list(gdf.columns)}")
        gdf = gdf.drop(columns=to_drop)
        _write_vector(gdf, inp)
        return _ok([inp], f"删除字段完成：{to_drop} → {inp}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"删除字段失败：{e}")


def tool_alter_field(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "in_table", "in_features")
        field = _require(parameters, "field_name", "field")
    except KeyError as e:
        return _missing(str(e))
    new_name = _get(parameters, "new_field_name", default=None)
    new_type = _get(parameters, "new_field_type", default=None)
    try:
        gdf = _read_vector(inp)
        actual = _match_field(gdf, field)
        if actual not in gdf.columns:
            return _fail(f"字段不存在：{field}")
        if new_type:
            dtype = _dtype_for(new_type)
            gdf[actual] = gdf[actual].astype(dtype)
        if new_name:
            gdf = gdf.rename(columns={actual: str(new_name)})
        _write_vector(gdf, inp)
        return _ok([inp], f"修改字段完成：{actual} → {inp}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"修改字段失败：{e}")


# ─── tif↔GDB 栅格（仅旁挂降级，GDAL 无法真正读写 GDB 栅格）──────────────────────
def tool_raster_to_gdb_sidecar(parameters: dict) -> dict[str, Any]:
    """把 .tif 旁挂复制到 GDB 目录（GDAL OpenFileGDB 不支持栅格）。"""
    import shutil

    try:
        inp = _require(parameters, "input", "raster", "in_raster")
        out = _require(parameters, "output", "out")
    except KeyError as e:
        return _missing(str(e))
    try:
        if not _is_raster_path(inp) or not os.path.exists(inp):
            return _fail(f"输入栅格不存在或非 .tif：{inp}")
        ds, layer = _split_path(str(out))
        if not layer or ".gdb" not in ds.lower():
            # 非 GDB 目标：直接复制为指定 .tif
            _ensure_parent(str(out))
            shutil.copy2(inp, str(out))
            return _ok([str(out)], f"已复制栅格 → {out}")
        os.makedirs(ds, exist_ok=True)
        side = os.path.join(ds, f"{layer}.tif")
        shutil.copy2(inp, side)
        return _ok(
            [side],
            f"GDAL 无法写 GDB 栅格数据集，已旁挂为 .tif：{side}",
            note="GDB 栅格数据集为 ESRI 专有格式，GDAL OpenFileGDB 仅支持矢量。",
        )
    except Exception as e:  # noqa: BLE001
        return _fail(f"栅格旁挂失败：{e}")


# ─── 注册表 ────────────────────────────────────────────────────────────────────
CUSTOM_TOOL_REGISTRY: dict[str, tuple[Callable[[dict], dict], str]] = {
    "project": (tool_project, "矢量/栅格投影（geopandas to_crs / rasterio warp）"),
    "simplify": (tool_simplify, "矢量简化 Douglas-Peucker（geopandas simplify）"),
    "buffer": (tool_buffer, "矢量缓冲区（geopandas buffer）；栅格缓冲请用 whitebox buffer_raster"),
    "near": (tool_near, "近邻分析（geopandas sjoin_nearest，附 NEAR_DIST）"),
    "summarize_within": (tool_summarize_within, "范围内汇总：按面统计落入要素计数与字段聚合（sjoin+groupby）"),
    "identity": (tool_identity, "Identity 叠加（geopandas overlay how=identity）"),
    "update": (tool_update, "Update 叠加：用 update 几何替换 input 重叠区（overlay difference+concat）"),
    "count_overlapping": (tool_count_overlapping, "计数重叠要素：每要素统计相交的其它要素数（sjoin+groupby）"),
    "spatial_join": (tool_spatial_join, "空间连接（geopandas sjoin，predicate/operation 可选）"),
    "remove_overlap": (tool_remove_overlap, "移除重叠（overlay difference）"),
    "allocate_polygons": (tool_allocate_polygons, "分配面：按最大重叠面积把目标面分配给源面"),
    "points_to_line": (tool_points_to_line, "点转线（groupby 分组 + shapely LineString）"),
    "create_feature_class": (tool_create_feature_class, "创建空要素类（pyogrio schema 写，含字段定义）"),
    "create_constant_raster": (tool_create_constant_raster, "创建常量栅格（rasterio + numpy.full）"),
    "composite_bands": (tool_composite_bands, "波段合成（rasterio 多单波段叠成多波段）"),
    "band_math": (tool_band_math, "波段运算（rasterio masked 读 + numpy 表达式 b1/b2..）"),
    "calculate_statistics": (tool_calculate_statistics, "栅格全局统计 min/max/mean/std（忽略 nodata）"),
    "calculate_field": (tool_calculate_field, "计算字段（逐行表达式，可用 area/length 与其它字段）"),
    "add_field": (tool_add_field, "添加字段（TEXT/INTEGER/DOUBLE/DATE）"),
    "delete_field": (tool_delete_field, "删除字段"),
    "alter_field": (tool_alter_field, "修改字段（重命名 / 改类型）"),
    "raster_to_gdb_sidecar": (tool_raster_to_gdb_sidecar, "tif 旁挂到 GDB 目录（GDAL 无法写 GDB 栅格）"),
}


# ─── 内置工具参数 schema（供 param-validate/schema.json 导出参数要求）────────────
# 结构与 schema.json 的 whitebox 段一致：
#   {tool_name: {"required": ["input","output",...], "params": {key: {optional, parameter_type, description}}}}
# required 取自各 tool_xxx 的 _require(...) 必填键（含别名）；parameter_type 用语义标签
# （ExistingFile=输入路径存在 / NewFile=输出路径 / Flag=布尔 / 其它=普通值）。
INNER_PARAM_SCHEMA: dict[str, dict[str, Any]] = {
    "project": {
        "required": ["input", "target_crs", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量/栅格"},
            "target_crs": {"optional": False, "parameter_type": "String", "description": "目标 CRS（EPSG:XXXX 或整数）"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出路径"},
        },
    },
    "simplify": {
        "required": ["input", "tolerance", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "tolerance": {"optional": False, "parameter_type": "Double", "description": "简化容差（地图单位）"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
        },
    },
    "buffer": {
        "required": ["input", "distance", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量（需投影坐标系）"},
            "distance": {"optional": False, "parameter_type": "Double", "description": "缓冲距离（地图单位）"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "dissolve": {"optional": True, "parameter_type": "Flag", "description": "是否合并缓冲区"},
        },
    },
    "near": {
        "required": ["input", "near", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "near": {"optional": False, "parameter_type": "ExistingFile", "description": "近邻要素"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量（附 NEAR_DIST）"},
            "max_distance": {"optional": True, "parameter_type": "Double", "description": "搜索半径"},
        },
    },
    "summarize_within": {
        "required": ["in_polygons", "input_features", "output"],
        "params": {
            "in_polygons": {"optional": False, "parameter_type": "ExistingFile", "description": "范围面"},
            "input_features": {"optional": False, "parameter_type": "ExistingFile", "description": "落入要素"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出面（带 COUNT/聚合）"},
            "sum_fields": {"optional": True, "parameter_type": "String", "description": "聚合数值字段列表"},
        },
    },
    "identity": {
        "required": ["input", "identity", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "identity": {"optional": False, "parameter_type": "ExistingFile", "description": "identity 叠加层"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
        },
    },
    "update": {
        "required": ["input", "update", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "update": {"optional": False, "parameter_type": "ExistingFile", "description": "update 替换层"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
        },
    },
    "count_overlapping": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量（带 OVERLAP_COUNT）"},
        },
    },
    "spatial_join": {
        "required": ["target", "join", "output"],
        "params": {
            "target": {"optional": False, "parameter_type": "ExistingFile", "description": "目标矢量"},
            "join": {"optional": False, "parameter_type": "ExistingFile", "description": "连接矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "predicate": {"optional": True, "parameter_type": "String", "description": "intersects/within/contains"},
        },
    },
    "remove_overlap": {
        "required": ["input", "remove", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "remove": {"optional": False, "parameter_type": "ExistingFile", "description": "要移除的重叠层"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
        },
    },
    "allocate_polygons": {
        "required": ["input", "join", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "源面"},
            "join": {"optional": False, "parameter_type": "ExistingFile", "description": "目标面"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出面（带 ALLOCATED）"},
            "source_field": {"optional": True, "parameter_type": "String", "description": "源 id 字段"},
        },
    },
    "points_to_line": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入点矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出线矢量"},
            "line_field": {"optional": True, "parameter_type": "String", "description": "分组字段"},
            "sort_field": {"optional": True, "parameter_type": "String", "description": "排序字段"},
        },
    },
    "create_feature_class": {
        "required": ["output"],
        "params": {
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出空要素类路径"},
            "geometry_type": {"optional": True, "parameter_type": "String", "description": "Point/LineString/Polygon"},
            "spatial_reference": {"optional": True, "parameter_type": "String", "description": "CRS"},
            "fields": {"optional": True, "parameter_type": "String", "description": "字段定义列表"},
        },
    },
    "create_constant_raster": {
        "required": ["output", "value", "extent", "cell_size"],
        "params": {
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "value": {"optional": False, "parameter_type": "Double", "description": "常量值"},
            "extent": {"optional": False, "parameter_type": "String", "description": "[xmin,ymin,xmax,ymax]"},
            "cell_size": {"optional": False, "parameter_type": "Double", "description": "像元大小"},
            "crs": {"optional": True, "parameter_type": "String", "description": "CRS"},
            "data_type": {"optional": True, "parameter_type": "String", "description": "如 float32"},
        },
    },
    "composite_bands": {
        "required": ["inputs", "output"],
        "params": {
            "inputs": {"optional": False, "parameter_type": "ExistingFile", "description": "单波段栅格列表"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "多波段输出栅格"},
        },
    },
    "band_math": {
        "required": ["input", "expression", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入多波段栅格"},
            "expression": {"optional": False, "parameter_type": "String", "description": "numpy 表达式（b1/b2..）"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
        },
    },
    "calculate_statistics": {
        "required": ["input"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
        },
    },
    "calculate_field": {
        "required": ["input", "field_name", "expression"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量/表"},
            "field_name": {"optional": False, "parameter_type": "String", "description": "字段名"},
            "expression": {"optional": False, "parameter_type": "String", "description": "表达式（可用 area/length）"},
        },
    },
    "add_field": {
        "required": ["input", "field_name"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量/表"},
            "field_name": {"optional": False, "parameter_type": "String", "description": "新字段名"},
            "field_type": {"optional": True, "parameter_type": "String", "description": "TEXT/INTEGER/DOUBLE/DATE"},
        },
    },
    "delete_field": {
        "required": ["input", "field_name"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量/表"},
            "field_name": {"optional": False, "parameter_type": "String", "description": "待删字段（可多个）"},
        },
    },
    "alter_field": {
        "required": ["input", "field_name"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量/表"},
            "field_name": {"optional": False, "parameter_type": "String", "description": "原字段名"},
            "new_field_name": {"optional": True, "parameter_type": "String", "description": "新字段名"},
            "new_field_type": {"optional": True, "parameter_type": "String", "description": "新类型"},
        },
    },
    "raster_to_gdb_sidecar": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 .tif"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "GDB 目录或 .tif 目标"},
        },
    },
}
