# CLAUDE.md — arcgis-mcp-server

LinkTool GIS 核心 MCP 服务器。五引擎统一调度（内置 Inner / WhiteboxTools / GDAL / QGIS / ArcGIS Pro），进程内 GDAL 栈实现全部数据查看工具，arcpy 经 ArcPyWorker 子进程执行。

---

## 项目结构

```
arcgis-mcp-server/
├── main.py                 # FastMCP 服务器入口 + 五引擎调度 + 工具定义
├── generate_schema.py      # 五引擎工具 schema 生成（7 天 TTL，启动时后台执行）
├── schema_loader.py        # schema.json 搜索缓存（list_available_tools 用）
├── detect_engines.py       # 引擎可用性探测（设置页刷新按钮的执行体）
├── arcpy_worker.py         # ArcPyWorker：arcgispro-py3 子进程 worker
├── topology.py             # 矢量拓扑修复（make_valid / explain_validity）
├── pyproject.toml          # uv 依赖（Python >=3.12,<3.13，mcp/whitebox/pyogrio/geopandas/rasterio/shapely）
├── uv.lock                 # 锁定的依赖版本
└── README.md               # 面向用户的说明
```

`schema.json` 为运行时生成（7 天 TTL），不入库；`scripts/param-validate` hook 经 `../arcgis-mcp-server/schema.json` 读取同一份（单一事实源）。

## 五引擎调度

`execute_gis_tool(tool_name, parameters)` 按 `_resolve_engine` 解析：

| tool_name 形态 | 引擎 | 说明 |
|---|---|---|
| `inner_xxx` | inner | 仅内置（不降级），如 `inner_buffer` |
| `wbt_xxx` | whitebox | 仅 Whitebox，如 `wbt_clip` |
| `gdal_xxx` / `gdal:xxx` | gdal | 如 `gdal_translate`、`gdal:slope` |
| `qgis_provider:algo` / `provider:algo` | qgis | 如 `qgis_native:buffer`、`native:buffer` |
| `arcpy_xxx` / `arcpy.模块.工具名` | arcpy | 如 `arcpy.analysis.Buffer` |
| 裸名 | 自动降级 | inner → wbt → gdal → qgis → arcpy |

- 引擎开关（`engine-switches.json`）每次调用实时读取：降级链跳过已关闭引擎；前缀强制命中已关闭引擎 → 明确报错「已在设置页关闭」
- GDB 输入/输出经临时 shapefile/GTiff 桥接（Whitebox/QGIS/GDAL CLI 引擎）
- 矢量执行前拓扑修复（PRE/POST pass）；输出自动 GeoJSON 嵌入（`.gis-result.json`）
- 超时 15 分钟（900 秒）

## 启动顺序（main.py 关键约束）

1. **重型 GDAL import（rasterio/pyogrio/geopandas/shapely）必须在 `mcp.run()` 之前**——否则 GDAL C 扩展在事件循环启动后初始化，与 anyio stdin 读取线程死锁
2. `repair_proj_env()`（来自 shared/gis_io）在 GDAL 栈定位 proj.db 前修复机器残留的 `PROJ_LIB`/`GDAL_DATA`（PostGIS 老库会让一切 EPSG 查询失败）
3. `PYTHONUTF8=1` + stdio reconfigure UTF-8（GBK 控制台解码崩溃）
4. `_prewarm` 后台线程：whitebox 预热 + schema 生成（不阻塞 stdio）

## 工具列表

| 工具名 | 引擎 | 说明 |
|---|---|---|
| `execute_gis_tool` | 五引擎 | 统一执行入口（见上表） |
| `list_gdb_contents` | 内置 | GDB 要素类/栅格/表/要素数据集分类列表（pyogrio/OpenFileGDB） |
| `query_feature_attributes` | 内置 | 属性查询（`max_records ≤ 500` 服务端硬上限，长字符串截断） |
| `get_data_properties` | 内置 | 元信息（坐标系 WKID/WKT、范围、字段、要素数、栅格属性） |
| `get_field_unique_values` | 内置 | 字段唯一值统计 |
| `list_available_tools` | 五引擎 | 跨引擎工具搜索（schema 缓存 + 动态查询降级） |
| `get_engine_status` | — | 当前引擎开关状态与可用性 |
| `create_gdb_database` | 内置 | 创建 File GDB |

所有内置工具零外部依赖（进程内 GDAL/pyogrio），Linux 可用。

## 引擎探测（detect_engines.py）

`uv run python detect_engines.py`（在 MCP 的 uv 环境内）并发探测五引擎，stdout 输出单个 JSON：

```json
{"engines": {"inner": {"available": true, "detail": "22 个内置工具"}, ...}, "checked_at": "iso"}
```

退出码恒为 0（单引擎失败不阻断）。宿主设置页「刷新检测」按钮经适配层调用，首次探测发现不可用引擎时自动关闭对应开关。

## 开发规范

### 添加新工具

- **内置引擎**：在 `shared/native_tools.py` 的 `CUSTOM_TOOL_REGISTRY` 注册函数 + `INNER_PARAM_SCHEMA` 声明参数
- **GDAL 直执行**：在 `shared/gdal_engine.py` 的 `GDAL_TOOL_CATALOG` + `GDAL_PARAM_SCHEMA` 注册
- **MCP 工具**：`main.py` 末尾按 FastMCP `@mcp.tool()` 模式添加

### 本地调试

```bash
cd scripts/arcgis-mcp-server
uv run python generate_schema.py schema.json   # 生成 schema 缓存
uv run python main.py                          # stdio 模式
```

测试用 `ARCGIS_MCP_NO_PREWARM=1` 跳过预热；引擎开关注入 `LINKTOOL_ENGINE_SWITCHES` 指向 JSON 文件。

## 依赖

```toml
[project]
requires-python = ">=3.12,<3.13"   # QGIS 进程内运行时 ABI 匹配
dependencies = [
  "mcp[cli]>=1.26,<2",
  "whitebox", "pyogrio", "geopandas", "rasterio", "shapely",
]

[project.optional-dependencies]
windows = ["pywin32>=306"]   # .lnk 快捷方式解析（ArcGIS Pro 定位）
```
