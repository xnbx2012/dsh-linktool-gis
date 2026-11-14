# Color-Style MCP 调用指南

## 概述

通过MCP调用ArcGIS制图工具，传入一个JSON配置即可生成包含多图层、标注、指北针、图例、比例尺的300dpi PNG地图。

## 调用方法

**工具名称**: `create_map`

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
  "outline_color": [100, 100, 100, 100],
  "outline_width": 1
}
```

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
