# CLAUDE.md — color-style-mcp

ArcGIS 地图制图 MCP 服务器。接收 JSON 样式配置，通过 ArcPy 生成带标注、指北针、图例、比例尺的 300dpi PNG 地图。

**仅暴露 2 个 MCP 工具**：`create_map` 和 `get_basemap_names`。所有 ArcPy 操作均通过 subprocess 在 ArcGIS Pro Python 解释器中执行（脚本为 `new_draw_map.py`）。

---

## 项目结构

```
color-style-mcp/
├── color_style_server.py   # FastMCP 服务器入口（2 个工具：create_map + get_basemap_names）
├── new_draw_map.py         # 完整 ArcPy 制图脚本（subprocess 调用入口）
├── CLAUDE.md               # 本文件
├── SKILL.md                # Skill 定义（供 Claude 理解如何调用）
├── README.md               # JSON 样式规范说明
├── pyproject.toml          # uv 依赖配置（Python >=3.12, mcp>=1.26.0）
├── uv.lock                 # 锁定的依赖版本
├── example.json            # 样式配置示例
├── catagraphy_project/     # 制图用的 ArcGIS Pro 工程模板（非版本控制）
│   └── LinkTool.aprx       # 制图模板工程文件（禁止放入 git）
└── scripts/                # 辅助脚本
```

> 旧的 `arcpy_scripts.py` 已废弃，逻辑全部并入 `new_draw_map.py`。

---

## 工具列表

### 1. `create_map(map_json)`

根据 JSON 配置生成 PNG 地图。

- `map_json`: 完整 JSON 字符串，包含 `layout`, `layers`, `map_elements`
- 自动注入 `aprx_path`: 服务器目录下的 `catagraphy_project/LinkTool.aprx`

**内部流程**:
1. `color_style_server.py` 解析 JSON，调用 `validate_map_json()` 做 schema 校验
2. 注入 `aprx_path`
3. `execute_arcpy_script(_NEW_DRAW_MAP, params)` 通过 `find_py_interpreter()` 定位 ArcGIS Pro Python
4. `subprocess.run([python_exe, _NEW_DRAW_MAP], input=json)` 把 JSON 通过 stdin 喂给脚本
5. `new_draw_map.py` 的 `sys.stdin.isatty()` 判断为 False（管道模式），正确读取参数
6. 解析 stdout 最后一行 JSON 作为返回结果

### 2. `get_basemap_names()`

返回 `layout.basemap_name` 字段可用的底图名称列表（35 项，与 `new_draw_map.py` 内部 `_VALID_BASEMAPS` 保持一致）。

调用方将名称之一传入 `create_map` 的 `layout.basemap_name` 即可启用对应底图；传空串或不匹配名称时，`new_draw_map.py` 会自动移除已有底图图层。

---

## JSON 样式规范

```json
{
  "layout": {
    "title": "地图标题",
    "output_path": "D:/test/03_Result/map.png",
    "page_size": "A4",
    "orientation": "landscape",
    "basemap_name": "Imagery"
  },
  "layers": [
    {
      "id": "layer1",
      "feature_class": "D:/test/01_DataBackup/data.gdb/featureclass",
      "visible": true,
      "renderer": {
        "type": "simple|unique_value|graduated_colors|classed",
        "field": "符号化字段名",
        ...
      },
      "labeling": {
        "enabled": true,
        "field": "标注字段名"
      }
    }
  ],
  "map_elements": {
    "legend":     { "enabled": true, "position": "bottom_right", "title": "图  例" },
    "north_arrow":{ "enabled": true, "position": "top_right" },
    "scale_bar":  { "enabled": true, "position": "bottom_left" }
  }
}
```

### 四种符号系统

| 类型 | `type` 值 | ArcPy 类 | 适用场景 |
|------|-----------|---------|---------|
| 简单符号 | `simple` | `SimpleRenderer` | 单一图层，无分类 |
| 唯一值符号 | `unique_value` | `UniqueValueRenderer` | 按字段唯一值分色 |
| 分级符号 | `graduated_colors` | `GraduatedColorsRenderer` | 按数值范围分级着色 |
| 分类符号 | `classed` | 计算字段 + `UniqueValueRenderer` | 先归类再唯一值着色 |

详细 JSON 字段定义见 `README.md`。

---

## ArcGIS Pro Python 解释器定位

复用 `scripts/shared/find_arcpy.py` 中的 `find_py_interpreter()`，统一与 `arcgis-mcp-server` 的查找顺序：
1. 环境变量 `ARCGIS_PRO_PATH`
2. 默认安装路径（C:/D:/E: 盘 Program Files）
3. 用户 AppData 安装路径
4. 开始菜单快捷方式解析
5. Windows 注册表

定位失败时返回 `None`，`execute_arcpy_script()` 立即返回错误，不抛异常。

---

## 制图规范

- **输出分辨率**: 300dpi PNG
- **页面**: A4 横版（默认，可通过 layout.page_size/orientation 切换）
- **标注**: 宋体，白色轮廓，黑色字体，标注字段与符号化字段相同
- **指北针**: 布局左上角或右上角空白位置，不遮挡专题地图和标题
- **图例**: 左下角或右下角，紧贴地图框，标题为"图  例"
- **底图**: 由 `layout.basemap_name` 控制；空值/不匹配名称会移除已有底图

---

## 开发规范

### 修改制图脚本

直接编辑 `new_draw_map.py`。脚本结构（已固化）：

1. 打印启动提示 → `import arcpy`
2. 读取 stdin JSON（基于 `sys.stdin.isatty()` 判断：交互终端走 `_DEBUG_PARAMS`，管道走 stdin）
3. 创建工程 `aprx = arcpy.mp.ArcGISProject(aprx_path)` + `aprx.createMap("地图", "MAP")`
4. 遍历 `layers`：添加要素类 → 设置 `renderer`（simple/unique_value/graduated_colors/classed） → 设置 `labeling`
5. 创建布局 `aprx.create_layout()` → 创建地图框 `layout.createMapFrame()` → 设置相机范围
6. 设置底图（按 `layout.basemap_name` 与 `_VALID_BASEMAPS` 校验）
7. 添加标题、指北针、图例、比例尺
8. `layout.exportToPNG(output_path, resolution=300)`

### 本地调试

```bash
# 启动服务器（stdio transport）
cd plugin/scripts/color-style-mcp
uv run python color_style_server.py

# 在 Claude Code 中测试
cd test
claude --agent linktool-plugin:task-plan --plugin-dir ../plugin
```

### 直接调试 new_draw_map.py

```bash
# 调试模式（stdin 是 tty，走 _DEBUG_PARAMS）
uv run python new_draw_map.py

# 生产模式（从 stdin 喂 JSON）
echo '{"layout": {...}, "layers": [...]}' | uv run python new_draw_map.py
```

---

## 重要约束

1. **`.aprx` 工程文件**不纳入 Git 版本控制（通过 `.gitignore` 排除）
2. 制图脚本通过 `subprocess.run([arcgis_python, new_draw_map.py], input=json)` 在 ArcGIS Pro Python 环境中执行，**绝不在本地 Python 环境 import arcpy**
3. `output_path` 必须经过 modify-protect-hook 路径校验
4. JSON 配置中所有路径必须为绝对路径
5. **`new_draw_map.py` 的 `sys.stdin.isatty()` 必须保持原状**：调试时走 `_DEBUG_PARAMS`，MCP 调用时走 stdin，二者缺一不可