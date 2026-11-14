# CLAUDE.md — plugin/scripts/

本目录存放：
1. 自研 MCP 服务器（每个服务器一个子目录）
2. Hook 脚本（每组 Hook 一个子目录）

---

## 目录结构

```
scripts/
├── arcgis-mcp-server/        # ArcGIS 核心 MCP 服务器
├── color-style-mcp/          # 地图制图 MCP 服务器
├── knowledge-db-mcp/         # 向量知识库 MCP 服务器
├── modify-protect-hook/      # 文件保护 Hook（3个脚本）
└── gis-tool-log/             # GIS 执行日志 Hook
```

---

## arcgis-mcp-server

**文件**: `arcgis-mcp-server/main.py`
**启动**: `uv run --with mcp[cli] python main.py`
**依赖**: `pyproject.toml` + `uv.lock`（Python 3.14，MCP CLI）

### 工具列表

| 工具名 | 描述 | 关键参数 |
|--------|------|---------|
| `execute_gis_tool` | 执行任意 ArcGIS/ArcPy 工具 | `tool_name`（如 `arcpy.analysis.Buffer`）, `parameters`（参数字典） |
| `list_gdb_contents` | 列出 GDB 内所有内容 | `gdb_path` |
| `query_feature_attributes` | 查询要素类属性表 | `feature_path`, `sql_where`, `max_records` |
| `get_data_properties` | 获取数据元信息（坐标系/范围/类型/字段） | `data_path` |

### 运行机制

1. `find_py_interpreter()` 自动定位 ArcGIS Pro Python 解释器（`arcgispro-py3` 环境）
   - 检查顺序：环境变量 `ARCGIS_PRO_PATH` → 默认安装路径（C/D/E盘）→ AppData → 快捷方式 → 注册表
2. 通过 `subprocess.run([python_exe, "-c", script_code])` 在 ArcGIS Pro Python 环境中执行脚本
3. 脚本结果通过 stdout 以 JSON 格式返回
4. `execute_gis_tool` 超时设置：15分钟（900秒）

### 查询安全限制

- `query_feature_attributes` 服务端硬上限 `max_records ≤ 500`（默认 100），防止上下文爆炸
- 字符串字段值超过 500 字符自动截断，标注 `…[truncated]`

### 添加新工具

在 `main.py` 末尾添加：

```python
@mcp.tool()
async def my_new_tool(param1: str, param2: int = 10) -> str:
    """工具描述，会显示给 Claude 作为工具说明"""
    script = '''
import arcpy, json, sys
params = json.loads(sys.stdin.read())
# ... arcpy 代码 ...
print(json.dumps({"success": True, "result": ...}))
'''
    result = execute_arcpy_script(script, {"param1": param1, "param2": param2})
    return json.dumps(result, ensure_ascii=False, indent=2)
```

---

## color-style-mcp

**文件**: `color-style-mcp/color_style_server.py`
**启动**: `uv run --with mcp[cli] python color_style_server.py`
**cwd**: `${CLAUDE_PLUGIN_ROOT}/scripts/color-style-mcp`

### 工具列表

| 工具名 | 描述 |
|--------|------|
| `create_map` | 根据 JSON 样式配置制图，输出 300dpi PNG |

### JSON 样式规范

`create_map` 接收一个 JSON 字符串，格式：

```json
{
  "layout": {
    "title": "地图标题",
    "output_path": "D:/output/map.png",
    "page_size": "A4",
    "orientation": "landscape"
  },
  "layers": [
    {
      "id": "layer1",
      "feature_class": "D:/data.gdb/featureclass",
      "visible": true,
      "renderer": {
        "type": "simple|unique_value|graduated_colors|classed",
        "field": "符号化字段名（simple类型不需要）",
        ...
      },
      "labeling": {
        "enabled": true,
        "field": "标注字段名"
      }
    }
  ]
}
```

### 符号系统类型

- `simple`：SimpleRenderer，所有要素相同样式
- `unique_value`：UniqueValueRenderer，按字段唯一值分色
- `graduated_colors`：GraduatedColorsRenderer，按数值分级着色
- `classed`：先用字段归类，再用唯一值符号系统

详细规范见 `color-style-mcp/README.md`。

---

## knowledge-db-mcp

**文件**: `knowledge-db-mcp/main.py`
**启动**: `run.bat`（封装 uv 环境）
**数据库**: `knowledge-db-mcp/data.sqlite`（SQLite + sqlite_vec 向量扩展）
**嵌入模型**: SiliconFlow `Qwen/Qwen3-Embedding-4B`（512维）
**重排序模型**: `Qwen/Qwen3-Reranker-8B`
**API Key**: 通过环境变量 `SILICONFLOW_API_KEY` 注入

提供 GIS 案例知识库的向量语义检索，支持选址/评价/预测/网络分析/统计报表等类型的模板检索。

---

## modify-protect-hook

三个脚本分别处理不同类型的工具调用：

### `main.py` — 文件工具保护

**触发**: Edit, Write, Delete, Read, Glob, Grep, NotebookEdit

**规则**:
1. cwd 根目录下只允许 `01_DataBackup`、`02_WorkSpace`、`03_Result` 三个目录
2. cwd 外所有路径禁止任何操作
3. `01_DataBackup` 目录仅允许读取（Read/Glob/Grep），禁止写入
4. 禁止 Read 工具读取 `SKILL.md` 文件（必须用 Skill 工具加载）
5. `plugin/skills/` 目录下的路径放行（供 Skill 脚本使用）
6. 可通过 `protected_dirs.json` 配置额外受保护目录

### `bash_guard.py` — Bash 命令审查

**触发**: Bash

**规则**:
1. 禁止 Bash 中操作 cwd 外的目录
2. 禁止危险命令：format, dd, diskpart, fdisk 等
3. 禁止在 Bash 中 `import arcpy`（必须通过 arcgis-mcp-server）
4. 创建/写入类命令（mkdir, cp, echo >等）检查目标路径合法性
5. 基于 LLM 审查语义上危险的操作

### `gis.py` — GIS 工具输出路径保护

**触发**: `execute_gis_tool` MCP 工具

**规则**：与 `main.py` 相同的路径约束，但专门针对 GIS 工具的 `parameters` 中的输出路径字段

### `protected_dirs.json`

配置额外受保护目录（支持 `none` 完全禁止 / `read` 仅读）：

```json
{
  "protected_dirs": [
    { "path": "${CLAUDE_CONFIG_DIR}", "access": "none", "recursive": true },
    { "path": "C:/Windows",          "access": "none", "recursive": true },
    ...
  ]
}
```

支持 `${CLAUDE_CONFIG_DIR}`、`${USER_HOME}`、`${TEMP}` 等变量。

---

## gis-tool-log

**文件**: `gis-tool-log/record.py`
**触发**: PostToolUse on `execute_gis_tool`

将每次 GIS 工具调用的 `tool_input` 追加写入 `cwd/02_WorkSpace/gis-tool-logs.json`，便于后续报告生成和调试复现。

---

## 开发新 MCP 服务器

1. 在 `scripts/` 下新建目录
2. 参考 `arcgis-mcp-server/main.py` 的 `FastMCP` 模式编写服务器
3. 初始化 uv 环境：`uv init && uv add mcp[cli]`
4. 确保可用 `uv run --with mcp[cli] python main.py` 启动
5. 在 `plugin/.claude-plugin/plugin.json` 中注册（用 `${CLAUDE_PLUGIN_ROOT}` 作路径前缀）
6. 本地调试：执行`npx @modelcontextprotocol/inspector`启动调试器后，使用`agent-browser`访问 `http://localhost:6274` 的 MCP 调试界面验证工具
