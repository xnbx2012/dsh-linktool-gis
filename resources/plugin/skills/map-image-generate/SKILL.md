---
name: map-image-generate
description: 使用color-style-mcp根据指定数据生成地图图片的完整指导，生成地图图片时必须用此Skill。
allowed-tools: mcp__plugin_linktool-plugin_color-style__create_map, mcp__MiniMax__understand_image, mcp__arcgis-mcp-server__list_gdb_contents, mcp__arcgis-mcp-server__query_feature_attributes, mcp__arcgis-mcp-server__get_data_properties
---

# plan0701 Workflow 边界

- 本 Skill 仅用于完整 Workflow 的 Deliver 阶段或已有结果的制图后处理。
- 不得作为完整复杂任务的独立 Workflow，也不得替代 `@gis-tool` 执行主体 GIS 分析。
- 制图必须消费已验证的 Workflow 产物、真实字段统计和明确输出路径。

# Color-Style MCP 调用指南

## 概述

通过调用 `color-style-mcp` MCP服务器的工具，传入一个JSON配置即可生成包含多图层、标注、指北针、图例、比例尺的300dpi PNG地图。请务必按照以下格式和约定编写JSON配置，以确保地图正确生成。

## 调用方法

**工具名称**: `mcp__plugin_linktool-plugin_color-style__create_map`

**参数**:
- `map_json` (string): 完整的JSON配置字符串

## JSON格式

```json
{
  "layout": {
    "title": "地图标题",
    "output_path": "C:/output/map.png",
    "page_size": "A4",
    "orientation": "landscape",
    "extent_margin": 0.10
  },
  "layers": [
    {
      "id": "图层标识",
      "feature_class": "要素类路径(.gdb/要素类 或 .shp)",
      "visible": true,
      "renderer": { "根据类型不同，见下方" },
      "labeling": {
        "enabled": true,
        "field": "标注字段",
        "font": { "family": "SimSun", "size": 12 },
        "color": [0, 0, 0, 100],
        "halo": { "color": [255, 255, 255, 100], "size": 1 }
      }
    }
  ],
  "map_elements": {
    "north_arrow": { "enabled": true },
    "legend": { "enabled": true, "title": "图  例" },
    "scale_bar": { "enabled": true }
  }
}
```

## 符号系统类型

### 1. 简单符号 (simple)

```json
"renderer": {
  "type": "simple",
  "symbol": {
    "type": "polygon",
    "fill_color": [R, G, B, 透明度],
    "outline_color": [R, G, B, 透明度],
    "outline_width": 1
  }
}
```

### 2. 唯一值符号 (unique_value)

```json
"renderer": {
  "type": "unique_value",
  "field": "分类字段",
  "classes": [
    { "value": "类别值", "label": "图例名", "symbol": { "fill_color": [...], "outline_color": [...] } }
  ]
}
```

### 3. 分级符号 (graduated_colors)

```json
"renderer": {
  "type": "graduated_colors",
  "field": "数值字段",
  "classification_method": "natural_breaks",
  "class_count": 5,
  "color_scheme": {
    "colors": [
      [255, 255, 204, 90],
      [194, 230, 153, 90],
      [120, 198, 121, 90],
      [49, 163, 84, 90],
      [0, 104, 55, 90]
    ]
  },
  "outline_color": [100, 100, 100, 100],
  "outline_width": 1
}
```

分级设色优先使用 `color_scheme.colors` 传入完整 RGB-A 色带；也可使用 `color_scheme.start_color` 和 `color_scheme.end_color` 让 MCP 按 `class_count` 自动插值。仅在确知 ArcGIS 工程中存在色带名称时，才使用 `color_scheme.name`。

分级方法: `natural_breaks` | `equal_interval` | `quantile` | `standard_deviation`

### 4. 分类符号 (classed)

```json
"renderer": {
  "type": "classed",
  "field": "数值字段",
  "classes": [
    { "label": "类别名称", "symbol": { "fill_color": [...] } }
  ]
}
```

## 关键约定

以下为默认的设置项，均可根据实际情况修改：

- **标注字体**：默认宋体 (`SimSun`)，白色轮廓 (`halo`)，黑色字体
- **输出分辨率**：固定300dpi PNG
- **布局尺寸**：A4横版（可配置为A3、Letter）
- **图例标题**：默认"图  例"
- **指北针位置**：地图框左上角内侧
- **图例位置**：地图框左下角内侧
- **比例尺位置**：地图框右下角内侧

## 最小调用示例

```json
{
  "layout": {
    "title": "测试地图",
    "output_path": "C:/output/test.png"
  },
  "layers": [
    {
      "id": "layer1",
      "feature_class": "C:/data.gdb/parcel",
      "visible": true,
      "renderer": {
        "type": "simple",
        "symbol": { "fill_color": [200, 200, 200, 80], "outline_color": [0, 0, 0, 100], "outline_width": 1 }
      },
      "labeling": { "enabled": false }
    }
  ]
}
```
# 地图制图流程指南
1. 制图需求分析：明确用户制图需求、地图主题、制图目的、成果类型和输出要求。
2. 制图数据分析：参考 'map-image-generate\skills\MapDrawing-DataAnalysis.md'，分析制图数据的数据信息。
3. 字段类型判断：参考 'map-image-generate\skills\FieldType-Judgement.md'，分析字段数据特征，判断适合的制图字段类型（连续数值、有序等级、离散类别、二元变量）和几何类型（点、线、面）。
4. 符号系统选择：参考 'map-image-generate\skills\SymbolSystem-design.md'，根据字段类型和几何类型选择合适的符号系统。
5. 配色方案设计：参考 'map-image-generate\skills\ColorScheme-design.md'，选择合适的配色方案，确保地图主题突出、符号表达清晰、视觉效果美观。
6. 调用 `/map-image-generate` Skill 生成地图图件：传入符合规范的 JSON 配置，生成地图。
7. 图件美观与质量检查：参考 'map-image-generate\skills\MapCheck.md',调用 `mcp__MiniMax__understand_image` 工具对生成图件进行质量检查，确保制图要素齐全、布局合理、主体居中、图例与标注清晰、配色符合主题、图件美观。
8. 根据 VLM 审图意见判断是否需要重新制图，直到输出最终地图路径、制图参数说明和质量检查结论。

# 制图规范
1. 地图制图必须确保地图的准确性、规范性、可读性和安全性。
2. 坐标系：采用国家统一平面坐标系（高斯-克吕格投影）和高程系统（1985国家高程基准），确保空间数据的准确定位和测量。
3. 公开地图特殊内容规范-中国全图要求：
  - 图幅范围：东到黑龙江与乌苏里江交汇处，西到喷赤河南北流向段，北到黑龙江最北江段，南到曾母暗沙以南中国政府网。
  - 必须表示南海诸岛、钓鱼岛及其附属岛屿，台湾岛、海南岛完整显示。
  - 海断续线按规定绘制，陆地国界线与海岸线符号有区别时用相应陆地国界线符号表示。
  - 图例中必须包含南海诸岛、钓鱼岛及其附属岛屿、台湾岛、海南岛等特殊内容的符号说明。
4. 制图字段和符号系统选择规范：
  - 禁止默认使用 `OBJECTID`、`FID`、`Shape`、`Shape_Area`、`Shape_Length`、`GlobalID` 等系统字段作为主制图字段，除非用户明确要求。
  - 连续数值字段应使用分级设色符号系统；
  - 有序等级字段应使用顺序色带符号系统；
  - 离散类别字段应使用唯一值分类符号系统；
  - 二元字段应使用对比色符号系统；
  - 点、线、面要素应选择符合几何类型的符号表达。
5. 配色规范：
  - 配色应符合地图主题和字段语义，确保视觉效果美观、符号表达清晰。
  - 禁止对分类变量使用无序渐变色带。
  - 禁止对连续变量使用大量随机离散颜色。
6. 图件质量规范：
  - 禁止生成缺少标题、图例、比例尺、指北针等基本制图要素的正式图件，除非用户明确要求简图。
  - 图件布局应合理，地图主体应居中，图例、比例尺、指北针等元素应放置在不遮挡主图的位置，避免过多空白或裁切。
  - 标注应清晰，避免重叠、过密、裁切或字号过小问题。
  - 配色应符合地图主题，分级变量应使用渐变色带，分类变量颜色应容易区分，图例颜色应与地图一致。 