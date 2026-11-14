# CLAUDE.md — plugin/

本文件为 Claude Code 提供 `plugin/` 目录的详细结构与开发规范。plugin 是整个项目的可发布单元，最终以压缩包形式分发给用户。

---

## 目录概览

```
plugin/
├── .claude-plugin/
│   └── plugin.json          # 插件声明（name、version、mcpServers 配置）
├── agents/                  # 4个 Agent 的 Markdown 定义文件
├── hooks/
│   └── hooks.json           # Hook 事件绑定配置
├── skills/                  # 技能库（每个子目录 = 一个 Skill）
├── scripts/                 # MCP 服务器 & Hook 脚本
└── bin/
    └── officecli.exe        # 内嵌 Office CLI 二进制
```

---

## plugin.json 配置规范

文件路径：`plugin/.claude-plugin/plugin.json`

### MCP 服务器配置示例

```json
"my-mcp-server": {
  "command": "uv",
  "args": ["run", "--with", "mcp[cli]", "python", "${CLAUDE_PLUGIN_ROOT}/scripts/my-mcp-server/main.py"],
  "cwd": "${CLAUDE_PLUGIN_ROOT}/scripts/my-mcp-server"
}
```

- 路径**必须**使用 `${CLAUDE_PLUGIN_ROOT}` 代替 plugin 目录的绝对路径，以保证可迁移性
- `uv run` 启动的服务器需在脚本目录下维护 `pyproject.toml` 和 `uv.lock`
- `npx` 启动的服务器直接指定包名，无需本地代码

### 当前 MCP 服务器列表

| 配置键 | 启动命令 | 代码位置 |
|--------|---------|---------|
| `arcgis-mcp-server` | `uv run python` | `scripts/arcgis-mcp-server/main.py` |
| `color-style` | `uv run python` | `scripts/color-style-mcp/color_style_server.py` |
| `knowledge-db` | `.bat` 脚本 | `scripts/knowledge-db-mcp/run.bat` |
| `bing-search` | `npx bing-cn-mcp` | — |
| `amap-maps` | `npx @amap/amap-maps-mcp-server` | — |
| `pdf-reader-mcp` | `npx mcp-pdf` | — |

---

## hooks.json 配置规范

文件路径：`plugin/hooks/hooks.json`

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "ToolName1|ToolName2",
        "hooks": [{ "type": "command", "command": "uv run python \"${CLAUDE_PLUGIN_ROOT}/scripts/.../hook.py\"" }]
      }
    ],
    "PostToolUse": [...]
  }
}
```

- `matcher` 支持 `|` 分隔的工具名或 MCP 工具的完整标识（如 `mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool`）
- Hook 脚本通过 stdin 接收 JSON 格式的 hook 事件（含 `cwd`、`tool_name`、`tool_input` 等字段）
- 退出码：`0` = 允许，`2` = 阻止，`1` = 脚本内部错误

### 当前 Hook 列表

| 事件 | 匹配工具 | 脚本 | 作用 |
|------|---------|------|------|
| PreToolUse | Edit/Write/Delete/Read/Glob/Grep/NotebookEdit | `modify-protect-hook/main.py` | 文件路径白名单校验 |
| PreToolUse | Bash | `modify-protect-hook/bash_guard.py` | 危险 Bash 命令拦截 |
| PreToolUse | `execute_gis_tool` | `modify-protect-hook/gis.py` | GIS 输出路径校验 |
| PostToolUse | `execute_gis_tool` | `gis-tool-log/record.py` | 记录执行日志 |
| PostToolUse | `execute_gis_tool` | `gis-data-preview/scripts/visualize.py auto-push` | 自动可视化推送 |

---

## 文件修改指南

### 新增 MCP 服务器

1. 在 `scripts/` 下新建目录，例如 `scripts/my-mcp/`
2. 在目录内放入 `main.py`（或 `server.py`）、`pyproject.toml`、`uv.lock`
3. 在 `plugin.json` 的 `mcpServers` 中添加配置（用 `${CLAUDE_PLUGIN_ROOT}` 作路径前缀）

### 新增 Skill

1. 在 `skills/` 下新建目录，例如 `skills/my-skill/`
2. 在目录内放入 `SKILL.md`（必需）以及相关脚本或数据文件
3. 在需要使用该 Skill 的 Agent frontmatter 中声明 `skills: [my-skill]`

### 修改 Agent

直接编辑 `agents/` 中对应的 Markdown 文件，frontmatter 控制模型、工具权限等参数。

### 新增 Hook

1. 在 `scripts/` 的对应子目录中编写 Hook 脚本
2. 在 `hooks/hooks.json` 中添加触发配置

---

## 路径约定

- **skills 目录免于 Hook 路径拦截**：modify-protect-hook 会对 `plugin/skills/` 路径放行，以允许 Skill 脚本的正常读写
- **禁止在 plugin/ 目录内存放测试数据**：测试用文件统一放到仓库根目录 `test/` 下
- **禁止在 plugin/ 目录内存放 ArcGIS Pro 工程文件**（`.aprx`）

## 参考资料

plugin及plugin内各组件的编写，参考以下资料，以这些官方资料为准：

- 创建插件的步骤指南：`https://code.claude.com/docs/zh-CN/plugins`
- 详细的配置项以Plugins参考为准：`https://code.claude.com/docs/zh-CN/plugins-reference`