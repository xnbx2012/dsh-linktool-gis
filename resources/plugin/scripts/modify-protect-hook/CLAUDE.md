# CLAUDE.md — modify-protect-hook

文件操作保护 Hook 脚本组。在 `PreToolUse` 阶段拦截危险操作，防止 AI 对 cwd 外目录进行读写，防止误删系统文件，防止写入只读目录。

---

## 项目结构

```
modify-protect-hook/
├── main.py              # 文件工具保护 Hook（Edit/Write/Delete/Read/Glob/Grep/NotebookEdit）
├── bash_guard.py        # Bash 命令审查 Hook
├── gis.py               # GIS 工具输出路径保护 Hook（execute_gis_tool）
├── protected_dirs.json  # 额外受保护目录配置
└── CLAUDE.md            # 本文件
```

---

## Hook 触发配置

在 `plugin/hooks/hooks.json` 中注册：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|Delete|Read|Glob|Grep|NotebookEdit",
        "hooks": [{ "type": "command", "command": "...modify-protect-hook/main.py" }]
      },
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "...modify-protect-hook/bash_guard.py" }]
      },
      {
        "matcher": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
        "hooks": [{ "type": "command", "command": "...modify-protect-hook/gis.py" }]
      }
    ]
  }
}
```

---

## 退出码约定

| 退出码 | 含义 | 处理方式 |
|--------|------|---------|
| `0` | 允许 | Claude 正常执行工具 |
| `2` | 阻止 | Claude 收到错误提示，取消执行 |
| `1` | 脚本内部错误 | 意外错误，通常也按阻止处理 |

所有阻止信息必须输出到 **stderr**。

---

## main.py — 文件工具保护

**触发**: Edit, Write, Delete, Read, Glob, Grep, NotebookEdit

### 规则

1. **cwd 根目录白名单**:
   - 只允许 `01_DataBackup`、`02_WorkSpace`、`03_Result` 三个子目录
   - cwd 根目录下创建任何其他文件/文件夹均被拒绝

2. **cwd 外禁止**:
   - 禁止操作 cwd 以外的任何文件或目录
   - `plugin/skills/` 目录例外放行（供 Skill 脚本使用）

3. **只读目录**:
   - `01_DataBackup` 仅允许读取（Read/Glob/Grep）
   - 禁止对 `01_DataBackup` 执行 Write、Edit、Delete

4. **禁止 Read SKILL.md**:
   - 禁止 `Read` 工具读取任何 `SKILL.md` 文件
   - 应通过 `Skill` 工具加载技能

5. **受保护目录**:
   - 加载 `protected_dirs.json`，命中规则时按 `access` 字段拦截

### 多线程审查

`check_paths_parallel()` 使用 `ThreadPoolExecutor` 并行检查多个路径，最大 4 个 worker。

---

## bash_guard.py — Bash 命令审查

**触发**: Bash

### 规则

1. **cwd 外禁止**:
   - 审查文件操作类命令（ls, dir, cp, mv, rm, mkdir 等）
   - 禁止操作 cwd 外的文件和目录
   - 处理重定向符号（`>`, `>>`, `1>`, `2>`）的目标路径

2. **危险命令禁止**:
   - `format`, `diskpart`, `fdisk`, `mkfs`, `dd`, `fsck`, `chkdsk`
   - 任何格式化磁盘命令直接拒绝

3. **禁止通过 Bash 执行 arcpy**:
   - 审查 Bash 中执行的 Python 代码
   - 若含有 `import arcpy` 则拒绝，提示使用 arcgis-mcp-server

2. **cwd 外禁止**:
   - 禁止操作 cwd 以外的任何文件或目录
   - `plugin/skills/` 与 `plugin/bin/` 目录例外放行（供 Skill 脚本与 officecli 等插件内嵌二进制使用）
   - `/dev/null`、`/dev/zero` 等 Unix 特殊设备文件放行（用于重定向）
   - 写入真实块设备（`/dev/sda` 等）由 dangerous_patterns 覆盖，仍被拦截

3. **URL 误判修复**:
   - 路径提取时跳过包含 `://` 的字符串（避免 XML namespace URL、Windows 盘符误匹配 `s://` 等被识别为路径）

4. **只读目录**:
   - 禁止通过 Bash 向 `01_DataBackup` 写入任何内容

---

## gis.py — GIS 输出路径保护

**触发**: `execute_gis_tool` MCP 工具

### 规则

与 `main.py` 相同的路径约束，但专门针对 GIS 工具的输出路径：

1. 遍历 `tool_input.parameters` 中的输出键：`out_*`/`output_*`（arcpy）与五引擎统一键 `output`/`outputs`/`sink`/`destination`/`*_output`
2. 将字符串值识别为潜在路径（纯文件名与 URI 伪路径跳过）
3. 检查是否落在允许的目录范围内
4. 禁止输出到 `01_DataBackup`

---

## protected_dirs.json — 受保护目录配置

```json
{
  "protected_dirs": [
    {
      "path": "${CLAUDE_CONFIG_DIR}",
      "access": "none",
      "recursive": true,
      "description": "Claude 配置文件目录"
    },
    {
      "path": "${TEMP}",
      "access": "read",
      "recursive": true,
      "description": "临时目录仅允许读取"
    }
  ]
}
```

### 配置字段

| 字段 | 说明 |
|------|------|
| `path` | 受保护目录路径，支持变量 `${CLAUDE_CONFIG_DIR}`, `${USER_HOME}`, `${TEMP}` |
| `access` | `none` = 完全禁止；`read` = 仅允许读取 |
| `recursive` | `true` = 子目录也受保护；`false` = 仅当前目录 |
| `description` | 说明文字（用于错误提示） |

### 当前受保护目录

- Claude 配置目录（完全禁止）
- Windows 系统目录（`C:/Windows`, `C:/Program Files`, `C:/ProgramData`）
- Linux/macOS 系统目录（`/etc`, `/usr`, `/bin`, `/sbin`, `/System`）
- 临时目录（仅允许读取，禁止写入）

---

## 开发规范

### 修改 Hook 逻辑

1. 三个脚本共享相同的常量定义：`ALLOWED_CWD_SUBDIRS`, `READONLY_CWD_SUBDIRS`
2. 修改时需保持三个脚本的逻辑一致
3. 新增受保护目录优先通过 `protected_dirs.json` 配置，而非硬编码
4. 所有阻止信息必须包含具体的路径名和拒绝原因

### 调试 Hook

```bash
# 手动测试（模拟 Hook 事件输入）
echo '{"cwd":"D:/test","tool_name":"Write","tool_input":{"file_path":"D:/test/02_WorkSpace/test.txt"}}' | python main.py
echo '{"cwd":"D:/test","tool_name":"Bash","tool_input":{"command":"ls D:/test/02_WorkSpace"}}' | python bash_guard.py
```
