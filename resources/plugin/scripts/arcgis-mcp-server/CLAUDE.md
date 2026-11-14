# CLAUDE.md — arcgis-mcp-server

ArcGIS 核心 MCP 服务器。在本地 Python 环境中运行，通过 `subprocess` 调用 ArcGIS Pro 的 `arcgispro-py3` 环境执行所有 ArcPy 操作。

---

## 项目结构

```
arcgis-mcp-server/
├── main.py                 # FastMCP 服务器入口 + 工具定义
├── pyproject.toml          # uv 依赖配置（Python >=3.12, mcp[cli]>=1.26.0）
├── uv.lock                 # 锁定的依赖版本
├── README.md               # 面向用户的安装/使用说明
├── .claude/
│   └── settings.local.json # 本地 MCP 服务器启用配置
└── .venv/                  # uv 虚拟环境
```

---

## 工具列表

### `execute_gis_tool(tool_name, parameters)`

执行任意 ArcPy 工具，通过 `arcpy.Describe` 反射调用。

- `tool_name`: `arcpy.模块.工具名`，如 `arcpy.analysis.Clip`、`arcpy.management.CopyFeatures`
- `parameters`: 字典形式的参数字典，key 必须与工具官方参数名一致

**示例**:
```json
{
  "tool_name": "arcpy.analysis.Buffer",
  "parameters": {
    "in_features": "D:/test/01_DataBackup/roads.shp",
    "out_feature_class": "D:/test/02_WorkSpace/roads_buffer.shp",
    "buffer_distance_or_field": "100 Meters"
  }
}
```

**实现方式**:
1. 拼接 Python 脚本字符串（通过 `sys.stdin` 接收参数）
2. `execute_arcpy_script()` 调用 `subprocess.run([python_exe, "-c", script], input=json.dumps(params), timeout=900)`
3. 解析 stdout 中的 JSON 返回结果（含 `success`、`result`、`messages`、`error`、`traceback`）

---

### `list_gdb_contents(gdb_path)`

遍历 `.gdb` 文件地理数据库，返回要素类、栅格、表、要素数据集等分类列表。

**返回字段**:
- `feature_classes[]`: 含 `name`, `path`, `dataType`, `shapeType`, `fieldCount`
- `raster_datasets[]`
- `tables[]`
- `feature_datasets[]`
- `topologies[]`
- `network_datasets[]`

---

### `query_feature_attributes(feature_path, sql_where, max_records)`

查询要素类属性表，支持 SQL WHERE 筛选。

- `feature_path`: GDB 要素类路径或 SHP 路径
- `sql_where`: SQL 条件字符串（**不加** `WHERE` 关键字），如 `"ZONE = 'R1' AND AREA > 1000"`
- `max_records`: 最大返回记录数（默认 100，防止上下文爆炸）

**返回字段**:
- `fields[]`: 含 `name`, `alias`, `type`, `length`
- `data[]`: 属性记录列表
- `total`: 总记录数
- `returned`: 实际返回数

---

### `get_data_properties(data_path)`

获取任意 GIS 数据的完整元信息。

**返回字段**:
- `data_type`: FeatureClass / ShapeFile / RasterDataset / Table 等
- `extent`: X/Y/Z/M 的 Min/Max
- `coordinate_system`: `name`, `factory_code`(WKID), `wkt`, `unit`
- `tolerance`: XY/Z/M Tolerance 和 Resolution
- `fields[]`: 完整字段列表（含 `nullable`, `required`, `domain`）
- `shape_type`: 几何类型（Point / Polyline / Polygon）
- `feature_count`: 要素数量（仅矢量数据）
- `raster_properties`: 栅格属性（width, height, band_count, pixel_type, cell_size, no_data_value, compression）
- `value_range`: 栅格值域（min/max）

---

## ArcGIS Pro Python 解释器定位

函数 `find_py_interpreter()` 按以下顺序查找 `python.exe`:

1. **环境变量**: `ARCGIS_PRO_PATH`（如 `C:\Program Files\ArcGIS\Pro`）
2. **默认路径**: C/D/E 盘的 Program Files、Program Files (x86)、盘符根目录
3. **AppData 安装**: `LOCALAPPDATA\Programs\ArcGIS\Pro`
4. **快捷方式解析**: 桌面/开始菜单的 `.lnk` 文件 → `win32com.client` 解引用
5. **注册表**: `HKEY_LOCAL_MACHINE\SOFTWARE\ESRI\ArcGISPro` → `InstallDir`
6. **克隆环境**: `arcgispro-py3-clone`

**返回值**: `C:\...\Pro\bin\Python\envs\arcgispro-py3\python.exe`

---

## 开发规范

### 添加新工具

在 `main.py` 末尾按如下模式添加：

```python
@mcp.tool()
async def my_tool(param: str) -> str:
    """
    工具描述（Claude 会读到）

    Args:
        param: 参数说明

    Returns:
        JSON 字符串
    """
    script = '''
import arcpy, json, sys
params = json.loads(sys.stdin.read())
# ... ArcPy 代码 ...
print(json.dumps({"success": True, "result": ...}))
'''
    result = execute_arcpy_script(script, {"param": param})
    return json.dumps(result, ensure_ascii=False, indent=2)
```

**注意事项**:
- 脚本中 ArcPy 代码执行在 ArcGIS Pro Python 环境，**不是**本地 Python 环境
- 脚本结果**必须通过 `print(json.dumps(...))`** 打印到 stdout
- 脚本内的异常处理应捕获并打印 JSON 错误信息，而不是让异常抛出

### 本地调试

```bash
# 启动服务器（stdio 模式）
uv run python main.py

# 在 Claude Code 中测试（在 test/ 目录启动）
claude --debug --plugin-dir ../plugin
```

---

## 依赖

```toml
[project]
requires-python = ">=3.12"
dependencies = ["mcp[cli]>=1.26.0"]

[project.optional-dependencies]
windows = ["pywin32>=306"]   # 用于解析 .lnk 快捷方式
```
