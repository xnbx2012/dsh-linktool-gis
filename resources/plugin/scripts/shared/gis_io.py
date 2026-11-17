# -*- coding: utf-8 -*-
"""共享 GIS 读写封装（GDAL/OGR 后端，无 arcpy）。

提供 arcgis-mcp-server 与各 Hook 共用的只读 GIS 操作：列 GDB 图层、查属性、取元信息、
取字段唯一值、把矢量转 WGS84 GeoJSON（供 execute_gis_tool 嵌入与 auto-push-hook 推送）。

历史：曾由 `shared/find_arcpy.py`（持久 worker / 跨进程 daemon / 解释器探测）经 arcgispro-py3
子进程执行 arcpy 实现。本模块以 pyogrio/geopandas/rasterio（GDAL/OGR 绑定）重写，
进程内直调，无冷启动、无 ArcGIS Pro 依赖。

GDB 读取依赖 GDAL 的 OpenFileGDB（只读）驱动；栅格读取用 rasterio（GTiff 等）。
路径约定：
  - .gdb 要素类：'<gdb_dir>/<图层名>'（pyogrio 以 layer= 解析）
  - .shp：文件路径直接读
"""

import json
import os
from typing import Any

WGS84_CRS = "EPSG:4326"
MAX_STRING_LEN = 500


def repair_proj_env() -> None:
    """修复机器残留的 PROJ/GDAL 环境变量（PROJ_LIB / PROJ_DATA / GDAL_DATA）。

    装过 PostgreSQL/PostGIS 的机器常见残留：PROJ_LIB 指向 PostGIS 自带的过老
    proj.db（DATABASE.LAYOUT.VERSION.MINOR=0）、GDAL_DATA 指向 postgis 的
    gdal-data。rasterio/pyogrio 优先读这些环境变量，任何 EPSG 查询都会失败
    （"It comes from another PROJ installation"）。仅当现有值缺少应有的数据
    文件时，改回 rasterio wheel 自带的数据目录；不覆盖正确的显式配置。
    在 GDAL/OGR C 扩展首次定位 proj.db 之前调用（首次 EPSG 查询前即可）。
    """
    try:
        import rasterio as _rio  # type: ignore
    except Exception:  # noqa: BLE001 —— 无 rasterio 时无从修复，保持现状
        return
    rio_dir = os.path.dirname(_rio.__file__)
    wheel_proj = os.path.join(rio_dir, "proj_data")
    wheel_gdal = os.path.join(rio_dir, "gdal_data")
    for var in ("PROJ_LIB", "PROJ_DATA"):
        cur = os.environ.get(var, "")
        if not os.path.isfile(os.path.join(cur, "proj.db")) and os.path.isfile(os.path.join(wheel_proj, "proj.db")):
            os.environ[var] = wheel_proj
    if not os.path.isfile(os.path.join(os.environ.get("GDAL_DATA", ""), "gdalvrt.xsd")) \
            and os.path.isfile(os.path.join(wheel_gdal, "gdalvrt.xsd")):
        os.environ["GDAL_DATA"] = wheel_gdal


def _import_pyogrio():
    import pyogrio  # type: ignore

    return pyogrio


def _import_geopandas():
    import geopandas  # type: ignore

    return geopandas


def _to_list(val: Any) -> list[Any]:
    """把 pyogrio read_info 返回的 numpy 数组/标量安全转为 Python list。"""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        # numpy ndarray
        return val.tolist()
    except Exception:  # noqa: BLE001
        pass
    return list(val)


def _split_path(path: str) -> tuple[str, str | None]:
    """把 '<gdb>/图层名' 或 '.../x.shp' 拆成 (数据源, 图层名)。

    .gdb 路径：最后一段是图层名，前面是 gdb 目录。
    .shp：整段是文件，图层名为 None。
    """
    p = path.replace("\\", "/")
    if not p:
        return path, None
    # .gdb 要素类：形如 D:/x/y.gdb/图层名
    gdb_marker = ".gdb/"
    idx = p.lower().find(gdb_marker)
    if idx >= 0:
        gdb_dir = p[: idx + len(".gdb")]
        layer = p[idx + len(".gdb"):].strip("/")
        return gdb_dir, layer or None
    if p.lower().endswith(".gdb"):
        return p, None
    return p, None  # .shp 等普通文件


# ─── list_gdb_contents ────────────────────────────────────────────────────────
def list_gdb_layers(gdb_path: str) -> dict[str, Any]:
    """列出 .gdb（或目录）内的图层/表，分类返回，字段形状兼容旧 arcpy 版本。"""
    pyogrio = _import_pyogrio()
    p = gdb_path.replace("\\", "/")
    if not os.path.exists(p):
        return {"success": False, "error": f"GDB 路径不存在: {gdb_path}"}

    contents: dict[str, list[dict[str, Any]]] = {
        "feature_classes": [],
        "raster_datasets": [],
        "tables": [],
        "feature_datasets": [],
        "topologies": [],
        "network_datasets": [],
        "other": [],
    }

    try:
        layers = pyogrio.list_layers(p)  # ndarray: [[name, geom_type], ...]
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取 GDB 图层失败: {e}"}

    for row in layers:
        name = str(row[0])
        geom_type = row[1] if len(row) > 1 else None
        full_path = f"{p}/{name}"
        item: dict[str, Any] = {
            "name": name,
            "path": full_path,
            "dataType": "Table",
        }
        # geom_type 为 None / None → 表；有几何 → 要素类
        if geom_type and str(geom_type) != "None":
            item["dataType"] = "FeatureClass"
            item["shapeType"] = str(geom_type)
            try:
                info = pyogrio.read_info(p, layer=name)
                item["fieldCount"] = len(_to_list(info.get("fields")))
            except Exception:  # noqa: BLE001
                pass
            contents["feature_classes"].append(item)
        else:
            item["dataType"] = "Table"
            contents["tables"].append(item)

    return {
        "success": True,
        "gdb_path": p,
        "contents": contents,
    }


# ─── query_feature_attributes ────────────────────────────────────────────────
def _map_ogr_type(ogr_type: str) -> str:
    """OGR 类型 → 旧 arcpy 兼容的 type 字符串。"""
    t = str(ogr_type)
    mapping = {
        "OFTString": "String",
        "OFTInteger": "Integer",
        "OFTInteger64": "Integer",
        "OFTReal": "Double",
        "OFTDate": "Date",
        "OFTDateTime": "Date",
        "OFTTime": "Date",
        "OFTBinary": "Blob",
    }
    return mapping.get(t, t)


def query_attributes(
    feature_path: str,
    sql_where: str = "",
    max_records: int = 100,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """查属性表，支持 SQL WHERE 筛选、字段子集、抽样截断。"""
    pyogrio = _import_pyogrio()
    gpd = _import_geopandas()
    datasource, layer = _split_path(feature_path)

    if not os.path.exists(datasource):
        return {"success": False, "error": f"数据不存在: {feature_path}"}

    try:
        info = pyogrio.read_info(datasource, layer=layer)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取图层信息失败: {e}"}

    all_fields = _to_list(info.get("fields"))
    ogr_types = _to_list(info.get("ogr_types"))
    field_defs = []
    for i, fn in enumerate(all_fields):
        field_defs.append(
            {
                "name": fn,
                "alias": fn,
                "type": _map_ogr_type(ogr_types[i]) if i < len(ogr_types) else "String",
                "length": None,
            }
        )

    # 字段子集（大小写不敏感）
    if fields:
        lower_map = {fn.lower(): fn for fn in all_fields}
        selected = []
        unknown = []
        for rf in fields:
            actual = lower_map.get(rf.lower())
            if actual is None:
                unknown.append(rf)
            else:
                selected.append(actual)
        if unknown:
            return {
                "success": False,
                "error": f"字段不存在: {unknown}。可用字段: {all_fields}",
            }
        query_fields = selected
        returned_fields = [f for f in field_defs if f["name"] in selected]
    else:
        query_fields = all_fields
        returned_fields = field_defs

    read_kwargs: dict[str, Any] = {
        "layer": layer,
        "max_features": max_records,
        "read_geometry": False,
    }
    if query_fields:
        read_kwargs["columns"] = query_fields
    if sql_where:
        read_kwargs["where"] = sql_where

    try:
        df = pyogrio.read_dataframe(datasource, **read_kwargs)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取属性失败: {e}"}

    data = []
    for _, row in df.iterrows():
        rd = {}
        for col in df.columns:
            v = row[col]
            if v is None:
                rd[col] = None
            elif isinstance(v, (int, float, bool)):
                rd[col] = v
            elif isinstance(v, str):
                rd[col] = v if len(v) <= MAX_STRING_LEN else v[:MAX_STRING_LEN] + "…[truncated]"
            else:
                rd[col] = str(v)
        data.append(rd)

    total_count = int(_to_list([info.get("features", len(data))])[0] if info.get("features") is not None else len(data))

    return {
        "success": True,
        "feature_path": feature_path,
        "total_records": total_count,
        "returned_records": len(data),
        "truncated": len(data) < total_count,
        "fields": returned_fields,
        "data": data,
    }


# ─── get_data_properties ──────────────────────────────────────────────────────
def _wkid_from_crs(crs: Any) -> int | None:
    """从 geopandas/rasterio crs 对象取 EPSG WKID。"""
    if crs is None:
        return None
    try:
        # geopandas CRS / rasterio CRS 都有 to_epsg()
        ep = crs.to_epsg() if hasattr(crs, "to_epsg") else None
        if ep:
            return int(ep)
    except Exception:  # noqa: BLE001
        pass
    return None


def data_properties(data_path: str) -> dict[str, Any]:
    """取矢量/栅格数据元信息，字段形状兼容旧 arcpy 版本。"""
    p = data_path.replace("\\", "/")
    if not os.path.exists(p):
        # 可能是 GDB 要素类逻辑路径，拆分后判断数据源
        datasource, layer = _split_path(p)
        if not os.path.exists(datasource):
            return {"success": False, "error": f"数据不存在: {data_path}"}

    lower = p.lower()
    datasource, layer = _split_path(p)

    # ── 矢量分支 ──
    is_vector = lower.endswith(".shp") or ".gdb" in lower
    if is_vector:
        try:
            return _vector_properties(datasource, layer, data_path)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": f"读取矢量属性失败: {e}"}

    # ── 栅格分支 ──
    try:
        return _raster_properties(p, data_path)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取栅格属性失败: {e}"}


def _vector_properties(datasource: str, layer: str | None, data_path: str) -> dict[str, Any]:
    pyogrio = _import_pyogrio()
    gpd = _import_geopandas()
    info = pyogrio.read_info(datasource, layer=layer)

    all_fields = _to_list(info.get("fields"))
    ogr_types_list = _to_list(info.get("ogr_types"))
    fields = []
    for i, fn in enumerate(all_fields):
        fields.append(
            {
                "name": fn,
                "alias": fn,
                "type": _map_ogr_type(ogr_types_list[i]) if i < len(ogr_types_list) else "String",
                "length": None,
                "nullable": None,
            }
        )

    crs_str = info.get("crs")
    crs_obj = None
    try:
        crs_obj = gpd.array.CRS.from_user_input(crs_str) if crs_str else None
    except Exception:  # noqa: BLE001
        try:
            from pyproj import CRS  # type: ignore

            if crs_str:
                crs_obj = CRS.from_user_input(crs_str)
        except Exception:  # noqa: BLE001
            crs_obj = None

    wkid = _wkid_from_crs(crs_obj)
    bounds_raw = info.get("total_bounds")  # numpy array (minx, miny, maxx, maxy)
    bounds = _to_list(bounds_raw)
    extent = None
    if bounds is not None and len(bounds) == 4:
        extent = {
            "xmin": bounds[0], "ymin": bounds[1],
            "xmax": bounds[2], "ymax": bounds[3],
        }

    props: dict[str, Any] = {
        "success": True,
        "data_path": data_path,
        "data_type": "FeatureClass",
        "name": info.get("layer_name") or layer,
        "coordinate_system": {
            "name": str(crs_str) if crs_str else None,
            "factory_code": wkid,
            "wkid": wkid,
            "wkt": crs_obj.to_wkt() if crs_obj and hasattr(crs_obj, "to_wkt") else None,
            "unit": None,
        },
        "extent": extent,
        "fields": fields,
        "shape_type": str(info.get("geometry_type") or ""),
        "feature_count": int(_to_list([info.get("features")])[0] or 0) if info.get("features") is not None else 0,
    }
    return props


def _raster_properties(p: str, data_path: str) -> dict[str, Any]:
    import rasterio  # type: ignore

    with rasterio.open(p) as ds:
        wkid = ds.crs.to_epsg() if ds.crs and hasattr(ds.crs, "to_epsg") else None
        bounds = ds.bounds
        extent = {
            "xmin": bounds.left, "ymin": bounds.bottom,
            "xmax": bounds.right, "ymax": bounds.top,
        }
        nodata = ds.nodata
        # 值域（取第一波段统计，可能为 None）
        try:
            import numpy as np  # type: ignore

            arr = ds.read(1, masked=True)
            value_range = {
                "minimum": float(arr.min()) if arr.count() else None,
                "maximum": float(arr.max()) if arr.count() else None,
            }
        except Exception:  # noqa: BLE001
            value_range = None

        props = {
            "success": True,
            "data_path": data_path,
            "data_type": "RasterDataset",
            "name": os.path.basename(p),
            "coordinate_system": {
                "name": str(ds.crs) if ds.crs else None,
                "factory_code": wkid,
                "wkid": wkid,
                "wkt": ds.crs.to_wkt() if ds.crs and hasattr(ds.crs, "to_wkt") else None,
                "unit": ds.crs.linear_units if ds.crs else None,
            },
            "extent": extent,
            "fields": [],
            "raster_properties": {
                "width": ds.width,
                "height": ds.height,
                "band_count": ds.count,
                "pixel_type": ds.dtypes[0] if ds.dtypes else None,
                "cell_size": {"x": ds.res[0], "y": ds.res[1]} if ds.res else None,
                "no_data_value": nodata,
            },
            "value_range": value_range,
            "resolution": {"x": ds.res[0], "y": ds.res[1]} if ds.res else None,
        }
    return props


# ─── get_field_unique_values ──────────────────────────────────────────────────
def field_unique_values(
    feature_path: str, field_name: str, max_unique_values: int = 50
) -> dict[str, Any]:
    """取某字段唯一值及计数，超阈值只返回计数。"""
    pyogrio = _import_pyogrio()
    gpd = _import_geopandas()
    datasource, layer = _split_path(feature_path)

    if not os.path.exists(datasource):
        return {"success": False, "error": f"数据不存在: {feature_path}"}

    try:
        info = pyogrio.read_info(datasource, layer=layer)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取图层信息失败: {e}"}

    all_fields = _to_list(info.get("fields"))
    lower_map = {fn.lower(): fn for fn in all_fields}
    actual = lower_map.get(field_name.lower())
    if actual is None:
        return {
            "success": False,
            "error": f"字段 '{field_name}' 不存在。可用字段: {all_fields}",
        }

    ogr_types_list = _to_list(info.get("ogr_types"))
    idx = all_fields.index(actual)
    field_info = {
        "name": actual,
        "type": _map_ogr_type(ogr_types_list[idx]) if idx < len(ogr_types_list) else "String",
    }

    try:
        df = pyogrio.read_dataframe(
            datasource, layer=layer, columns=[actual], read_geometry=False
        )
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取字段失败: {e}"}

    series = df[actual]
    total = len(series)
    null_count = int(series.isna().sum())
    vc = series.dropna().astype(str).value_counts()
    unique_count = int(len(vc))

    result: dict[str, Any] = {
        "success": True,
        "feature_path": feature_path,
        "field_name": actual,
        "field_info": field_info,
        "total_records": total,
        "null_count": null_count,
        "unique_count": unique_count,
    }

    if unique_count <= max_unique_values:
        result["value_counts"] = [
            {"value": k, "count": int(v)} for k, v in vc.items()
        ]
        result["truncated"] = False
    else:
        result["value_counts"] = None
        result["truncated"] = True
        result["note"] = (
            f"唯一值数（{unique_count}）超过阈值（{max_unique_values}）。"
            "可调高 max_unique_values 获取完整分解。"
        )
    return result


# ─── embed_geojson（execute_gis_tool 嵌入 + auto-push-hook 推送共用）──────────
def embed_geojson(feature_path: str, max_records: int = 5000) -> dict[str, Any]:
    """把矢量要素类/.shp 转 WGS84 GeoJSON（非 WGS84 自动重投影）。

    返回 {success, geojson, count, bounds, spatial_reference, truncated}。
    与旧 arcpy 版 _EMBED_GEOJSON_SCRIPT 的返回形状一致。
    """
    pyogrio = _import_pyogrio()
    gpd = _import_geopandas()
    datasource, layer = _split_path(feature_path)

    if not os.path.exists(datasource):
        return {"success": False, "error": f"数据不存在: {feature_path}"}

    try:
        info = pyogrio.read_info(datasource, layer=layer)
        total = int(_to_list([info.get("features")])[0] or 0) if info.get("features") is not None else 0
        cols = _to_list(info.get("fields")) or None
        df = pyogrio.read_dataframe(
            datasource,
            layer=layer,
            max_features=max_records,
            columns=cols,
        )
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"读取要素失败: {e}"}

    if df.empty:
        return {
            "success": True,
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
            "bounds": [],
            "spatial_reference": {},
            "truncated": False,
        }

    source_crs = df.crs
    source_wkid = _wkid_from_crs(source_crs)
    if source_crs is not None and str(source_crs).upper() not in (WGS84_CRS, "EPSG:4326"):
        try:
            df = df.to_crs(WGS84_CRS)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": f"重投影到 WGS84 失败: {e}"}

    geojson = json.loads(df.to_json())
    count = len(geojson.get("features", []))

    # bounds（WGS84 下）
    bounds: list[float] = []
    try:
        b = df.total_bounds  # [minx, miny, maxx, maxy]
        bounds = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
    except Exception:  # noqa: BLE001
        pass

    return {
        "success": True,
        "geojson": geojson,
        "count": count,
        "bounds": bounds,
        "spatial_reference": {"wkid": source_wkid} if source_wkid else {},
        "truncated": total > max_records,
    }
