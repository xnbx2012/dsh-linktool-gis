# LinkTool GIS MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server providing unified GIS tool execution across **five engines** — built-in (inner), WhiteboxTools, GDAL, QGIS, and ArcGIS Pro (arcpy) — plus zero-dependency data inspection tools. One `execute_gis_tool` entry, five backends, per-engine enable switches.

## Features

- **五引擎统一调度**：`inner_` / `wbt_` / `gdal_` / `qgis_` / `arcpy_` 前缀强制指定引擎；裸名按 内置 → Whitebox → GDAL → QGIS → ArcPy 顺序自动降级解析
- **引擎开关实时生效**：宿主设置页逐引擎开关，服务器每次工具调用读取 `engine-switches.json`；关闭的引擎在降级链中被跳过，前缀强制命中关闭引擎则明确报错
- **零依赖数据工具**：`list_gdb_contents`、`query_feature_attributes`、`get_data_properties`、`get_field_unique_values`、`list_available_tools`、`get_engine_status` 等用进程内 GDAL/pyogrio 实现，不依赖任何外部 GIS 软件
- **GDB 双向桥接**：Whitebox/QGIS/GDAL CLI 引擎不支持 GDB 输入输出时，自动经临时 shapefile/GTiff 转换（`_convert_gdb_inputs` / `_redirect_gdb_outputs`）
- **结果上屏**：矢量输出自动转 WGS84 GeoJSON 嵌入返回结果（`.gis-result.json` 落盘 + `geojson` 字段）
- **拓扑修复**：矢量工具执行前自动 make_valid / 修复无效几何

## Engines

| 引擎 | 前缀 | 依赖 | 平台 |
|---|---|---|---|
| 内置 Inner | `inner_` | geopandas/shapely/rasterio（随依赖） | Windows / Linux / macOS |
| WhiteboxTools | `wbt_` | whitebox pip 包（首次调用下载二进制） | Windows / Linux / macOS |
| GDAL | `gdal_` | rasterio/pyogrio 进程内；CLI 二进制可选（自动探测 PATH 与 QGIS 安装目录） | Windows / Linux / macOS |
| QGIS | `qgis_` | QGIS 安装（Windows: `qgis_process*.bat` 进程内；POSIX: PATH 上的 `qgis_process` CLI，offscreen） | Windows / Linux / macOS |
| ArcGIS Pro | `arcpy_` | ArcGIS Pro（`arcgispro-py3` 解释器，经 ArcPyWorker 子进程） | Windows 专属 |

引擎可用性探测：`detect_engines.py` 并发探测五个引擎，输出单个 JSON（宿主设置页「刷新检测」按钮经适配层调用）。

## Requirements

- Python 3.12（QGIS 进程内运行时 ABI 匹配）、`uv`
- 引擎依赖按需：ArcGIS Pro（仅 arcpy 引擎）、QGIS（仅 qgis 引擎）；Whitebox/GDAL/内置随 `pyproject.toml` 依赖自动就绪

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ARCGIS_PRO_PATH` | ArcGIS Pro 安装目录（仅 arcpy 引擎；未设置时自动探测） |
| `LINKTOOL_ENGINE_SWITCHES` | 引擎开关 JSON 文件路径（宿主注入；缺省读 `<scripts>/../../.runtime/engine-switches.json`） |
| `AGENT_WORK_DIR` | 工作空间根（01_DataBackup/02_WorkSpace/03_Result 策略的数据源） |
| `ARCGIS_MCP_NO_PREWARM=1` | 跳过启动预热（whitebox + schema 生成），用于测试 |
| `ARCGIS_MCP_FULL_SCHEMA=1` | schema 生成时包含 whitebox 完整参数详情 |

## Usage

```json
{
  "tool_name": "wbt_clip",
  "parameters": { "input": "D:/proj/01_DataBackup/test.gdb/sites", "clip": "D:/proj/02_WorkSpace/zones.shp", "output": "D:/proj/02_WorkSpace/sites_clipped.shp" }
}
```

其他形态：`inner_buffer`、`gdal_translate` / `gdal:slope`、`qgis_native:buffer` / `native:buffer`、`arcpy.analysis.Buffer`。查数据类工具直接调用（如 `list_gdb_contents(gdb_path)`）。

## Schema 生成

启动时后台线程生成 `schema.json`（7 天 TTL）：inner（注册表）/ whitebox（list_tools + tool_parameters）/ gdal（GDAL_PARAM_SCHEMA）/ qgis（进程内注册表逐算法导出 required/params）。`scripts/param-validate` hook 读同一文件做必填参数校验（单一事实源）。

## Testing

```bash
uv run python generate_schema.py schema.json   # 手动生成 schema
ARCGIS_MCP_NO_PREWARM=1 uv run python main.py  # 直接启动（stdio）
```

## Troubleshooting

- **"引擎已在设置页关闭"**：`LINKTOOL_ENGINE_SWITCHES` 指向的文件中该引擎为 false；在宿主设置页开启即可。
- **rasterio EPSG 报错（"another PROJ installation"）**：机器残留 `PROJ_LIB`/`GDAL_DATA`（常见于装过 PostgreSQL/PostGIS）；`gis_io.repair_proj_env()` 会在 GDAL 栈初始化前自动改回 wheel 自带数据目录。
- **Windows 控制台 GBK 解码崩溃**：`main.py` 已强制 `PYTHONUTF8=1` 并 reconfigure stdio；重型 GDAL 导入固定在 `mcp.run()` 之前，避免 stdio 死锁。
