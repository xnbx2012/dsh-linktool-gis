---
name: gis-data-preview
description: 将 .shp / .gdb / .GeoJson 数据推送到网页实现数据实时预览，支持点/线/面图层的简单渲染、唯一值渲染和分级渲染。仅限`gis-data-visualisation`智能体调用。
---

# GIS可视化技能

本技能提供基于 FastAPI + Leaflet 的 GIS 数据实时网页可视化能力，通过 CLI 工具管理可视化服务生命周期，并将用户输入的地理数据（.shp、.gdb、.geojson等格式）统一转换为 WGS 1984 坐标系下的 GeoJSON 格式数据，并通过可视化服务实时推送至网页。

## 整体流程

当用户输入数据时，可视化智能体需要：
1. **识别数据格式**：检查输入数据的后缀名（.shp或.geojson 等，根据路径中是否包含`.gdb`判断是否GDB要素类），确定数据类型。如果是 .shp 或 .gdb 格式，则需要检查坐标系和进行转换；如果是 .geojson 格式，则可以跳过第3步的数据转换。
2. **检查并统一坐标系为 WGS 1984（EPSG:4326）**：检查数据的坐标系是否为 WGS 1984（EPSG:4326），如果不是，则调用 `arcgis-mcp-server` 的 `execute-gis-tool` 工具，使用 `arcpy.management.Project` 工具进行投影转换。将预存的 WGS 1984 投影文件路径 `./scripts/coordinate/WGS1984.prj` 作为 `out_coor_system` 参数传入，将数据转换为目标坐标系。如数据已为 WGS 1984，则跳过此步骤。
3. **将数据转换为 GeoJSON 格式**：如果数据格式不是 GeoJSON（如 .shp、.gdb 等），则调用 `arcgis-mcp-server` 的 `execute-gis-tool` 工具，使用 `arcpy.conversion.FeaturesToJSON` 工具将数据转换为 GeoJSON 格式。`out_json_path` 参数设置为 `/test/02_WorkSpace/geojson数据/` 目录下，文件名与输入数据相同但后缀改为 .geojson。
4. **创建符号系统**：根据用户需求和分析 GeoJSON 数据内容（几何类型、字段特征等），构建renderer JSON 配置，支持 simple（简单渲染）、unique（唯一值渲染）和 graduated（分级渲染）三种类型。
5. **启动可视化服务**：运行 `./scripts/visualize.py start` 启动 FastAPI + Leaflet 服务，自动打开浏览器。如果服务已在运行，则提示并跳过。
6. **推送数据至网页**：运行 `./scripts/visualize.py push` 携带 renderer 配置和 GeoJSON 路径，将转换后的 GeoJSON 数据和符号系统通过 POST `/api/layers` 接口推送至后端，后端通过 WebSocket 广播到浏览器，实现地图的动态更新。
7. **实时推送更新**：每当用户输入新的地理数据时，重复上述流程进行数据转换、符号化和推送，实现地图的实时更新。

## 脚本位置

```bash
uv run ./scripts/visualize.py --help
```

## CLI 命令

使用 `uv run` 执行 `visualize.py`，支持以下子命令:

### 1. 启动服务

```bash
uv run ./scripts/visualize.py start
```

### 2. 停止服务

```bash
uv run ./scripts/visualize.py stop
```

### 3. 推送图层

```bash
uv run ./scripts/visualize.py push --path <文件路径> --name <图层名称> [--color <颜色>] [--type <几何类型>] [--renderer <符号系统 JSON>]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--path` | 是 | GeoJSON 文件路径（.geojson / .json）。非 GeoJSON 格式需先通过 `arcpy.conversion.FeaturesToJSON` 工具转换 |
| `--name` | 是 | 图层在地图上的显示名称 |
| `--color` | 否 | 符号颜色，十六进制格式（默认 `#e53935`） |
| `--type` | 否 | 几何类型：`auto`（自动检测，默认）/ `point` / `line` / `polygon` |
| `--renderer` | 否 | 符号系统 JSON 字符串（如 `{"type":"unique","field":"landuse",...}`）。传入时覆盖 `--color` 和 `--type` |

-  非 GeoJSON 格式（.shp、.gdb 等）需通过 `arcpy.conversion.FeaturesToJSON` 工具转换为 GeoJSON，再由智能体调用         
  `visualize.py push` 推送至网页
- 转换后的 GeoJSON 文件保存在 `/test/02_WorkSpace/geojson数据/` 目录
- 数据通过 POST `/api/layers` 推送至后端，再经 WebSocket 广播到浏览器

## 符号系统（Renderer）

推送图层时可指定渲染器类型，通过构建 renderer JSON 配置控制地图符号化样式。

### simple — 简单渲染

所有要素使用相同样式：

```json
{
  "type": "simple",
  "symbol": {
    "color": "#e53935",
    "weight": 2,
    "opacity": 1.0,
    "fillColor": "#e53935",
    "fillOpacity": 0.6,
    "radius": 5
  }
}
```

### unique — 唯一值渲染

根据指定字段的唯一值分配不同颜色：

```json
{
  "type": "unique",
  "field": "landuse",
  "symbol": { "color": "#999", "weight": 1, "fillOpacity": 0.6, "radius": 5 },
  "unique_values": {
    "林地": { "color": "#2e7d32" },
    "水体": { "color": "#1565c0" },
    "建设用地": { "color": "#e53935" }
  }
}
```

### graduated — 分级渲染

根据指定字段的数值范围分级着色：

```json
{
  "type": "graduated",
  "field": "population",
  "symbol": { "color": "#999", "weight": 1, "fillOpacity": 0.6, "radius": 5 },
  "classification_method": "natural_breaks",
  "classification_breaks": [
    { "min": 0, "max": 100, "color": "#ffffcc", "label": "0-100" },
    { "min": 100, "max": 500, "color": "#fd8d3c", "label": "100-500" },
    { "min": 500, "max": 1000, "color": "#800026", "label": "500-1000" }
  ]
}
```
## plan0701 Workflow 边界

- 本 Skill 应嵌入完整 Workflow 的 Deliver 阶段，用于已有结果的网页可视化预览。
- 不得被单独作为完整复杂任务的主体 Workflow。
