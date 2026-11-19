# -*- coding: utf-8 -*-
"""GDAL 直执行引擎（execute_gis_tool 的 `gdal` 引擎，无 arcpy / 无 qgis_process）。

历史上 QGIS 自带的 59 个 `gdal:*` 处理算法由 qgis_engine 经 `qgis_process run` 头less
子进程执行。本引擎在「内置(inner) → whitebox → gdal → qgis」降级链中替代 QGIS，
对 `gdal:*` 工具**直接**在 uv 进程内（rasterio / pyogrio / geopandas / numpy）执行，
仅在 rasterio 缺能力时（contour / grid / viewshed / colorrelief / pansharp / retile 等）
subprocess 调 QGIS 自带的 GDAL 命令行二进制（gdaldem / gdal_contour / gdal_viewshed /
gdal_grid / gdal_translate -of COG / gdalbuildvrt / gdaladdo / gdaltindex / nearblack /
gdal_proximity.* / gdal_pansharpen.* 等），不再经 qgis_process 这一中间环节。

设计约定（与 native_tools.py / gis_io.py 一致，避免已知陷阱）：
- 本模块在 main.py 顶部已 `import rasterio/pyogrio/geopandas/shapely`（GDAL C 扩展首次
  初始化在 mcp.run() 之前完成）后才被延迟 import，故模块级 import 这些库安全。
- 每个工具 `tool_gdal_xxx(parameters: dict) -> dict`，返回与 execute_gis_tool 同形：
  {success, output, error, messages, output_paths, engine='gdal'}。output_paths 显式返回。
- 多输入工具断言 CRS 一致；GDB 逻辑路径（`xxx.gdb/图层名`）经 gis_io._split_path 拆解；
  GDB 栅格输出目标降级为旁挂同名 `.tif`（GDAL OpenFileGDB 不支持写栅格）。
- GDAL CLI 二进制路径取自环境变量 `GDAL_BIN_DIR`（默认 QGIS 4.2 安装目录 bin/）；
  Python 脚本包装（gdal_calc / gdal_polygonize / gdal_proximity / gdal_retile /
  gdal_pansharpen）取自 `GDAL_SCRIPTS_DIR`（默认 QGIS apps/Python312/Scripts/）且
  需 `OSGEO4W_ROOT` 环境变量；CLI 不可用时返回清晰错误、不阻断 MCP 启动。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# 复用 gis_io 路径拆分与 native_tools 路径约定（与生成端同源不走样）
import sys as _sys
_SHARED_DIR = os.path.dirname(os.path.abspath(__file__))
if _SHARED_DIR not in _sys.path:
    _sys.path.insert(0, _SHARED_DIR)

from gis_io import _split_path  # noqa: E402

GDAL_RUN_TIMEOUT = 900  # 与 execute_gis_tool 900s 对齐


# ─── 路径判定 / 通用读写封装（与 native_tools 一致，独立持有避免循环 import）──────────
def _is_gdb_logical_path(path: str) -> bool:
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
    return str(path).replace("\\", "/").lower().endswith((".tif", ".tiff", ".vrt", ".img", ".asc", ".grd"))


def _ensure_parent(path: str) -> None:
    p = str(path).replace("\\", "/")
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _resolve_raster_out(out: str) -> tuple[str, str | None]:
    """GDB 逻辑栅格输出 → 旁挂 .tif（GDAL OpenFileGDB 不支持写 GDB 栅格）。"""
    if _is_gdb_logical_path(out):
        ds, layer = _split_path(str(out))
        side = os.path.join(ds, f"{layer}.tif")
        return side, "GDAL OpenFileGDB 不支持写 GDB 栅格，已降级为旁挂 .tif"
    return str(out), None


def _read_vector(path: str):
    """读矢量（.shp / GDB 要素类），返回 GeoDataFrame。"""
    import geopandas as gpd  # type: ignore

    ds, layer = _split_path(str(path))
    if not os.path.exists(ds):
        raise FileNotFoundError(f"数据不存在: {path}")
    return gpd.read_file(ds, layer=layer) if layer else gpd.read_file(ds)


def _write_vector(gdf, path: str, *, geometry_type: str | None = None) -> str:
    """写矢量到 .shp / .gpkg / .geojson / GDB 要素类（pyogrio OpenFileGDB 写）。"""
    import pyogrio  # type: ignore

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


# ─── 通用工具：参数取值（大小写不敏感，别名宽松）──────────────────────────────
def _get(parameters: dict, *keys: str, default: Any = ...) -> Any:
    plower = {k.lower().strip(): k for k in (parameters or {})}
    for k in keys:
        kk = k.lower().strip()
        if kk in plower:
            return parameters[plower[kk]]
    if default is not ...:
        return default
    raise KeyError(keys[0])


def _require(parameters: dict, *keys: str) -> Any:
    return _get(parameters, *keys)


def _missing(*keys: str) -> dict[str, Any]:
    return _fail(f"缺少必填参数（候选键名）：{list(keys)}")


def _ok(output_paths: list[str], message: str = "", **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "success": True,
        "output": message or "完成",
        "error": None,
        "messages": [message] if message else [],
        "output_paths": output_paths,
        "engine": "gdal",
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
        "engine": "gdal",
    }
    r.update(extra)
    return r


# ─── GDAL CLI 定位与调度 ─────────────────────────────────────────────────────────
_GDAL_BIN_DIR: str | None = None
_GDAL_BIN_PROBED = False


def _probe_gdal_bin_dir() -> str | None:
    """定位 GDAL CLI 二进制目录；进程级只探测一次。

    优先级：环境变量 GDAL_BIN_DIR > QGIS 4.2.0/4.2/4.0 安装目录 bin/。
    返回目录路径或 None（GDAL CLI 不可用）。
    """
    global _GDAL_BIN_DIR, _GDAL_BIN_PROBED
    if _GDAL_BIN_PROBED:
        return _GDAL_BIN_DIR
    _GDAL_BIN_PROBED = True

    translate_name = "gdal_translate.exe" if os.name == "nt" else "gdal_translate"
    env_dir = os.environ.get("GDAL_BIN_DIR", "").strip()
    if env_dir and os.path.isfile(os.path.join(env_dir, translate_name)):
        _GDAL_BIN_DIR = env_dir
        return _GDAL_BIN_DIR

    candidates = [
        r"C:\Program Files\QGIS 4.2.0\bin",
        r"C:\Program Files\QGIS 4.2\bin",
        r"C:\Program Files\QGIS 4.0\bin",
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, translate_name)):
            _GDAL_BIN_DIR = c
            return _GDAL_BIN_DIR

    # 任意 QGIS 安装（如 QGIS 3.x LTR：bin/ 带 gdal_translate.exe 与 apps/Python312/Scripts/）；
    # QGIS 4.x 部分发行版不再内置 GDAL CLI，故按存在性逐个探测。
    try:
        import glob as _glob

        for c in sorted(_glob.glob(r"C:\Program Files\QGIS *\bin"), reverse=True):
            if os.path.isfile(os.path.join(c, translate_name)):
                _GDAL_BIN_DIR = c
                return _GDAL_BIN_DIR
    except Exception:  # noqa: BLE001
        pass

    # POSIX（Linux/macOS，apt gdal-bin / 发行版 QGIS 包安装）：PATH 上探测 gdal_translate
    found = shutil.which(translate_name)
    if found:
        _GDAL_BIN_DIR = os.path.dirname(found)
        return _GDAL_BIN_DIR
    return None


def _gdal_bin(name: str) -> str:
    """bin 目录下的 CLI 可执行完整路径（POSIX 无 .exe 后缀）。"""
    suffix = ".exe" if os.name == "nt" else ""
    return os.path.join(_probe_gdal_bin_dir() or "", name + suffix)


def _exe(name: str) -> str:
    """按平台生成 CLI 可执行文件名（Windows 带 .exe，POSIX 无后缀）——供错误提示使用。"""
    return name + (".exe" if os.name == "nt" else "")


_GDAL_SCRIPTS_DIR: str | None = None
_GDAL_SCRIPTS_PROBED = False


def _probe_gdal_scripts_dir() -> str | None:
    """定位 GDAL Python 脚本包装目录（gdal_calc / gdal_polygonize / gdal_proximity /
    gdal_retile / gdal_pansharpen 等）。

    探测文件名按平台取：gdal_polygonize.bat（Windows QGIS Scripts 目录）/
    gdal_polygonize.py（Linux gdal-bin 等发行版包）。两种形式任一存在即接受。

    优先级：环境变量 GDAL_SCRIPTS_DIR > QGIS apps/Python312/Scripts/（Windows）>
    POSIX PATH 上的 gdal_polygonize.py（所在目录即 scripts dir）。
    """
    global _GDAL_SCRIPTS_DIR, _GDAL_SCRIPTS_PROBED
    if _GDAL_SCRIPTS_PROBED:
        return _GDAL_SCRIPTS_DIR
    _GDAL_SCRIPTS_PROBED = True

    # 标记文件按平台取主形态；探测时兼容两种形式（.bat 优先 Windows，.py 优先 POSIX）
    marker_bat = "gdal_polygonize.bat"
    marker_py = "gdal_polygonize.py"

    def _has_marker(d: str) -> bool:
        return os.path.isfile(os.path.join(d, marker_bat)) or os.path.isfile(os.path.join(d, marker_py))

    env_dir = os.environ.get("GDAL_SCRIPTS_DIR", "").strip()
    if env_dir and _has_marker(env_dir):
        _GDAL_SCRIPTS_DIR = env_dir
        return _GDAL_SCRIPTS_DIR

    # 从 GDAL bin 推断 QGIS 安装根目录（bin 上级）→ apps/Python312/Scripts
    bin_dir = _probe_gdal_bin_dir()
    if bin_dir and "bin" in bin_dir:
        root = os.path.dirname(bin_dir)
        cand = os.path.join(root, "apps", "Python312", "Scripts")
        if _has_marker(cand):
            _GDAL_SCRIPTS_DIR = cand
            return _GDAL_SCRIPTS_DIR

    # POSIX（Linux/macOS，apt gdal-bin / 发行版包安装）：PATH 上探测 gdal_polygonize.py，
    # 其所在目录即脚本目录（/usr/bin 下同时有 gdal_proximity.py / gdal_retile.py 等）
    found = shutil.which(marker_py) or shutil.which(marker_bat)
    if found:
        _GDAL_SCRIPTS_DIR = os.path.dirname(found)
        return _GDAL_SCRIPTS_DIR
    return None


def gdal_available() -> bool:
    """gdal 引擎是否可用。纯 Python 后端（rasterio/geopandas）总可用；CLI 工具按需探测。"""
    bin_dir = _probe_gdal_bin_dir()
    scripts_dir = _probe_gdal_scripts_dir()
    return bin_dir is not None or scripts_dir is not None


def _gdal_env() -> dict[str, str]:
    """为 GDAL CLI 子进程构造 UTF-8 友好的环境（GDAL_FILENAME_IS_UTF8 / OSOGeo4W_ROOT）。"""
    env = dict(os.environ)
    env.setdefault("GDAL_FILENAME_IS_UTF8", "YES")
    env.setdefault("OGR_ENABLE_PARTIAL_REPROJECTION", "YES")
    bin_dir = _probe_gdal_bin_dir()
    if bin_dir:
        # 把 GDAL bin 加到 PATH 最前，确保 DLL（gdal313.dll 等）可被找到
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        # OSGEO4W_ROOT 供 gdal_proximity.bat / gdal_pansharpen.bat 等 wrapper 解析路径
        if "OSGEO4W_ROOT" not in env:
            env["OSGEO4W_ROOT"] = os.path.dirname(bin_dir)
    # 强制 UTF-8 输出，避免中文路径在子进程 stdout 出现 GBK 乱码
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _run_cli(exe: str, args: list[str], timeout: int = GDAL_RUN_TIMEOUT,
             expect_json: bool = False) -> tuple[int, str, str]:
    """执行一个 GDAL/OGR CLI 命令，返回 (returncode, stdout, stderr)。

    对中文路径参数以 UTF-8 传递；stdout/stderr 以 UTF-8 解码。
    gdalinfo / ogrinfo 等可用 --json 开关返回结构化 JSON。
    """
    cmd = [exe] + args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_gdal_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"GDAL CLI 超时（{timeout}s）：{exe} {args[:6]}…") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"GDAL 可执行不存在：{exe}（请检查 GDAL_BIN_DIR）。") from e
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _run_script_bat(name: str, args: list[str], timeout: int = GDAL_RUN_TIMEOUT) -> tuple[int, str, str]:
    """跑 QGIS apps/Python312/Scripts/gdal_*.bat 包装脚本（gdal_proximity / gdal_retile / gdal_pansharpen 等）。

    这些 .bat 内部 `call %OSGEO4W_ROOT%/bin/o4w_env.bat` 后 python -u 跑 .py 脚本；
    需 OSGEO4W_ROOT 环境变量指向 QGIS 安装根目录（_gdal_env 已注入）。
    """
    if os.name != "nt":
        # POSIX：gdal-bin 包以 .py 形式安装同一批脚本（gdal_proximity.py / gdal_retile.py /
        # gdal_pansharpen.py / rgb2pct.py / pct2rgb.py / gdal2tiles.py / gdal2xyz.py /
        # ogrmerge.py），在 GDAL_SCRIPTS_DIR 或 PATH 上定位后用当前解释器直跑。
        env_dir = os.environ.get("GDAL_SCRIPTS_DIR", "").strip()
        script = None
        for cand in ([os.path.join(env_dir, f"{name}.py")] if env_dir else []) + [
            shutil.which(f"{name}.py"),
            shutil.which(name),
        ]:
            if cand and os.path.isfile(cand):
                script = cand
                break
        if not script:
            raise RuntimeError(
                f"GDAL 脚本包装未找到：{name}.py（请安装 gdal-bin 或设置 GDAL_SCRIPTS_DIR）。"
            )
        try:
            # 发行版脚本（gdal-bin）自带 shebang 指向系统 python3，且依赖系统包里的
            # osgeo_utils（python3-gdal）。用当前解释器（venv/其它 ABI）跑会 ImportError，
            # 因此脚本可执行时直接按 shebang 执行，不可执行才退回当前解释器。
            if os.access(script, os.X_OK):
                cmd = [script]
            else:
                cmd = [_sys.executable, script]
            proc = subprocess.run(
                cmd + args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=_gdal_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"GDAL 脚本超时（{timeout}s）：{name}") from e
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        raise RuntimeError(
            "GDAL 脚本包装目录未找到（gdal_proximity/gdal_retile 等需 QGIS 安装的 "
            "apps/Python312/Scripts/）。请设置 GDAL_SCRIPTS_DIR 环境变量。"
        )
    bat = os.path.join(scripts, f"{name}.bat")
    if not os.path.isfile(bat):
        raise RuntimeError(f"找不到 GDAL 脚本包装：{bat}")
    try:
        proc = subprocess.run(
            [bat] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_gdal_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"GDAL 脚本超时（{timeout}s）：{name}") from e
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ─── 1. gdal:translate（栅格式转换/区域裁剪/波段子集/类型转换）────────────────────
def tool_translate(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore
    from rasterio.windows import Window, from_bounds  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT", "i")
        out = _require(parameters, "output", "OUTPUT", "o")
    except KeyError as e:
        return _missing(str(e))
    band = _get(parameters, "band", "BAND", default=None)
    outsize = _get(parameters, "outsize", "OUTSIZE", default=None)
    projwin = _get(parameters, "projwin", "PROJWIN", default=None)
    a_srs = _get(parameters, "a_srs", "A_SRS", default=None)
    try:
        actual_out, note = _resolve_raster_out(out)
        with rasterio.open(inp) as src:
            window = None
            if projwin:
                # projwin: [xmin,ymin,xmax,ymax] 或 dict xmin/ymin/xmax/ymax
                p = projwin
                if isinstance(p, str):
                    p = [float(x) for x in p.replace("[", " ").replace("]", " ").replace(",", " ").split()]
                if isinstance(p, dict):
                    xmin, ymin = float(p["xmin"]), float(p["ymin"])
                    xmax, ymax = float(p["xmax"]), float(p["ymax"])
                else:
                    xmin, ymin, xmax, ymax = p[0], p[1], p[2], p[3]
                window = from_bounds(xmin, ymin, xmax, ymax, src.transform)
            bands = src.count
            if band:
                if isinstance(band, str):
                    band = [int(x) for x in band.replace(",", " ").split()]
                elif isinstance(band, int):
                    band = [band]
                bands = min(len(band), src.count)
            kwargs = src.profile.copy()
            if a_srs:
                kwargs["crs"] = a_srs
            if outsize:
                if isinstance(outsize, str):
                    sz = [int(x) for x in outsize.replace(",", " ").split()]
                else:
                    sz = list(outsize)
                if len(sz) >= 2 and sz[0] > 0 and sz[1] > 0:
                    kwargs["width"], kwargs["height"] = sz[0], sz[1]
            kwargs.update(driver="GTiff")
            _ensure_parent(actual_out)
            src_bands = band if band else list(range(1, bands + 1))
            with rasterio.open(actual_out, "w", **kwargs) as dst:
                for di, si in enumerate(src_bands, start=1):
                    if window is not None:
                        data = src.read(si, window=window, out_shape=(
                            kwargs["height"], kwargs["width"]) if outsize else None)
                    else:
                        out_shape = (kwargs["height"], kwargs["width"]) if outsize else None
                        data = src.read(si, out_shape=out_shape)
                    dst.write(data, di)
        msg = f"栅格转换完成 → {actual_out}"
        if note:
            msg += f"（{note}）"
        return _ok([actual_out], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:translate 失败：{e}")


# ─── 2. gdal:rasterize（矢量 → 栅格）───────────────────────────────────────────
def tool_rasterize(parameters: dict) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.features import rasterize  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    attribute = _get(parameters, "field", "attribute", "ATTRIBUTE", default=None)
    extent = _get(parameters, "extent", "EXTENT", default=None)
    size = _get(parameters, "size", "SIZE", "resolution_x", default=None)
    burn = _get(parameters, "burn", "BURN", default=1)
    all_touched = bool(_get(parameters, "all_touched", "ALL_TOUCHED", default=False))
    init = _get(parameters, "init", "INIT", default=0)
    try:
        gdf = _read_vector(inp)
        if extent:
            e = extent
            if isinstance(e, str):
                e = [float(x) for x in e.replace("[", " ").replace("]", " ").replace(",", " ").split()]
            xmin, ymin, xmax, ymax = e[0], e[1], e[2], e[3]
        else:
            xmin, ymin, xmax, ymax = gdf.total_bounds
        # 解析分辨率或尺寸
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            width, height = int(size[0]), int(size[1])
        elif isinstance(size, str) and "x" in size.lower():
            width, height = [int(x) for x in size.lower().split("x")]
        else:
            # 默认 1px/100m，按范围与长度比构造
            res = float(size) if size else 100.0
            width = max(1, int((xmax - xmin) / res))
            height = max(1, int((ymax - ymin) / res))
        from rasterio.transform import from_origin  # type: ignore
        transform = from_origin(xmin, ymax, (xmax - xmin) / width, (ymax - ymin) / height)
        if attribute:
            am = {c.lower(): c for c in gdf.columns}
            col = am.get(str(attribute).lower())
            if col is None:
                return _fail(f"字段 '{attribute}' 不存在；可用字段：{list(gdf.columns)}")
            shapes = ((geom, val) for geom, val in zip(gdf.geometry, gdf[col]) if geom is not None)
        else:
            shapes = ((geom, burn) for geom in gdf.geometry if geom is not None)
        arr = rasterize(
            shapes=shapes, out_shape=(height, width),
            transform=transform, fill=init, all_touched=all_touched,
            dtype="float64" if attribute else "int32",
        )
        actual_out, note = _resolve_raster_out(out)
        _ensure_parent(actual_out)
        with rasterio.open(
            actual_out, "w", driver="GTiff", height=height, width=width,
            count=1, dtype=arr.dtype, crs=gdf.crs, transform=transform, nodata=init,
        ) as dst:
            dst.write(arr, 1)
        msg = f"栅格化完成：{len(gdf)} 要素 → {actual_out}（{width}x{height}）"
        if note:
            msg += f"（{note}）"
        return _ok([actual_out], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:rasterize 失败：{e}")


# ─── 3. gdal:rasterize_over（按属性覆盖写到已有栅格）────────────────────────────
def tool_rasterize_over(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore
    from rasterio.features import rasterize  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        field = _require(parameters, "field", "FIELD", "attribute")
    except KeyError as e:
        return _missing(str(e))
    try:
        if not os.path.exists(out):
            return _fail(f"输出栅格不存在，无法覆盖：{out}（rasterize_over 需要已有栅格作底）")
        gdf = _read_vector(inp)
        am = {c.lower(): c for c in gdf.columns}
        col = am.get(str(field).lower())
        if col is None:
            return _fail(f"字段 '{field}' 不存在；可用字段：{list(gdf.columns)}")
        with rasterio.open(out, "r+") as dst:
            shapes = ((geom, val) for geom, val in zip(gdf.geometry, gdf[col]) if geom is not None)
            arr = rasterize(
                shapes=shapes, out_shape=(dst.height, dst.width),
                transform=dst.transform, fill=dst.nodata or 0, dtype=dst.dtypes[0],
            )
            dst.write(arr, 1)
        return _ok([out], f"按字段 '{field}' 覆盖栅格完成 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:rasterize_over 失败：{e}")


def tool_rasterize_over_fixed_value(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore
    from rasterio.features import rasterize  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        burn = float(_require(parameters, "burn", "BURN", "fixed_value"))
    except (KeyError, ValueError) as e:
        return _missing(str(e))
    try:
        if not os.path.exists(out):
            return _fail(f"输出栅格不存在，无法覆盖：{out}")
        gdf = _read_vector(inp)
        with rasterio.open(out, "r+") as dst:
            shapes = ((geom, burn) for geom in gdf.geometry if geom is not None)
            arr = rasterize(
                shapes=shapes, out_shape=(dst.height, dst.width),
                transform=dst.transform, fill=dst.nodata or 0, dtype=dst.dtypes[0],
            )
            dst.write(arr, 1)
        return _ok([out], f"以固定值 {burn} 覆盖栅格完成 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:rasterize_over_fixed_value 失败：{e}")


# ─── 4. gdal:polygonize（栅格 → 矢量面，按像元值分组）─────────────────────────
def tool_polygonize(parameters: dict) -> dict[str, Any]:
    import geopandas as gpd  # type: ignore
    import rasterio  # type: ignore
    from rasterio.features import shapes  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    band = int(_get(parameters, "band", "BAND", default=1))
    field = _get(parameters, "field", "FIELD", "DN", default="DN")
    connectivity = int(_get(parameters, "connectivity", default=4))
    try:
        from shapely.geometry import shape  # type: ignore

        with rasterio.open(inp) as src:
            arr = src.read(band)
            mask = src.read_masks(band) > 0 if src.nodata is None else (arr != src.nodata)
            geoms, vals = [], []
            for geom, val in shapes(arr, mask=mask, transform=src.transform, connectivity=connectivity):
                geoms.append(shape(geom))  # GeoJSON dict → shapely 几何
                vals.append(int(val) if isinstance(val, (int, float)) and float(val).is_integer() else val)
            out_gdf = gpd.GeoDataFrame({"geometry": geoms, str(field): vals}, crs=src.crs)
            _write_vector(out_gdf, out)
            return _ok([out], f"栅格转面完成：{len(out_gdf)} 个多边形 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:polygonize 失败：{e}")


# ─── 5. gdal:sieve（移除小面积像元区，按最小尺寸过滤）───────────────────────────
def tool_sieve(parameters: dict) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.features import sieve  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        size = int(_require(parameters, "threshold", "size", "SIZE", "THRESHOLD"))
    except KeyError as e:
        return _missing(str(e))
    except ValueError as e:
        return _fail(f"threshold 须为整数：{e}")
    band = int(_get(parameters, "band", default=1))
    connectivity = int(_get(parameters, "connectivity", default=4))
    try:
        actual_out, note = _resolve_raster_out(out)
        with rasterio.open(inp) as src:
            arr = src.read(band)
            # rasterio.features.sieve 仅接受整数 dtype；float 栅格先就近取整（sieve 语义即按整数值连通）。
            if np.issubdtype(arr.dtype, np.floating):
                arr_s = arr.astype("int32")
            else:
                arr_s = arr
            out_arr = sieve(arr_s, size=size, connectivity=connectivity)
            kwargs = src.profile.copy()
            kwargs.update(dtype=out_arr.dtype, driver="GTiff")
        with rasterio.open(actual_out, "w", **kwargs) as dst:
            dst.write(out_arr, band)
        msg = f"sieve 完成（阈值 {size} 像元）→ {actual_out}"
        if note:
            msg += f"（{note}）"
        return _ok([actual_out], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:sieve 失败：{e}")


# ─── 6. gdal:fillnodata（填补 NoData 区域）──────────────────────────────────────
def tool_fillnodata(parameters: dict) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.fill import fillnodata  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    band = int(_get(parameters, "band", default=1))
    max_dist = float(_get(parameters, "max_distance", "mask_distance", "MAX_DISTANCE", default=100.0))
    smooth = int(_get(parameters, "smoothing", "SMOOTHING_ITERATIONS", default=0))
    try:
        actual_out, note = _resolve_raster_out(out)
        with rasterio.open(inp) as src:
            arr = src.read(band)
            # fillnodata 需要一个 mask：1=有效、0=待填充。nodata 已知则取 nodata 的反，
            # 否则用有效数据位掩码（NaN/0 也视为待填充）。
            if src.nodata is not None:
                mask = (arr != src.nodata).astype("uint8")
            else:
                valid = np.ones(arr.shape, dtype="uint8")
                try:
                    valid = (~np.isnan(arr)).astype("uint8")
                except TypeError:
                    pass
                mask = valid
            filled = fillnodata(arr, mask=mask, max_search_distance=max_dist, smoothing_iterations=smooth)
            kwargs = src.profile.copy()
            kwargs.update(driver="GTiff")
        with rasterio.open(actual_out, "w", **kwargs) as dst:
            dst.write(filled, band)
        msg = f"填充 NoData 完成 → {actual_out}"
        if note:
            msg += f"（{note}）"
        return _ok([actual_out], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:fillnodata 失败：{e}")


# ─── 7. gdal:cliprasterbyextent / cliprasterbymasklayer（rasterio.mask）─────────
def tool_cliprasterbyextent(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore
    from rasterio.windows import from_bounds  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        extent = _require(parameters, "extent", "EXTENT", "PROJWIN")
    except KeyError as e:
        return _missing(str(e))
    band = int(_get(parameters, "band", default=1))
    try:
        e = extent
        if isinstance(e, str):
            e = [float(x) for x in e.replace("[", " ").replace("]", " ").replace(",", " ").split()]
        if isinstance(e, dict):
            xmin, ymin, xmax, ymax = float(e["xmin"]), float(e["ymin"]), float(e["xmax"]), float(e["ymax"])
        else:
            xmin, ymin, xmax, ymax = e[0], e[1], e[2], e[3]
        actual_out, note = _resolve_raster_out(out)
        with rasterio.open(inp) as src:
            window = from_bounds(xmin, ymin, xmax, ymax, src.transform)
            kwargs = src.profile.copy()
            kwargs.update(
                driver="GTiff",
                width=window.width, height=window.height,
                transform=rasterio.windows.transform(window, src.transform),
            )
            _ensure_parent(actual_out)
            with rasterio.open(actual_out, "w", **kwargs) as dst:
                dst.write(src.read(window=window))
        msg = f"按范围裁剪完成 → {actual_out}"
        if note:
            msg += f"（{note}）"
        return _ok([actual_out], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:cliprasterbyextent 失败：{e}")


def tool_cliprasterbymasklayer(parameters: dict) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore
    from rasterio.mask import mask  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        mask_layer = _require(parameters, "mask", "MASK_LAYER", "mask_layer")
    except KeyError as e:
        return _missing(str(e))
    crop = bool(_get(parameters, "crop", "CROP_TO_CUTLINE", default=True))
    try:
        mask_gdf = _read_vector(mask_layer)
        try:
            with rasterio.open(inp) as src:
                # CRS 一致性：若不一致，把 mask 重投影到 src.crs
                if mask_gdf.crs is not None and src.crs is not None and not mask_gdf.crs.equals(src.crs):
                    mask_gdf = mask_gdf.to_crs(src.crs)
                out_img, out_transform = mask(src, list(mask_gdf.geometry), crop=crop, filled=True)
                kwargs = src.profile.copy()
                kwargs.update(
                    driver="GTiff", width=out_img.shape[2], height=out_img.shape[1],
                    transform=out_transform,
                )
        except Exception as e:  # noqa: BLE001
            return _fail(f"掩膜裁剪失败：{e}")
        actual = _resolve_raster_out(out)[0]
        _ensure_parent(actual)
        with rasterio.open(actual, "w", **kwargs) as dst:
            dst.write(out_img)
        return _ok([actual], f"按掩膜层裁剪完成 → {actual}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:cliprasterbymasklayer 失败：{e}")


# ─── 8. gdal:merge（栅格拼接）─────────────────────────────────────────────────────
def tool_merge(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore
    from rasterio.merge import merge  # type: ignore

    try:
        inputs = _require(parameters, "input", "INPUT", "inputs", "INPUTS")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    nodata = _get(parameters, "nodata", "NODATA", default=None)
    resampling_name = str(_get(parameters, "resampling", "RESAMPLING", default="nearest")).lower()
    try:
        if isinstance(inputs, str):
            inputs = [inputs]
        from rasterio.enums import Resampling  # type: ignore
        resam_map = {r.lower(): r for r in [m.name for m in Resampling]}
        resam = Resampling.__members__.get(resampling_name.upper())
        if resam is None:
            resam = Resampling.nearest
        srcs = [rasterio.open(p) for p in inputs]
        try:
            arr, transform = merge(srcs, nodata=nodata, resampling=resam)
        finally:
            for s in srcs:
                s.close()
        with rasterio.open(inputs[0]) as ref:
            crs = ref.crs
        actual = _resolve_raster_out(out)[0]
        _ensure_parent(actual)
        with rasterio.open(
            actual, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2],
            count=arr.shape[0], dtype=arr.dtype, crs=crs, transform=transform, nodata=nodata,
        ) as dst:
            dst.write(arr)
        return _ok([actual], f"拼接完成：{len(inputs)} 个栅格 → {actual}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:merge 失败：{e}")


# ─── 9. gdal:warpreproject / assignprojection / extractprojection（rasterio.warp）─
def tool_warpreproject(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore
    from rasterio.warp import calculate_default_transform, reproject  # type: ignore
    from rasterio.enums import Resampling  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        target = _require(parameters, "target_crs", "crs", "CRS", "TARGET_CRS", "a_srs")
    except KeyError as e:
        return _missing(str(e))
    resam_name = str(_get(parameters, "resampling", "RESAMPLING", default="nearest")).lower()
    try:
        if isinstance(target, int):
            target = f"EPSG:{target}"
        elif isinstance(target, str) and target.strip().isdigit():
            target = f"EPSG:{target.strip()}"
        resam = Resampling.__members__.get(resam_name.upper(), Resampling.nearest)
        actual, note = _resolve_raster_out(out)
        with rasterio.open(inp) as src:
            if src.crs is None:
                return _fail(f"输入栅格无 CRS，无法投影：{inp}")
            transform, width, height = calculate_default_transform(
                src.crs, target, src.width, src.height, *src.bounds
            )
            kwargs = src.profile.copy()
            kwargs.update(crs=target, transform=transform, width=width, height=height, driver="GTiff")
            _ensure_parent(actual)
            with rasterio.open(actual, "w", **kwargs) as dst:
                for i in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, i), destination=rasterio.band(dst, i),
                        src_transform=src.transform, src_crs=src.crs,
                        dst_transform=transform, dst_crs=target, resampling=resam,
                    )
        msg = f"栅格重投影完成：{src.crs} → {target} → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:warpreproject 失败：{e}")


def tool_assignprojection(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _get(parameters, "output", "OUTPUT", default=None)
        target = _require(parameters, "crs", "target_crs", "CRS", "A_SRS")
    except KeyError as e:
        return _missing(str(e))
    try:
        if isinstance(target, int):
            target = f"EPSG:{target}"
        elif isinstance(target, str) and target.strip().isdigit():
            target = f"EPSG:{target.strip()}"
        if out is None:
            # 原地赋投影 → 直接 r+ 修改 metadata
            with rasterio.open(inp, "r+") as dst:
                dst.crs = target
            return _ok([inp], f"原地赋投影完成 → {target}")
        actual, note = _resolve_raster_out(out)
        with rasterio.open(inp) as src:
            kwargs = src.profile.copy()
            kwargs.update(crs=target, driver="GTiff")
            _ensure_parent(actual)
            with rasterio.open(actual, "w", **kwargs) as dst:
                for i in range(1, src.count + 1):
                    dst.write(src.read(i), i)
        msg = f"赋投影完成 → {actual}（{target}；未像元重采样，仅写 CRS）"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:assignprojection 失败：{e}")


def tool_extractprojection(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
    except KeyError as e:
        return _missing(str(e))
    prj_out = _get(parameters, "prj", "PRJ", default=None)
    try:
        with rasterio.open(inp) as src:
            crs = src.crs
            wkt = crs.to_wkt() if crs else None
            info = {"crs": crs.to_string() if crs else None, "wkt": wkt}
        if prj_out:
            _ensure_parent(prj_out)
            with open(prj_out, "w", encoding="utf-8") as f:
                f.write(wkt or "")
            return _ok([prj_out], f"投影已提取到 .prj → {prj_out}", crs=info["crs"])
        return _ok([inp], f"投影已读取：{info['crs']}", crs=info["crs"], wkt=wkt)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:extractprojection 失败：{e}")


# ─── 10. gdal:rearrange_bands（波段子集/重排，纯 Python）─────────────────────
def tool_rearrange_bands(parameters: dict) -> dict[str, Any]:
    import rasterio  # type: ignore

    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        order = _require(parameters, "bands", "BANDS", "order")
    except KeyError as e:
        return _missing(str(e))
    try:
        if isinstance(order, str):
            order = [int(x) for x in order.replace(",", " ").split()]
        with rasterio.open(inp) as src:
            kwargs = src.profile.copy()
            kwargs.update(count=len(order), driver="GTiff")
            actual, note = _resolve_raster_out(out)
            _ensure_parent(actual)
            with rasterio.open(actual, "w", **kwargs) as dst:
                for di, si in enumerate(order, 1):
                    dst.write(src.read(si), di)
        msg = f"波段重排完成：{order} → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:rearrange_bands 失败：{e}")


# ─── 11. gdal:rastercalculator（波段算术，复用 rasterio + numpy 表达式）────────
def tool_rastercalculator(parameters: dict) -> dict[str, Any]:
    import numpy as np  # type: ignore
    import rasterio  # type: ignore

    try:
        inputs = _require(parameters, "input", "input_a", "INPUT_A", "inputs")
        out = _require(parameters, "output", "OUTPUT")
        formula = _require(parameters, "formula", "expression", "calc", "EXPRESSION")
    except KeyError as e:
        return _missing(str(e))
    try:
        # 统一为 list[str]：单输入用 [a]
        if isinstance(inputs, str):
            inputs = [inputs]
        # 用 a/b/c/... 顺序绑定各输入的第 1 个波段；支持表达式 b1/b2 等可由用户自由
        bands_meta = []
        with rasterio.open(inputs[0]) as ref:
            kwargs = ref.profile.copy()
            kwargs.update(driver="GTiff", count=1, dtype="float64")
            transform = ref.transform
            crs = ref.crs
        var_map = {}
        names = "abcdefghijklmnop"[: len(inputs)]
        for nm, p in zip(names, inputs):
            with rasterio.open(p) as src:
                arr = src.read(1).astype("float64")
                # 把 nodata 替换为 NaN，参与表达式为浮点 NaN
                if src.nodata is not None:
                    arr = np.where(arr == src.nodata, np.nan, arr)
                var_map[nm] = arr
        # 也提供 b1/b2 形式：第一个输入的第 1 波段为 b1，依次
        with rasterio.open(inputs[0]) as s0:
            var_map["b1"] = s0.read(1).astype("float64")
        result = eval(str(formula), {"np": np, "numpy": np}, var_map)  # noqa: S307 —— 受控执行，提示词层用户侧可控
        result = np.asarray(result, dtype="float64")
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        kwargs.update(width=result.shape[1], height=result.shape[0], transform=transform, crs=crs)
        with rasterio.open(actual, "w", **kwargs) as dst:
            dst.write(result, 1)
        msg = f"栅格计算完成：{formula} → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:rastercalculator 失败：{e}")


# ─── 12. 矢量类（geopandas）──────────────────────────────────────────────────────
def tool_buffervectors(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT", "geometry")
        out = _require(parameters, "output", "OUTPUT")
        dist = float(_require(parameters, "distance", "radius", "DISTANCE"))
    except KeyError as e:
        return _missing(str(e))
    except ValueError as e:
        return _fail(f"distance 须为数值：{e}")
    dissolve = bool(_get(parameters, "dissolve", "DISSOLVE", default=False))
    try:
        gdf = _read_vector(inp)
        if gdf.crs is not None and getattr(gdf.crs, "is_geographic", False):
            return _fail("输入为地理坐标系（度），缓冲距离单位为度无意义。请先投影到投影坐标系。")
        if dissolve:
            merged = gdf.dissolve()
            merged.geometry = merged.geometry.buffer(dist, resolution=16)
            out_gdf = merged.reset_index(drop=True)
        else:
            out_gdf = gdf.copy()
            out_gdf.geometry = gdf.geometry.buffer(dist, resolution=16)
        _write_vector(out_gdf, out)
        return _ok([out], f"矢量缓冲完成（距离 {dist}）：{len(out_gdf)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:buffervectors 失败：{e}")


def tool_clipvectorbyextent(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        extent = _require(parameters, "extent", "EXTENT")
    except KeyError as e:
        return _missing(str(e))
    try:
        gdf = _read_vector(inp)
        e = extent
        if isinstance(e, str):
            e = [float(x) for x in e.replace("[", " ").replace("]", " ").replace(",", " ").split()]
        if isinstance(e, dict):
            xmin, ymin, xmax, ymax = float(e["xmin"]), float(e["ymin"]), float(e["xmax"]), float(e["ymax"])
        else:
            xmin, ymin, xmax, ymax = e[0], e[1], e[2], e[3]
        from shapely.geometry import box  # type: ignore
        clip_bbox = gpd_box(xmin, ymin, xmax, ymax, crs=gdf.crs)
        clipped = gdf.clip(clip_bbox)
        _write_vector(clipped, out)
        return _ok([out], f"按范围裁剪矢量完成：{len(clipped)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:clipvectorbyextent 失败：{e}")


def gpd_box(xmin, ymin, xmax, ymax, crs=None):
    from shapely.geometry import box  # type: ignore
    import geopandas as gpd  # type: ignore
    return gpd.GeoDataFrame(geometry=[box(xmin, ymin, xmax, ymax)], crs=crs)


def tool_clipvectorbypolygon(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        mask_p = _require(parameters, "mask", "MASK", "overlay")
    except KeyError as e:
        return _missing(str(e))
    try:
        a = _read_vector(inp)
        b = _read_vector(mask_p)
        try:
            if a.crs is not None and b.crs is not None and not a.crs.equals(b.crs):
                b = b.to_crs(a.crs)
        except Exception:  # noqa: BLE001
            pass
        clipped = a.clip(b)
        _write_vector(clipped, out)
        return _ok([out], f"按掩膜裁剪矢量完成：{len(clipped)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:clipvectorbypolygon 失败：{e}")


def tool_dissolve(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    field = _get(parameters, "field", "FIELD", default=None)
    try:
        gdf = _read_vector(inp)
        if field:
            am = {c.lower(): c for c in gdf.columns}
            col = am.get(str(field).lower())
            if col is None:
                return _fail(f"字段 '{field}' 不存在；可用字段：{list(gdf.columns)}")
            out_gdf = gdf.dissolve(by=col).reset_index()
        else:
            out_gdf = gdf.dissolve().reset_index()
        _write_vector(out_gdf, out)
        return _ok([out], f"dissolve 完成（按 {field or '全部'}）：{len(out_gdf)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:dissolve 失败：{e}")


def tool_convertformat(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        gdf = _read_vector(inp)
        _write_vector(gdf, out)
        return _ok([out], f"矢量格式转换完成：{len(gdf)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:convertformat 失败：{e}")


def tool_offsetcurve(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        dist = float(_require(parameters, "distance", "offset", "OFFSET"))
    except KeyError as e:
        return _missing(str(e))
    except ValueError as e:
        return _fail(f"distance 须为数值：{e}")
    side = str(_get(parameters, "side", "SIDE", default="right")).lower()
    try:
        gdf = _read_vector(inp)
        out_gdf = gdf.copy()
        # shapely 2.x offset_curve 签名 (distance, quad_segs=8, join_style=1, mitre_limit=5.0, side='right')
        # 用关键字 side= 传方向；join_style=2 (round)。parallel_offset 旧签名用位置 side。
        def _offset(g):
            if g is None or g.is_empty:
                return None
            try:
                return g.offset_curve(dist, join_style=2, side=side)
            except TypeError:
                return g.parallel_offset(dist, side, join_style=2)
        out_gdf.geometry = out_gdf.geometry.apply(_offset)
        _write_vector(out_gdf, out)
        return _ok([out], f"偏移曲线完成（{side} {dist}）：{len(out_gdf)} 要素 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:offsetcurve 失败：{e}")


def tool_onesidebuffer(parameters: dict) -> dict[str, Any]:
    """单侧缓冲：用 shapely buffer side ∈ both|left|right（shapely 2.x via offset_curve）。"""
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        dist = float(_require(parameters, "distance", "DISTANCE"))
    except KeyError as e:
        return _missing(str(e))
    except ValueError as e:
        return _fail(f"distance 须为数值：{e}")
    side = str(_get(parameters, "side", "SIDE", default="both")).lower()
    try:
        gdf = _read_vector(inp)
        out_gdf = gdf.copy()
        if side == "both":
            out_gdf.geometry = gdf.geometry.buffer(dist)
        else:
            shapely_side = "left" if side == "left" else "right"
            out_gdf.geometry = gdf.geometry.apply(
                lambda g: g.buffer(dist, single_sided=True, join_style=2) if g is not None else None
            )
            # shapely 的 single_sided 需配合方向：用 offset_curve + buffer 兜底更稳，这里仅在 LineString 上有效
        _write_vector(out_gdf, out)
        return _ok([out], f"单侧缓冲完成（{side} {dist}）→ {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:onesidebuffer 失败：{e}")


def tool_pointsalonglines(parameters: dict) -> dict[str, Any]:
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        dist = float(_require(parameters, "distance", "DISTANCE", "offset"))
    except KeyError as e:
        return _missing(str(e))
    except ValueError as e:
        return _fail(f"distance 须为数值：{e}")
    try:
        import geopandas as gpd  # type: ignore
        from shapely.geometry import LineString, MultiLineString  # type: ignore

        gdf = _read_vector(inp)
        pts = []
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue
            # 仅对线要素插点；面/点跳过（gdal:pointsalonglines 语义即沿线）
            if not isinstance(geom, (LineString, MultiLineString)):
                continue
            length = geom.length
            n = max(1, int(length / dist)) if dist > 0 else 1
            for i in range(n + 1):
                d = (i * length) / n if n else 0
                pts.append(geom.interpolate(d))
        if not pts:
            return _fail("输入中无线要素（pointsalonglines 仅处理 LineString/MultiLineString）。")
        out_gdf = gpd.GeoDataFrame(geometry=pts, crs=gdf.crs)
        _write_vector(out_gdf, out)
        return _ok([out], f"沿线生点完成（间隔 {dist}）：{len(pts)} 点 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:pointsalonglines 失败：{e}")


# ─── 13. GDAL CLI 派发工具（gdaldem / gdal_contour / gdal_viewshed / gdal_grid 等）──
def _gdal_dem_impl(parameters: dict, mode: str) -> dict[str, Any]:
    """gdaldem aspect/slope/hillshade/roughness/tpi/tri/color-relief 公共实现。"""
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdaldem.exe）。请设置 GDAL_BIN_DIR 或安装 QGIS。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    band = int(_get(parameters, "band", "BAND", default=1))
    try:
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        exe = _gdal_bin("gdaldem")
        args = [mode]
        if mode == "color-relief":
            color_clut = _require(parameters, "color_table", "clut", "COLOR_TABLE")
            args += [inp, color_clut, actual, "-of", "GTiff"]
        else:
            args += [inp, actual, "-of", "GTiff", "-b", str(band)]
            if mode in ("hillshade", "slope", "aspect"):
                scale = _get(parameters, "scale", "S", default=None)
                if scale is not None:
                    args += ["-s", str(scale)]
                # -z（垂直夸张）为 hillshade 专属；slope/aspect 传 -z 会被 gdaldem 拒绝。
                if mode == "hillshade":
                    z_factor = _get(parameters, "z_factor", "Z", default=None)
                    if z_factor is not None:
                        args += ["-z", str(z_factor)]
            if bool(_get(parameters, "compute_edges", "COMPUTE_EDGES", default=False)):
                args.append("-compute_edges")
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdaldem {mode} 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"gdaldem {mode} 完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except KeyError as e:
        return _missing(str(e))
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdaldem {mode} 失败：{e}")


def tool_aspect(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "aspect")


def tool_slope(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "slope")


def tool_hillshade(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "hillshade")


def tool_roughness(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "roughness")


def tool_tpitopographicpositionindex(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "TPI")


def tool_triterrainruggednessindex(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "TRI")


def tool_colorrelief(parameters: dict) -> dict[str, Any]:
    return _gdal_dem_impl(parameters, "color-relief")


# gdal:contour / contour_polygon：gdal_contour.exe CLI
def tool_contour(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdal_contour.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        interval = float(_get(parameters, "interval", "INTERVAL", "CONTOUR_INTERVAL", default=100))
    except (ValueError, TypeError) as e:
        return _fail(f"interval 须为数值：{e}")
    band = int(_get(parameters, "band", "BAND", default=1))
    field = _get(parameters, "field", "ATTRIBUTE_FIELD", "FIELD", default="ELEV")
    try:
        _ensure_parent(out)
        exe = _gdal_bin("gdal_contour")
        args = ["-a", str(field), "-i", str(interval), "-b", str(band), "-of", "GPKG", inp, out]
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:contour 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out], f"等值线生成完成（间隔 {interval}）→ {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:contour 失败：{e}")


def tool_contour_polygon(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdal_contour.exe，contour_polygon 需 GDAL 3.9+ 的 -amin/-amax）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
        interval = float(_require(parameters, "interval", "INTERVAL", default=100))
    except KeyError as e:
        return _missing(str(e))
    except ValueError as e:
        return _fail(f"interval 须为数值：{e}")
    band = int(_get(parameters, "band", default=1))
    try:
        _ensure_parent(out)
        exe = _gdal_bin("gdal_contour")
        args = ["-p", "-amin", "ELEV_MIN", "-amax", "ELEV_MAX", "-i", str(interval),
                "-b", str(band), "-of", "GPKG", inp, out]
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:contour_polygon 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out], f"等值面生成完成（间隔 {interval}）→ {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:contour_polygon 失败：{e}")


# gdal:viewshed：gdal_viewshed.exe CLI
def tool_viewshed(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdal_viewshed.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT", "dem")
        out = _require(parameters, "output", "OUTPUT")
        coord = _require(parameters, "observer", "observer_pos", "OBSERVER_COORD")
    except KeyError as e:
        return _missing(str(e))
    try:
        ox, oy = (coord if isinstance(coord, (list, tuple)) else
                  [float(x) for x in str(coord).replace(",", " ").split()][:2])
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        exe = _gdal_bin("gdal_viewshed")
        args = ["-ox", str(ox), "-oy", str(oy), "-of", "GTiff", inp, actual]
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:viewshed 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"可视域完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:viewshed 失败：{e}")


# gdal:grid*（gdal_grid.exe CLI，5 种算法各对应 -algorithm 选项）
def tool_grid_generic(parameters: dict, algorithm: str) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdal_grid.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    zfield = _get(parameters, "zfield", "ZFIELD", default=None)
    try:
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        exe = _gdal_bin("gdal_grid")
        args = ["-a", algorithm, "-of", "GTiff", inp, actual]
        if zfield:
            args += ["-zfield", str(zfield)]
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:grid({algorithm}) 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"栅格插值完成（{algorithm}）→ {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:grid {algorithm} 失败：{e}")


def tool_gridaverage(parameters: dict) -> dict[str, Any]:
    return tool_grid_generic(parameters, "average")


def tool_griddatametrics(parameters: dict) -> dict[str, Any]:
    return tool_grid_generic(parameters, "data_metrics")


def tool_gridinversedistance(parameters: dict) -> dict[str, Any]:
    return tool_grid_generic(parameters, "invdist")


def tool_gridinversedistancenearestneighbor(parameters: dict) -> dict[str, Any]:
    return tool_grid_generic(parameters, "invdistnn")


def tool_gridlinear(parameters: dict) -> dict[str, Any]:
    return tool_grid_generic(parameters, "linear")


def tool_gridnearestneighbor(parameters: dict) -> dict[str, Any]:
    return tool_grid_generic(parameters, "nearest")


# gdal:createcog：gdal_translate -of COG CLI（rasterio venv 可能缺 COG 驱动，统一走 CLI）
def tool_createcog(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（gdal:createcog 依赖 gdal_translate.exe 的 COG 驱动）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        exe = _gdal_bin("gdal_translate")
        args = ["-of", "COG", inp, actual]
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:createcog 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"COG 创建完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:createcog 失败：{e}")


# gdal:buildvirtualraster：gdalbuildvrt.exe
def tool_buildvirtualraster(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdalbuildvrt.exe）。")
    try:
        inputs = _require(parameters, "input", "INPUT", "inputs", "INPUTS")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        if isinstance(inputs, str):
            inputs = [inputs]
        _ensure_parent(out)
        exe = _gdal_bin("gdalbuildvrt")
        args = [out] + list(inputs)
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:buildvirtualraster 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out], f"VRT 构建完成：{len(inputs)} 个输入 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:buildvirtualraster 失败：{e}")


# gdal:overviews（构建金字塔）：gdaladdo.exe
def tool_overviews(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdaladdo.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
    except KeyError as e:
        return _missing(str(e))
    levels = _get(parameters, "levels", "LEVELS", default="2 4 8 16")
    resam = str(_get(parameters, "resampling", "RESAMPLING", default="nearest")).lower()
    try:
        exe = _gdal_bin("gdaladdo")
        if isinstance(levels, (list, tuple)):
            levels = " ".join(str(x) for x in levels)
        args = ["-r", resam, inp] + str(levels).split()
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:overviews 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([inp], f"金字塔构建完成（{levels}，{resam}）→ {inp}（原地写入）")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:overviews 失败：{e}")


# gdal:nearblack：nearblack.exe
def tool_nearblack(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 nearblack.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _get(parameters, "output", "OUTPUT", default=None)
    except KeyError as e:
        return _missing(str(e))
    near = _get(parameters, "near", "NEAR", "near_white", default=15)
    try:
        exe = _gdal_bin("nearblack")
        actual = _resolve_raster_out(out)[0] if out else inp
        if out:
            _ensure_parent(actual)
            args = ["-of", "GTiff", "-o", actual, "-near", str(near), inp]
        else:
            args = ["-near", str(near), inp]
        rc, sout, serr = _run_cli(exe, args)
        if rc != 0:
            return _fail(f"gdal:nearblack 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([actual], f"近黑处理完成 → {actual}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:nearblack 失败：{e}")


# gdal:proximity：gdal_proximity.bat（脚本包装）
def tool_proximity(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:proximity 不可用（需 QGIS apps/Python312/Scripts/gdal_proximity.bat）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        rc, sout, serr = _run_script_bat("gdal_proximity", [inp, actual, "-of", "GTiff"])
        if rc != 0:
            return _fail(f"gdal:proximity 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"邻近距离栅格完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:proximity 失败：{e}")


# gdal:retile：gdal_retile.bat
def tool_retile(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:retile 不可用。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out_dir = _get(parameters, "output", "OUTPUT", "out_dir", default=None)
    except KeyError as e:
        return _missing(str(e))
    tilesize = _get(parameters, "tilesize", "TILESIZE", default=256)
    try:
        target_dir = out_dir or os.path.join(os.path.dirname(inp), f"{os.path.basename(inp)}_retiled")
        os.makedirs(target_dir, exist_ok=True)
        rc, sout, serr = _run_script_bat(
            "gdal_retile",
            ["-ps", str(int(tilesize)), str(int(tilesize)), "-targetDir", target_dir, inp],
        )
        if rc != 0:
            return _fail(f"gdal:retile 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([target_dir], f"切片完成 → {target_dir}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:retile 失败：{e}")


# gdal:pansharp：gdal_pansharpen.bat
def tool_pansharp(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:pansharp 不可用。")
    try:
        pan = _require(parameters, "pan", "PANCHROMATIC", "input")
        ms = _require(parameters, "spectral", "MS", "INPUTS", "multispectral")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        if isinstance(ms, str):
            ms = [ms]
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        rc, sout, serr = _run_script_bat("gdal_pansharpen", [pan] + ms + [actual, "-of", "GTiff"])
        if rc != 0:
            return _fail(f"gdal:pansharp 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"全色锐化完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:pansharp 失败：{e}")


# gdal:rgbtopct / pcttorgb：rgb2pct.bat / pct2rgb.bat
def tool_rgbtopct(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:rgbtopct 不可用。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    n_colors = int(_get(parameters, "n_colors", "NCOLORS", default=256))
    try:
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        rc, sout, serr = _run_script_bat("rgb2pct", ["-n", str(n_colors), inp, actual])
        if rc != 0:
            return _fail(f"gdal:rgbtopct 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"RGB→PCT 完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:rgbtopct 失败：{e}")


def tool_pcttorgb(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:pcttorgb 不可用。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        actual, note = _resolve_raster_out(out)
        _ensure_parent(actual)
        rc, sout, serr = _run_script_bat("pct2rgb", [inp, actual, "-of", "GTiff"])
        if rc != 0:
            return _fail(f"gdal:pcttorgb 失败（rc={rc}）：{(serr or sout)[:500]}")
        msg = f"PCT→RGB 完成 → {actual}"
        if note:
            msg += f"（{note}）"
        return _ok([actual], msg, note=note)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:pcttorgb 失败：{e}")


# gdal:tileindex：gdaltindex.exe
def tool_tileindex(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdaltindex.exe）。")
    try:
        inputs = _require(parameters, "input", "INPUT", "LAYERS", "inputs")
        out = _require(parameters, "output", "OUTPUT", "index")
    except KeyError as e:
        return _missing(str(e))
    try:
        if isinstance(inputs, str):
            inputs = [inputs]
        _ensure_parent(out)
        exe = _gdal_bin("gdaltindex")
        rc, sout, serr = _run_cli(exe, [out] + list(inputs))
        if rc != 0:
            return _fail(f"gdal:tileindex 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out], f"瓦片索引生成完成：{len(inputs)} 个输入 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:tileindex 失败：{e}")


# gdal:gdal2tiles / gdal2xyz：脚本包装
def tool_gdal2tiles(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:gdal2tiles 不可用。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out_dir = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        os.makedirs(out_dir, exist_ok=True)
        rc, sout, serr = _run_script_bat("gdal2tiles", [inp, out_dir])
        if rc != 0:
            return _fail(f"gdal:gdal2tiles 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out_dir], f"切片网页瓦片完成 → {out_dir}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:gdal2tiles 失败：{e}")


def tool_gdal2xyz(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到，gdal:gdal2xyz 不可用。")
    try:
        inp = _require(parameters, "input", "INPUT")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    band = int(_get(parameters, "band", default=1))
    try:
        _ensure_parent(out)
        rc, sout, serr = _run_script_bat("gdal2xyz", ["-band", str(band), inp, out])
        if rc != 0:
            return _fail(f"gdal:gdal2xyz 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out], f"栅格→XYZ ASCII 完成 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:gdal2xyz 失败：{e}")


# gdal:buildvirtualvector / ogrmerge：脚本 ogrmerge.bat
def tool_buildvirtualvector(parameters: dict) -> dict[str, Any]:
    scripts = _probe_gdal_scripts_dir()
    if not scripts:
        return _fail("GDAL 脚本包装目录未找到（需要 ogrmerge.bat）。")
    try:
        inputs = _require(parameters, "input", "INPUT", "LAYERS", "inputs")
        out = _require(parameters, "output", "OUTPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        if isinstance(inputs, str):
            inputs = [inputs]
        _ensure_parent(out)
        rc, sout, serr = _run_script_bat("ogrmerge", ["-o", out] + list(inputs))
        if rc != 0:
            return _fail(f"gdal:buildvirtualvector 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([out], f"虚拟矢量合并完成：{len(inputs)} 输入 → {out}")
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:buildvirtualvector 失败：{e}")


# gdal:gdalinfo / ogrinfo：CLI 取 -json 形式 metadata；返回结构化结果
def tool_gdalinfo(parameters: dict) -> dict[str, Any]:
    import json as _json
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 gdalinfo.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        exe = _gdal_bin("gdalinfo")
        rc, sout, serr = _run_cli(exe, ["-json", inp])
        if rc != 0:
            return _fail(f"gdal:gdalinfo 失败（rc={rc}）：{(serr or sout)[:500]}")
        try:
            info = _json.loads(sout)
        except Exception:
            return _ok([inp], "gdalinfo 完成（非 JSON 输出）", raw=sout[:2000])
        return _ok([inp], f"栅格信息已读取：{inp}", info=info)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:gdalinfo 失败：{e}")


def tool_ogrinfo(parameters: dict) -> dict[str, Any]:
    import json as _json
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 ogrinfo.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        exe = _gdal_bin("ogrinfo")
        rc, sout, serr = _run_cli(exe, ["-al", "-so", inp])
        if rc != 0:
            return _fail(f"gdal:ogrinfo 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([inp], f"矢量信息已读取：{inp}", raw=sout[:4000])
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:ogrinfo 失败：{e}")


def tool_ogrinfojson(parameters: dict) -> dict[str, Any]:
    import json as _json
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 ogrinfo.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
    except KeyError as e:
        return _missing(str(e))
    try:
        exe = _gdal_bin("ogrinfo")
        rc, sout, serr = _run_cli(exe, ["-json", "-al", inp])
        if rc != 0:
            return _fail(f"gdal:ogrinfojson 失败（rc={rc}）：{(serr or sout)[:500]}")
        try:
            info = _json.loads(sout)
        except Exception:
            return _ok([inp], "ogrinfojson 完成（非 JSON 输出）", raw=sout[:2000])
        return _ok([inp], f"矢量信息已读取（JSON）：{inp}", info=info)
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:ogrinfojson 失败：{e}")


def tool_dataset_identify(parameters: dict) -> dict[str, Any]:
    """用 gdalinfo -json 探测驱动；与 gdal:gdalinfo 类似但聚焦驱动识别。"""
    return tool_gdalinfo(parameters)


def tool_executesql(parameters: dict) -> dict[str, Any]:
    bin_dir = _probe_gdal_bin_dir()
    if not bin_dir:
        return _fail("GDAL CLI 不可用（未找到 ogrinfo.exe / ogr2ogr.exe）。")
    try:
        inp = _require(parameters, "input", "INPUT")
        sql = _require(parameters, "sql", "SQL", "dialect")
    except KeyError as e:
        return _missing(str(e))
    out_path = _get(parameters, "output", "OUTPUT", default=None)
    try:
        if out_path:
            exe = _gdal_bin("ogr2ogr")
            _ensure_parent(out_path)
            rc, sout, serr = _run_cli(exe, ["-f", "GPKG", out_path, inp, "-sql", sql])
            if rc != 0:
                return _fail(f"gdal:executesql 失败（rc={rc}）：{(serr or sout)[:500]}")
            return _ok([out_path], f"SQL 执行完成（结果写入 {out_path}）")
        exe = _gdal_bin("ogrinfo")
        rc, sout, serr = _run_cli(exe, [inp, "-sql", sql])
        if rc != 0:
            return _fail(f"gdal:executesql 失败（rc={rc}）：{(serr or sout)[:500]}")
        return _ok([inp], f"SQL 执行完成（结果回读 stdout）", raw=sout[:4000])
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:executesql 失败：{e}")


# ─── 14. 暂不直接支持的工具：返回清晰 _fail 引导 ─────────────────────────────
def _tool_unsupported(name: str, hint: str = "") -> dict[str, Any]:
    return _fail(
        f"gdal:{name} 当前版本未直接实现。"
        f"{' 建议：' + hint if hint else '可通过 list_available_tools 查询替代工具。'}"
    )


def tool_buildvirtualvector_unsupported(p: dict) -> dict[str, Any]:
    return _tool_unsupported("buildvirtualvector")


def tool_importvectorintopostgis(p: dict) -> dict[str, Any]:
    return _tool_unsupported("importvectorintopostgisdatabase*",
                             "本环境不直连 PostgreSQL；如需入库请用 ogr2ogr CLI 配 PG 连接串。")


def tool_rasterize_over_unsupported(p: dict) -> dict[str, Any]:
    return _tool_unsupported("rasterize_over（旧名）", "请用 rasterize_over（已是 gdal 引擎直支持）")


# ─── 15. 工具注册表 ─────────────────────────────────────────────────────────────
# 结构与 QGIS 的 qgis:* catalog 一致：name → 实现函数 + 描述 + group。
GDAL_TOOL_CATALOG: dict[str, tuple[Any, str, str]] = {
    # 纯 Python（rasterio/pyogrio/geopandas）
    "gdal:translate": (tool_translate, "栅格式转换/区域裁剪/波段子集/类型转换（rasterio）", "Raster conversion"),
    "gdal:rasterize": (tool_rasterize, "矢量 → 栅格化（rasterio.features.rasterize）", "Vector conversion"),
    "gdal:rasterize_over": (tool_rasterize_over, "按字段值覆盖已有栅格（rasterio）", "Vector conversion"),
    "gdal:rasterize_over_fixed_value": (tool_rasterize_over_fixed_value, "按固定值覆盖已有栅格（rasterio）", "Vector conversion"),
    "gdal:polygonize": (tool_polygonize, "栅格 → 矢量面（rasterio.features.shapes）", "Raster conversion"),
    "gdal:sieve": (tool_sieve, "按最小尺寸过滤像元区（rasterio.features.sieve）", "Raster analysis"),
    "gdal:fillnodata": (tool_fillnodata, "填补 NoData（rasterio.fill.fillnodata）", "Raster analysis"),
    "gdal:cliprasterbyextent": (tool_cliprasterbyextent, "按范围裁剪栅格（rasterio.windows）", "Raster extraction"),
    "gdal:cliprasterbymasklayer": (tool_cliprasterbymasklayer, "按掩膜矢量裁剪栅格（rasterio.mask）", "Raster extraction"),
    "gdal:merge": (tool_merge, "栅格拼接（rasterio.merge）", "Raster miscellaneous"),
    "gdal:warpreproject": (tool_warpreproject, "栅格重投影（rasterio.warp.reproject）", "Raster projections"),
    "gdal:assignprojection": (tool_assignprojection, "赋投影（未重采样，rasterio）", "Raster projections"),
    "gdal:extractprojection": (tool_extractprojection, "提取投影为 .prj（rasterio）", "Raster projections"),
    "gdal:rearrange_bands": (tool_rearrange_bands, "波段重排/子集（rasterio）", "Raster conversion"),
    "gdal:rastercalculator": (tool_rastercalculator, "栅格表达式运算（rasterio + numpy）", "Raster miscellaneous"),
    "gdal:buffervectors": (tool_buffervectors, "矢量缓冲（geopandas buffer）", "Vector geoprocessing"),
    "gdal:clipvectorbyextent": (tool_clipvectorbyextent, "按范围裁剪矢量（geopandas.clip）", "Vector geoprocessing"),
    "gdal:clipvectorbypolygon": (tool_clipvectorbypolygon, "按掩膜面裁剪矢量（geopandas.clip）", "Vector geoprocessing"),
    "gdal:dissolve": (tool_dissolve, "矢量融合（geopandas.dissolve）", "Vector geoprocessing"),
    "gdal:convertformat": (tool_convertformat, "矢量格式转换（pyogrio）", "Vector conversion"),
    "gdal:offsetcurve": (tool_offsetcurve, "偏移曲线（shapely parallel_offset）", "Vector geoprocessing"),
    "gdal:onesidebuffer": (tool_onesidebuffer, "单侧缓冲（shapely single_sided）", "Vector geoprocessing"),
    "gdal:pointsalonglines": (tool_pointsalonglines, "沿线生点（shapely interpolate）", "Vector geoprocessing"),
    # GDAL CLI（gdaldem / gdal_contour / gdal_viewshed / gdal_grid 等）
    "gdal:aspect": (tool_aspect, "坡向（gdaldem aspect）", "Raster analysis"),
    "gdal:slope": (tool_slope, "坡度（gdaldem slope）", "Raster analysis"),
    "gdal:hillshade": (tool_hillshade, "山体阴影（gdaldem hillshade）", "Raster analysis"),
    "gdal:roughness": (tool_roughness, "粗糙度（gdaldem roughness）", "Raster analysis"),
    "gdal:tpitopographicpositionindex": (tool_tpitopographicpositionindex, "地形位置指数 TPI（gdaldem TPI）", "Raster analysis"),
    "gdal:triterrainruggednessindex": (tool_triterrainruggednessindex, "地形崎岖度 TRI（gdaldem TRI）", "Raster analysis"),
    "gdal:colorrelief": (tool_colorrelief, "彩色晕渲（gdaldem color-relief）", "Raster analysis"),
    "gdal:contour": (tool_contour, "等值线（gdal_contour）", "Raster extraction"),
    "gdal:contour_polygon": (tool_contour_polygon, "等值面（gdal_contour -p）", "Raster extraction"),
    "gdal:viewshed": (tool_viewshed, "可视域（gdal_viewshed）", "Raster miscellaneous"),
    "gdal:gridaverage": (tool_gridaverage, "网格化-均值算法（gdal_grid average）", "Raster analysis"),
    "gdal:griddatametrics": (tool_griddatametrics, "网格化-数据度量（gdal_grid data_metrics）", "Raster analysis"),
    "gdal:gridinversedistance": (tool_gridinversedistance, "网格化-反距离加权（gdal_grid invdist）", "Raster analysis"),
    "gdal:gridinversedistancenearestneighbor": (tool_gridinversedistancenearestneighbor, "网格化-IDW 邻近（gdal_grid invdistnn）", "Raster analysis"),
    "gdal:gridlinear": (tool_gridlinear, "网格化-线性插值（gdal_grid linear）", "Raster analysis"),
    "gdal:gridnearestneighbor": (tool_gridnearestneighbor, "网格化-最近邻（gdal_grid nearest）", "Raster analysis"),
    "gdal:createcog": (tool_createcog, "生成 Cloud Optimized GeoTIFF（gdal_translate -of COG）", "Raster conversion"),
    "gdal:buildvirtualraster": (tool_buildvirtualraster, "构建虚拟栅格 VRT（gdalbuildvrt）", "Raster miscellaneous"),
    "gdal:overviews": (tool_overviews, "构建金字塔（gdaladdo）", "Raster miscellaneous"),
    "gdal:nearblack": (tool_nearblack, "近黑像素处理（nearblack）", "Raster analysis"),
    "gdal:proximity": (tool_proximity, "邻近距离栅格（gdal_proximity）", "Raster analysis"),
    "gdal:retile": (tool_retile, "栅格切片（gdal_retile）", "Raster miscellaneous"),
    "gdal:pansharp": (tool_pansharp, "全色锐化（gdal_pansharpen）", "Raster miscellaneous"),
    "gdal:rgbtopct": (tool_rgbtopct, "RGB → PCT 调色板（rgb2pct）", "Raster conversion"),
    "gdal:pcttorgb": (tool_pcttorgb, "PCT → RGB（pct2rgb）", "Raster conversion"),
    "gdal:tileindex": (tool_tileindex, "瓦片索引（gdaltindex）", "Raster miscellaneous"),
    "gdal:gdal2tiles": (tool_gdal2tiles, "栅格 → 网页瓦片（gdal2tiles）", "Raster miscellaneous"),
    "gdal:gdal2xyz": (tool_gdal2xyz, "栅格 → XYZ ASCII（gdal2xyz）", "Raster conversion"),
    "gdal:buildvirtualvector": (tool_buildvirtualvector, "虚拟矢量合并（ogrmerge）", "Vector miscellaneous"),
    "gdal:gdalinfo": (tool_gdalinfo, "栅格信息（gdalinfo -json）", "Raster miscellaneous"),
    "gdal:ogrinfo": (tool_ogrinfo, "矢量信息（ogrinfo -al -so）", "Vector miscellaneous"),
    "gdal:ogrinfojson": (tool_ogrinfojson, "矢量信息 JSON（ogrinfo -json）", "Vector miscellaneous"),
    "gdal:dataset_identify": (tool_dataset_identify, "数据集驱动识别（gdalinfo）", "Miscellaneous"),
    "gdal:executesql": (tool_executesql, "对矢量执行 SQL（ogrinfo -sql / ogr2ogr）", "Vector miscellaneous"),
    # 暂不直接支持：返回清晰错误引导
    "gdal:importvectorintopostgisdatabaseavailableconnections": (
        tool_importvectorintopostgis, "导入矢量到 PostgreSQL（已有连接）", "Vector miscellaneous"),
    "gdal:importvectorintopostgisdatabasenewconnection": (
        tool_importvectorintopostgis, "导入矢量到 PostgreSQL（新建连接）", "Vector miscellaneous"),
}


# ─── 16. 参数 schema（供 param-validate/schema.json 与 list_available_tools 描述展示）─
# 结构：{tool_name: {"required": [...], "params": {key: {optional, parameter_type, description}}}}
def _grid_schema() -> dict[str, Any]:
    return {"required": ["input", "output"],
            "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入点矢量"},
                       "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
                       "zfield": {"optional": True, "parameter_type": "String", "description": "高程取自字段（默认 use Z）"}}}


GDAL_PARAM_SCHEMA: dict[str, dict[str, Any]] = {
    "gdal:translate": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "band": {"optional": True, "parameter_type": "String", "description": "波段子集（如 1 或 1,3,4）"},
            "outsize": {"optional": True, "parameter_type": "String", "description": "输出尺寸 WxH"},
            "projwin": {"optional": True, "parameter_type": "Extent", "description": "裁剪范围 xmin,ymin,xmax,ymax"},
            "a_srs": {"optional": True, "parameter_type": "String", "description": "目标 CRS（EPSG:XXXX）"},
        },
    },
    "gdal:rasterize": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "field": {"optional": True, "parameter_type": "String", "description": "像元值取自该字段；省略用 burn"},
            "extent": {"optional": True, "parameter_type": "Extent", "description": "输出范围"},
            "size": {"optional": True, "parameter_type": "String", "description": "输出像素 WxH，或分辨率"},
            "burn": {"optional": True, "parameter_type": "Double", "description": "默认像元值（无 field 时）"},
            "all_touched": {"optional": True, "parameter_type": "Flag", "description": "全部触及像素也算入"},
        },
    },
    "gdal:rasterize_over": {
        "required": ["input", "output", "field"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "ExistingFile", "description": "已有输出栅格（覆盖底层）"},
            "field": {"optional": False, "parameter_type": "String", "description": "覆盖像元值取自该字段"},
        },
    },
    "gdal:rasterize_over_fixed_value": {
        "required": ["input", "output", "burn"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "ExistingFile", "description": "已有输出栅格"},
            "burn": {"optional": False, "parameter_type": "Double", "description": "覆盖固定值"},
        },
    },
    "gdal:polygonize": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量（.shp / .gpkg）"},
            "band": {"optional": True, "parameter_type": "Integer", "description": "波段号（默认 1）"},
            "field": {"optional": True, "parameter_type": "String", "description": "像元值字段名（默认 DN）"},
        },
    },
    "gdal:sieve": {
        "required": ["input", "output", "size"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "size": {"optional": False, "parameter_type": "Integer", "description": "最小连通区像元数阈值"},
        },
    },
    "gdal:fillnodata": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "max_distance": {"optional": True, "parameter_type": "Double", "description": "最大搜索距离（默认 100）"},
            "smoothing": {"optional": True, "parameter_type": "Integer", "description": "平滑迭代次数"},
        },
    },
    "gdal:cliprasterbyextent": {
        "required": ["input", "output", "extent"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "extent": {"optional": False, "parameter_type": "Extent", "description": "裁剪范围 xmin,ymin,xmax,ymax"},
        },
    },
    "gdal:cliprasterbymasklayer": {
        "required": ["input", "output", "mask"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "mask": {"optional": False, "parameter_type": "ExistingFile", "description": "掩膜矢量"},
        },
    },
    "gdal:merge": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile",
                      "description": "输入栅格（单个或多个；建议传 list）"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "nodata": {"optional": True, "parameter_type": "Double", "description": "输出 NoData 值"},
            "resampling": {"optional": True, "parameter_type": "String", "description": "重采样方法 nearest/bilinear/cubic..."},
        },
    },
    "gdal:warpreproject": {
        "required": ["input", "output", "target_crs"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "target_crs": {"optional": False, "parameter_type": "String", "description": "目标 CRS（EPSG:XXXX 或整数）"},
            "resampling": {"optional": True, "parameter_type": "String", "description": "重采样方法"},
        },
    },
    "gdal:assignprojection": {
        "required": ["input", "crs"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "crs": {"optional": False, "parameter_type": "String", "description": "目标 CRS（EPSG:XXXX）"},
            "output": {"optional": True, "parameter_type": "NewFile", "description": "省略则原地赋投影"},
        },
    },
    "gdal:extractprojection": {
        "required": ["input"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "prj": {"optional": True, "parameter_type": "NewFile", "description": "输出 .prj 路径"},
        },
    },
    "gdal:rearrange_bands": {
        "required": ["input", "output", "bands"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "bands": {"optional": False, "parameter_type": "String", "description": "波段顺序如 3,2,1"},
        },
    },
    "gdal:rastercalculator": {
        "required": ["input", "output", "formula"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile",
                      "description": "输入栅格（单或多）；逐个绑定到 a/b/c/..."},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
            "formula": {"optional": False, "parameter_type": "String",
                        "description": "表达式；变量 a/b/c... 与 b1；可用 numpy 函数"},
        },
    },
    "gdal:buffervectors": {
        "required": ["input", "output", "distance"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "distance": {"optional": False, "parameter_type": "Double", "description": "缓冲距离（地图单位）"},
            "dissolve": {"optional": True, "parameter_type": "Flag", "description": "是否合并缓冲区"},
        },
    },
    "gdal:clipvectorbyextent": {
        "required": ["input", "output", "extent"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "extent": {"optional": False, "parameter_type": "Extent", "description": "裁剪范围"},
        },
    },
    "gdal:clipvectorbypolygon": {
        "required": ["input", "output", "mask"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "mask": {"optional": False, "parameter_type": "ExistingFile", "description": "掩膜矢量"},
        },
    },
    "gdal:dissolve": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "field": {"optional": True, "parameter_type": "String", "description": "按字段融合；省略全融合"},
        },
    },
    "gdal:convertformat": {
        "required": ["input", "output"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
        },
    },
    "gdal:offsetcurve": {
        "required": ["input", "output", "distance"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入线矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "distance": {"optional": False, "parameter_type": "Double", "description": "偏移距离"},
            "side": {"optional": True, "parameter_type": "String", "description": "left / right"},
        },
    },
    "gdal:onesidebuffer": {
        "required": ["input", "output", "distance"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出矢量"},
            "distance": {"optional": False, "parameter_type": "Double", "description": "缓冲距离"},
            "side": {"optional": True, "parameter_type": "String", "description": "both / left / right"},
        },
    },
    "gdal:pointsalonglines": {
        "required": ["input", "output", "distance"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入线矢量"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出点矢量"},
            "distance": {"optional": False, "parameter_type": "Double", "description": "点间隔距离"},
        },
    },
    "gdal:contour": {
        "required": ["input", "output", "interval"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格（DEM）"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出等值线（.shp/.gpkg）"},
            "interval": {"optional": False, "parameter_type": "Double", "description": "等值线间距"},
            "field": {"optional": True, "parameter_type": "String", "description": "高程字段名（默认 ELEV）"},
        },
    },
    "gdal:contour_polygon": {
        "required": ["input", "output", "interval"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出等值面 .gpkg"},
            "interval": {"optional": False, "parameter_type": "Double", "description": "等值面间距"},
        },
    },
    "gdal:viewshed": {
        "required": ["input", "output", "observer"],
        "params": {
            "input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
            "output": {"optional": False, "parameter_type": "NewFile", "description": "输出可视域"},
            "observer": {"optional": False, "parameter_type": "String", "description": "观察点 xy（如 '500,800'）"},
        },
    },
    "gdal:aspect": {"required": ["input", "output"],
                    "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                               "output": {"optional": False, "parameter_type": "NewFile", "description": "输出坡向"}}},
    "gdal:slope": {"required": ["input", "output"],
                   "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                              "output": {"optional": False, "parameter_type": "NewFile", "description": "输出坡度"}}},
    "gdal:hillshade": {"required": ["input", "output"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                                  "output": {"optional": False, "parameter_type": "NewFile", "description": "输出阴影"},
                                  "z_factor": {"optional": True, "parameter_type": "Double", "description": "垂直缩放因子"},
                                  "scale": {"optional": True, "parameter_type": "Double", "description": "水平比例"}}},
    "gdal:roughness": {"required": ["input", "output"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                                  "output": {"optional": False, "parameter_type": "NewFile", "description": "输出粗糙度"}}},
    "gdal:tpitopographicpositionindex": {"required": ["input", "output"],
                                          "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                                                     "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 TPI"}}},
    "gdal:triterrainruggednessindex": {"required": ["input", "output"],
                                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                                                  "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 TRI"}}},
    "gdal:colorrelief": {"required": ["input", "output", "color_table"],
                         "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 DEM"},
                                    "output": {"optional": False, "parameter_type": "NewFile", "description": "输出彩色晕渲"},
                                    "color_table": {"optional": False, "parameter_type": "ExistingFile", "description": "颜色查表 (.txt)"}}},
    "gdal:gridaverage": _grid_schema(),
    "gdal:griddatametrics": _grid_schema(),
    "gdal:gridinversedistance": _grid_schema(),
    "gdal:gridinversedistancenearestneighbor": _grid_schema(),
    "gdal:gridlinear": _grid_schema(),
    "gdal:gridnearestneighbor": _grid_schema(),
    "gdal:createcog": {"required": ["input", "output"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
                                  "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 COG (.tif)"}}},
    "gdal:buildvirtualraster": {"required": ["input", "output"],
                                "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格（可多个）"},
                                           "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 .vrt"}}},
    "gdal:overviews": {"required": ["input"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格（原地写）"},
                                  "levels": {"optional": True, "parameter_type": "String", "description": "金字塔层级（如 '2 4 8'）"},
                                  "resampling": {"optional": True, "parameter_type": "String", "description": "重采样方法"}}},
    "gdal:nearblack": {"required": ["input"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
                                  "output": {"optional": True, "parameter_type": "NewFile", "description": "省略则原地处理"},
                                  "near": {"optional": True, "parameter_type": "Integer", "description": "近黑阈值"}}},
    "gdal:proximity": {"required": ["input", "output"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
                                  "output": {"optional": False, "parameter_type": "NewFile", "description": "输出距离栅格"}}},
    "gdal:retile": {"required": ["input"],
                    "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
                               "output": {"optional": True, "parameter_type": "String", "description": "输出目录"},
                               "tilesize": {"optional": True, "parameter_type": "Integer", "description": "瓦片大小（默认 256）"}}},
    "gdal:pansharp": {"required": ["pan", "spectral", "output"],
                      "params": {"pan": {"optional": False, "parameter_type": "ExistingFile", "description": "全色栅格"},
                                 "spectral": {"optional": False, "parameter_type": "ExistingFile", "description": "多光谱栅格（可多个）"},
                                 "output": {"optional": False, "parameter_type": "NewFile", "description": "输出锐化栅格"}}},
    "gdal:rgbtopct": {"required": ["input", "output"],
                      "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 RGB 栅格"},
                                 "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 PCT 栅格"},
                                 "n_colors": {"optional": True, "parameter_type": "Integer", "description": "调色板色数（默认 256）"}}},
    "gdal:pcttorgb": {"required": ["input", "output"],
                      "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入 PCT 栅格"},
                                 "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 RGB 栅格"}}},
    "gdal:tileindex": {"required": ["input", "output"],
                       "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格（多个）"},
                                  "output": {"optional": False, "parameter_type": "NewFile", "description": "输出索引矢量"}}},
    "gdal:gdal2tiles": {"required": ["input", "output"],
                        "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
                                   "output": {"optional": False, "parameter_type": "String", "description": "输出目录"}}},
    "gdal:gdal2xyz": {"required": ["input", "output"],
                      "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"},
                                 "output": {"optional": False, "parameter_type": "NewFile", "description": "输出 .xyz ASCII"}}},
    "gdal:buildvirtualvector": {"required": ["input", "output"],
                                "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量（多个）"},
                                           "output": {"optional": False, "parameter_type": "NewFile", "description": "输出合并矢量"}}},
    "gdal:gdalinfo": {"required": ["input"],
                      "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入栅格"}}},
    "gdal:ogrinfo": {"required": ["input"],
                     "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"}}},
    "gdal:ogrinfojson": {"required": ["input"],
                         "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"}}},
    "gdal:dataset_identify": {"required": ["input"],
                              "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入数据"}}},
    "gdal:executesql": {"required": ["input", "sql"],
                        "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入矢量"},
                                   "sql": {"optional": False, "parameter_type": "String", "description": "SQL 语句"},
                                   "output": {"optional": True, "parameter_type": "NewFile", "description": "省略则回读 stdout"}}},
}


def _grid_schema() -> dict[str, Any]:
    return {"required": ["input", "output"],
            "params": {"input": {"optional": False, "parameter_type": "ExistingFile", "description": "输入点矢量"},
                       "output": {"optional": False, "parameter_type": "NewFile", "description": "输出栅格"},
                       "zfield": {"optional": True, "parameter_type": "String", "description": "高程取自字段（默认 use Z）"}}}


def _grid_alt_schema() -> dict[str, Any]:
    return _grid_schema()


def _grid_invdist_schema() -> dict[str, Any]:
    return _grid_schema()


def _grid_invdistnn_schema() -> dict[str, Any]:
    return _grid_schema()


def _grid_lin_schema() -> dict[str, Any]:
    return _grid_schema()


def _grid_nn_schema() -> dict[str, Any]:
    return _grid_schema()


# ─── 17. 公开 API：列工具 / 执行工具 / 可用性 ────────────────────────────────────
def list_gdal_algorithms() -> dict[str, dict[str, Any]]:
    """列出全部 gdal:* 工具目录（含纯 Python 与 CLI 实现的统一描述）。

    返回：{algo_id: {name, provider, group, description}}，与 qgis_engine
    list_qgis_algorithms 同形（供 schema 导出 / list_available_tools 展示）。
    """
    catalog: dict[str, dict[str, Any]] = {}
    for name, (_func, desc, group) in GDAL_TOOL_CATALOG.items():
        # 名字：去掉 "gdal:" 前缀后已是算法短名；name 字段用算法短名首字母大写口语形式
        short = name.split(":", 1)[1] if ":" in name else name
        nice = short.replace("_", " ").title()
        catalog[name] = {
            "name": nice,
            "provider": "gdal",
            "group": group,
            "description": desc,
        }
    return catalog


def run_gdal_tool(algo_id: str, parameters: dict) -> dict[str, Any]:
    """执行 gdal:* 工具。algo_id 形如 `gdal:translate`（或去前缀的 translate）。

    Returns: 与 inner 工具同形的 dict（{success, output, error, output_paths, engine='gdal'}）。
    """
    canon = algo_id.strip().lower()
    if not canon.startswith("gdal:"):
        canon = f"gdal:{canon}"
    entry = GDAL_TOOL_CATALOG.get(canon)
    if entry is None:
        return _fail(
            f"gdal 引擎未知工具：'{canon}'。可用 list_available_tools(source='gdal') 查询，"
            f"或加 qgis_ 前缀走 QGIS 后备。"
        )
    func = entry[0]
    try:
        return func(parameters or {})
    except Exception as e:  # noqa: BLE001
        return _fail(f"gdal:{canon} 执行异常：{e}")