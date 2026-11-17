# CLAUDE.md — shared

共享工具模块。提供五引擎的引擎实现与 ArcPy 解释器定位，供 arcgis-mcp-server 与各 Hook 共用。

---

## 模块

### gis_io.py — 共享 GIS 读写（GDAL/OGR 后端，无 arcpy）

```python
from gis_io import repair_proj_env, list_gdb_layers, query_attributes, data_properties, field_unique_values
```

- `repair_proj_env()`：修复机器残留的 `PROJ_LIB`/`PROJ_DATA`/`GDAL_DATA`（PostGIS 老库会让 rasterio/pyogrio 一切 EPSG 查询失败）；在 GDAL 栈首次定位 proj.db 前调用
- `list_gdb_layers` / `query_attributes` / `data_properties` / `field_unique_values`：pyogrio/geopandas/rasterio 进程内实现，GDB 经 OpenFileGDB（只读）驱动
- 矢量输出转 WGS84 GeoJSON（`embed_geojson`，供 execute_gis_tool 嵌入）

### native_tools.py — 内置引擎（inner）

`CUSTOM_TOOL_REGISTRY`（纯 Python 工具注册表：buffer/project/spatial_join/band_math/字段计算等 22 个）+ `INNER_PARAM_SCHEMA`（参数 schema）。零外部 GIS 依赖。

### gdal_engine.py — GDAL 直执行引擎

`GDAL_TOOL_CATALOG` + `GDAL_PARAM_SCHEMA`（59 个 gdal:* 工具）。进程内 rasterio/pyogrio 优先，CLI 二进制（gdal_translate/gdaldem/...）兜底；二进制探测覆盖 PATH、QGIS 3.x/4.x 安装目录、POSIX `shutil.which`。

### qgis_engine.py — QGIS 引擎

- Windows：进程内 QgsApplication 运行时（`_configure_qgis_environment` 注入 QGIS Python 路径；只注册 native+3d provider，其余 provider 经 `qgis_process*.bat` CLI）
- POSIX：PATH 上的 `qgis_process` CLI（`QT_QPA_PLATFORM=offscreen`，`--json` 输出 raw_decode 解析，输出路径自动回填）
- `list_qgis_algorithms` / `get_qgis_help` / `export_qgis_schemas`（完整 required/params 导出，供 generate_schema）

### find_arcpy.py — ArcPy 解释器定位与脚本执行

```python
from find_arcpy import find_py_interpreter, run_arcpy_script
```

`find_py_interpreter()`：环境变量 `ARCGIS_PRO_PATH` → 默认安装路径 → AppData → 快捷方式 → 注册表。`run_arcpy_script(script, input_data, timeout)` 经 arcgispro-py3 子进程执行，返回 `{"success", "result", "error"}`。

## 引用方式

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from gis_io import query_attributes
```

## GDAL 栈依赖（hook 使用方）

data-backup / result-validate 经 shared/gis_io.py 读写 GIS 数据，其 hooks.json 启动命令需
`uv run --no-project --with-requirements "${DSH_PLUGIN_ROOT}/scripts/shared/gdal-requirements.txt" python ...`。
版本/加包集中在 `gdal-requirements.txt`（单一事实源）。
