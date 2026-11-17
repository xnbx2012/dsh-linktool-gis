# CLAUDE.md — color-style-mcp

地图制图 MCP 服务器。接收 JSON 样式配置，生成带标注、指北针、图例、比例尺的 300dpi PNG 地图。

**双后端（对 MCP 工具名/参数规范/LLM 调用方式完全透明）**：
- **arcpy**：`new_draw_map.py` 在 ArcGIS Pro Python 解释器中执行（Windows，需授权安装）
- **qgis**：`qgis_draw_map.py` 在 QGIS 自带 Python（`python-qgis*.bat`）中执行；符号/标注/整饰要素转 PyQGIS 等价实现，底图按地图范围抓取 XYZ 瓦片拼贴（Esri 影像/地形/OSM）

**仅暴露 2 个 MCP 工具**：`create_map` 和 `get_basemap_names`。两者均为 subprocess 执行（stdin JSON 进、stdout 最后一行 JSON 出）。

---

## 项目结构

```
color-style-mcp/
├── color_style_server.py   # FastMCP 服务器入口（2 个工具 + 后端选择 select_backend）
├── new_draw_map.py         # ArcPy 制图脚本（ArcGIS Pro 解释器中执行）
├── qgis_draw_map.py        # QGIS 制图脚本（python-qgis*.bat 中执行，与 ArcPy 契约一致）
├── CLAUDE.md               # 本文件
├── SKILL.md                # Skill 定义（供 Claude 理解如何调用）
├── README.md               # JSON 样式规范说明
├── pyproject.toml          # uv 依赖配置（Python >=3.12, mcp>=1.26,<2）
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
- 自动按 `select_backend()` 选后端：设置页引擎开关（`LINKTOOL_ENGINE_SWITCHES` → engine-switches.json）中 ArcGIS Pro 开且解释器可用 → arcpy；否则 QGIS 开且 `python-qgis*.bat` 可用 → qgis；都不可用报明确错误
- arcpy 后端额外注入 `aprx_path`: 服务器目录下的 `catagraphy_project/LinkTool.aprx`
- 结果 dict 带 `backend` 字段标识实际执行后端；`warnings` 数组记录非致命问题（底图瓦片缺失等）

**内部流程**:
1. `color_style_server.py` 解析 JSON，调用 `validate_map_json()` 做 schema 校验
2. `select_backend()` 按引擎开关与环境分发
3. arcpy 后端：注入 `aprx_path` → `execute_arcpy_script(_NEW_DRAW_MAP, params)` 经 `find_py_interpreter()` 定位解释器
4. qgis 后端：`execute_qgis_script(_QGIS_DRAW_MAP, params)` 经 `qgis_engine.qgis_python_launcher()` 定位 `python-qgis*.bat`
5. 两者均 `subprocess.run([...], input=json)` 把 JSON 通过 stdin 喂给脚本（不传 env——显式构造环境块会破坏 arcpy 子进程；脚本内部自行 reconfigure UTF-8）
6. 脚本的 `sys.stdin.isatty()` 判断为 False（管道模式），正确读取参数
7. 解析 stdout 最后一行 `{` 开头的 JSON 行作为返回结果

### 2. `get_basemap_names()`

返回 `layout.basemap_name` 字段可用的底图名称列表（35 项，与脚本内底表保持一致），并带 `backend` 字段标识当前制图后端。

调用方将名称之一传入 `create_map` 的 `layout.basemap_name` 即可启用对应底图；传空串或不匹配名称时视为无底图。QGIS 后端将名称映射为 XYZ 瓦片（无同名瓦片时以 Topographic 近似并记 warning）。

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

## QGIS 后端（qgis_draw_map.py）

无 ArcGIS Pro 或其开关关闭时自动启用。JSON 契约与 ArcPy 后端完全一致，内部转 PyQGIS：

| ArcPy 概念 | QGIS 实现 |
|---|---|
| 符号系统（simple/unique_value/graduated_colors/classed） | `QgsSingleSymbolRenderer` / `QgsCategorizedSymbolRenderer`（缺省 classes 自动取 uniqueValues 配 12 色板）/ `QgsGraduatedSymbolRenderer`（Jenks/等间距/分位数/标准差，start_color→end_color 线性插值）/ CASE 表达式分类 |
| 标注（宋体+白晕） | `QgsPalLayerSettings` + `QgsTextBufferSettings`，Points 单位 |
| 底图 | **瓦片拼贴**：按最终地图范围选最高缩放级（瓦片 ≤8×8）同步抓 XYZ 瓦片，拼成 PNG+`.pgw` 世界文件（Web 墨卡托）挂为最底层栅格。不用内置 XYZ 图层——headless 下其瓦片下载器依赖 GUI 事件循环，全部重试失败（`_download_tile` 走 `QgsNetworkAccessManager` 同步抓取，兼容系统代理） |
| 指北针 | `QgsLayoutItemPicture` + 安装目录 `svg/arrows/NorthArrow_02.svg` |
| 比例尺 | `QgsLayoutItemScaleBar`，单位自适应（地理坐标用度，投影坐标按数据跨度选 m/km） |
| 图例 | `QgsLayoutItemLegend`，内容自适应尺寸；`setAutoUpdateModel(False)` 后在私有模型副本剔除底图节点（底图不入图例） |
| 地图 CRS | 锚定首个专题图层坐标系（ArcPy 语义），底图在线重投影 |

QGIS 启动器定位复用 `scripts/shared/qgis_engine.py` 的 `qgis_python_launcher()`（Windows 找 `bin/python-qgis*.bat`，POSIX 用 PATH 上的 python3）。

**布局 API 注意**（3.44 LTR 实测）：
- `attemptMove` 的 PagePosition 枚举参数部分项不生效——整饰要素一律按角位**显式计算左上角**后普通 `attemptMove` 落位
- categorized 渲染器 3 参构造未导出（TypeError→2 参回退）；`QgsClassificationStandardDeviation`（非 StdDev）；`QgsPrintLayout`（`addLayout` 需 PrintLayout 实例）
- 图层树 index 0 是**最顶层**：底图要 `addChildNode` 追加到末尾才是最底层

---

## 制图规范

- **输出分辨率**: 300dpi PNG
- **页面**: A4 横版（默认，可通过 layout.page_size/orientation 切换）
- **标注**: 宋体，白色轮廓，黑色字体，标注字段与符号化字段相同
- **指北针**: 布局左上角或右上角空白位置，不遮挡专题地图和标题
- **图例**: 左下角或右下角，紧贴地图框，标题为"图  例"
- **底图**: 由 `layout.basemap_name` 控制；空值/不匹配名称视为无底图。arcpy 后端用同名 Esri 底图；qgis 后端抓同名/近似 XYZ 瓦片拼贴

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

### 直接调试 qgis_draw_map.py

```bash
# 经 QGIS 自带 Python 启动器执行（stdin 喂 JSON）
echo '{"layout": {...}, "layers": [...]}' | "C:/Program Files/QGIS 3.x/bin/python-qgis-ltr.bat" qgis_draw_map.py
```

两个脚本的 stdout 最后一行都是 JSON 结果（`{success, output_path, message, added_layers_count, total_layers_count, warnings?}`）。

---

## 重要约束

1. **`.aprx` 工程文件**不纳入 Git 版本控制（通过 `.gitignore` 排除）
2. 制图脚本一律 subprocess 执行（arcpy 经 ArcGIS Pro 解释器、qgis 经 `python-qgis*.bat`），**绝不在 MCP 服务器进程内 import arcpy/PyQGIS**
3. `output_path` 必须经过 modify-protect-hook 路径校验
4. JSON 配置中所有路径必须为绝对路径
5. **两个脚本的 `sys.stdin.isatty()` 必须保持原状**：调试时走 `_DEBUG_PARAMS`，MCP 调用时走 stdin，二者缺一不可