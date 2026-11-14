# Color-Style MCP Server

ArcGIS地图制图MCP服务器，支持多种符号系统，输出300dpi PNG地图。

## JSON样式规范

### 通用结构

```json
{
  "layout": {
    "title": "地图标题",
    "output_path": "输出路径.png",
    "page_size": "A4",
    "orientation": "landscape"
  },
  "layers": [
    {
      "id": "唯一标识符",
      "feature_class": "要素类路径（如：C:/data.gdb/featureclass 或 C:/data.shp）",
      "visible": true,
      "renderer": {
        "type": "simple|unique_value|graduated_colors|classed",
        "field": "符号化字段名",
        "配置项": "...根据类型不同而不同..."
      },
      "labeling": {
        "enabled": true,
        "field": "标注字段名",
        "font": {
          "family": "SimSun（宋体）",
          "size": 12
        },
        "color": [0, 0, 0, 100],
        "halo": {
          "color": [255, 255, 255, 100],
          "size": 1
        }
      }
    }
  ],
  "map_elements": {
    "north_arrow": {
      "enabled": true,
      "position": "top_left|top_right"
    },
    "legend": {
      "enabled": true,
      "position": "bottom_left|bottom_right",
      "title": "图  例"
    },
    "scale_bar": {
      "enabled": true
    }
  }
}
```

### 符号系统类型

#### 1. 简单符号系统 (simple)

```json
{
  "renderer": {
    "type": "simple",
    "symbol": {
      "type": "polygon|line|point",
      "fill_color": [255, 200, 100, 80],
      "outline_color": [100, 100, 100, 100],
      "outline_width": 1
    }
  }
}
```

- **fill_color**: 填充色 [R, G, B, 透明度(0-100)]
- **outline_color**: 轮廓色 [R, G, B, 透明度(0-100)]
- **outline_width**: 轮廓粗细（像素）

#### 2. 唯一值符号系统 (unique_value)

```json
{
  "renderer": {
    "type": "unique_value",
    "field": "类别字段",
    "default_symbol": {
      "fill_color": [200, 200, 200, 80],
      "outline_color": [100, 100, 100, 100],
      "outline_width": 1
    },
    "classes": [
      {
        "value": "类别值1",
        "label": "图例显示名称1",
        "symbol": {
          "fill_color": [255, 0, 0, 80],
          "outline_color": [100, 100, 100, 100],
          "outline_width": 1
        }
      },
      {
        "value": "类别值2",
        "label": "图例显示名称2",
        "symbol": {
          "fill_color": [0, 255, 0, 80],
          "outline_color": [100, 100, 100, 100],
          "outline_width": 1
        }
      }
    ]
  }
}
```

#### 3. 分级符号系统 (graduated_colors)

```json
{
  "renderer": {
    "type": "graduated_colors",
    "field": "数值字段",
    "classification_method": "natural_breaks|equal_interval|quantile|standard_deviation",
    "class_count": 5,
    "color_scheme": {
      "colors": [
        [255, 255, 200, 80],
        [216, 204, 150, 80],
        [177, 153, 100, 80],
        [139, 102, 50, 80],
        [100, 50, 0, 80]
      ]
    },
    "outline_color": [100, 100, 100, 100],
    "outline_width": 1
  }
}
```

也可使用简化写法，由 MCP 按 `class_count` 自动插值：

```json
"color_scheme": {
  "start_color": [255, 255, 200, 80],
  "end_color": [100, 50, 0, 80]
}
```

- **classification_method**: 分级方法
  - natural_breaks: 自然断点法
  - equal_interval: 等间距法
  - quantile: 分位数法
  - standard_deviation: 标准差法
- **class_count**: 分级数量
- **color_scheme**: 颜色渐变方案

#### 4. 分类符号系统 (classed)

```json
{
  "renderer": {
    "type": "classed",
    "field": "数值字段",
    "classes": [
      {
        "label": "类别名称1",
        "expression": "字段名 <= 100",
        "symbol": {
          "fill_color": [255, 0, 0, 80],
          "outline_color": [100, 100, 100, 100],
          "outline_width": 1
        }
      },
      {
        "label": "类别名称2",
        "expression": "字段名 > 100 AND 字段名 <= 500",
        "symbol": {
          "fill_color": [255, 255, 0, 80],
          "outline_color": [100, 100, 100, 100],
          "outline_width": 1
        }
      }
    ]
  }
}
```

### 完整示例

```json
{
  "layout": {
    "title": "中国行政区划图",
    "output_path": "D:/output/china_map.png",
    "page_size": "A4",
    "orientation": "landscape"
  },
  "layers": [
    {
      "id": "provinces",
      "feature_class": "D:/GIS_Data/china.gdb/provinces",
      "visible": true,
      "renderer": {
        "type": "unique_value",
        "field": "REGION",
        "default_symbol": {
          "fill_color": [220, 220, 220, 80],
          "outline_color": [100, 100, 100, 100],
          "outline_width": 1
        },
        "classes": [
          {
            "value": "华北",
            "label": "华北地区",
            "symbol": {
              "fill_color": [255, 100, 100, 80],
              "outline_color": [80, 80, 80, 100],
              "outline_width": 1.5
            }
          },
          {
            "value": "华东",
            "label": "华东地区",
            "symbol": {
              "fill_color": [100, 255, 100, 80],
              "outline_color": [80, 80, 80, 100],
              "outline_width": 1.5
            }
          },
          {
            "value": "华南",
            "label": "华南地区",
            "symbol": {
              "fill_color": [100, 100, 255, 80],
              "outline_color": [80, 80, 80, 100],
              "outline_width": 1.5
            }
          }
        ]
      },
      "labeling": {
        "enabled": true,
        "field": "NAME",
        "font": {
          "family": "SimSun",
          "size": 14
        },
        "color": [0, 0, 0, 100],
        "halo": {
          "color": [255, 255, 255, 100],
          "size": 1.5
        }
      }
    }
  ],
  "map_elements": {
    "north_arrow": {
      "enabled": true,
      "position": "top_right"
    },
    "legend": {
      "enabled": true,
      "position": "bottom_left",
      "title": "图  例"
    },
    "scale_bar": {
      "enabled": true
    }
  }
}
```

## MCP工具列表

| 工具名称 | 描述 |
|---------|------|
| `create_map` | 统一入口：接收完整JSON配置，创建多图层地图并导出PNG |

## 安装与配置

### 环境要求

- Python 3.x
- ArcGIS Pro 3.x（提供arcpy环境）
- uv（Python包管理器）

### 安装步骤

```bash
cd <项目根目录>/scripts/color-style-mcp
uv init
uv add mcp fastmcp
```

### MCP配置方法

#### 方法1：Plugin配置（推荐）

在Claude Code插件配置中：

```json
{
  "mcpServers": {
    "color-style": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "mcp[cli]",
        "python",
        "${CLAUDE_PLUGIN_ROOT}/scripts/color-style-mcp/color_style_server.py"
      ],
      "cwd": "${CLAUDE_PLUGIN_ROOT}/scripts/color-style-mcp"
    }
  }
}
```

#### 方法2：.mcp.json配置

在用户配置目录的`.mcp.json`中（将路径替换为实际安装路径）：

```json
{
  "mcpServers": {
    "color-style": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "mcp[cli]",
        "python",
        "<实际路径>/scripts/color-style-mcp/color_style_server.py"
      ],
      "cwd": "<实际路径>/scripts/color-style-mcp"
    }
  }
}
```

#### 方法3：命令行配置

```bash
claude mcp add color-style -- uv run --with mcp[cli] python <实际路径>/scripts/color-style-mcp/color_style_server.py
```

### 运行调试

```bash
cd <项目根目录>/scripts/color-style-mcp
uv run python color_style_server.py
```

### 调用方法

通过MCP调用 `create_map` 工具，传入一个完整的JSON配置字符串：

```json
{
  "map_json": "{ \"layout\": { ... }, \"layers\": [ ... ], \"map_elements\": { ... } }"
}
```

完整JSON格式参考上方「JSON样式规范」及 `example.json` 文件。

### 使用chrome-devtools调试

1. 启动Claude Code并加载MCP服务器
2. 访问调试页面（地址见Claude Code控制台输出）
3. 输入MCP配置信息（command、args、env等）
4. 点击Connect → List Tools → 执行工具测试功能
5. 如有错误，查看连接日志排查问题
