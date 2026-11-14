# CLAUDE.md — gis-tool-log

GIS 工具执行日志 Hook 脚本。在 `PostToolUse` 阶段自动记录每次 `execute_gis_tool` 的调用参数，便于后续报告生成和调试复现。

---

## 项目结构

```
gis-tool-log/
├── record.py             # 原始日志记录 Hook（已被 enhanced_record.py 替代）
├── enhanced_record.py    # 增强版日志记录 Hook（当前使用）
└── CLAUDE.md             # 本文件
```

---

## Hook 触发配置

在 `plugin/hooks/hooks.json` 中注册（当前使用增强版）：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python \"${CLAUDE_PLUGIN_ROOT}/scripts/gis-tool-log/enhanced_record.py\""
          }
        ]
      }
    ]
  }
}
```

---

## enhanced_record.py（增强版，当前使用）

### 新增功能（相比 record.py）

- **执行 ID**：每次调用生成唯一 UUID
- **时间戳**：记录执行时间
- **路径分离**：`input_paths` 和 `output_paths` 独立提取
- **参数摘要**：`parameters_summary` 排除路径字段，保留业务参数
- **上下文注入**：通过 `additionalContext` 输出一行压缩摘要到 Claude 上下文

### 日志文件格式

```json
[
  {
    "execution_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-06-02T14:30:00.000+08:00",
    "tool_name": "arcpy.analysis.Buffer",
    "parameters": { "in_features": "...", "out_feature_class": "...", "buffer_distance_or_field": "100 Meters" },
    "input_paths": ["D:/test/01_DataBackup/roads.shp"],
    "output_paths": ["D:/test/02_WorkSpace/roads_buffer.shp"],
    "parameters_summary": { "buffer_distance_or_field": "100 Meters" }
  }
]
```

### additionalContext 输出

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "[GIS-LOG] #550e8400 Buffer | 输入: roads → roads_buffer"
  }
}
```

---

## record.py（原始版本，保留备用）

记录 `tool_input` 到 `gis-tool-logs.json`，无时间戳和 ID。已被 `enhanced_record.py` 替代。

### 输入

通过 stdin 接收 JSON 格式的 hook 事件，示例如下（非真实值）：

```json
{
  "cwd": "D:/test",
  "tool_name": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
  "tool_input": {
    "tool_name": "arcpy.analysis.Buffer",
    "parameters": {
      "in_features": "...",
      "out_feature_class": "...",
      "buffer_distance_or_field": "..."
    }
  }
}
```

### 输出

将 `tool_input` 追加写入 `cwd/02_WorkSpace/gis-tool-logs.json`。

**日志文件格式**:
```json
[
  {
    "tool_name": "arcpy.analysis.Buffer",
    "parameters": {
      "in_features": "D:/test/01_DataBackup/roads.shp",
      "out_feature_class": "D:/test/02_WorkSpace/roads_buffer.shp",
      "buffer_distance_or_field": "100 Meters"
    }
  },
  { ... },
  { ... }
]
```

### 逻辑流程

1. 读取 stdin → 解析 JSON hook 事件
2. `cwd` 路径中的 `\\` 替换为 `/` 以统一格式
3. 构建日志文件路径：`{cwd}/02_WorkSpace/gis-tool-logs.json`
4. 如文件不存在，创建空的 JSON 数组 `[]`
5. 读取现有日志，追加新条目
6. 写回文件（JSON 格式，`ensure_ascii=False`，缩进 4）

---

## 用途

| 场景 | 说明 |
|------|------|
| **过程报告生成** | `@report` Agent 的 `tool-report` Skill 读取此日志，还原完整的 GIS 操作步骤 |
| **调试复现** | 通过日志中的 `tool_name` + `parameters` 可精确复现工具调用 |
| **质量审计** | 审查执行了什么工具、用了什么参数、输出了什么路径 |

---

## 开发规范

### 修改日志格式

如需要增加更多字段（如时间戳、执行结果、返回值），在 `record.py` 中修改：

```python
log_entry = {
    "tool_name": tool_input.get("tool_name"),
    "parameters": tool_input.get("parameters"),
    # "timestamp": datetime.now().isoformat(),
    # "result": tool_output,
}
```

**注意**: `record.py` 是 `PostToolUse` Hook，此时工具**已经执行完毕**，但 Hook 输入中**不包含**工具的返回结果。如需记录结果，需额外处理。

### 日志文件位置

- 固定路径：`{cwd}/02_WorkSpace/gis-tool-logs.json`
- `modify-protect-hook` 已放行 `02_WorkSpace` 目录的写入操作

### 调试

```bash
# 手动测试
echo '{"cwd":"D:/test","tool_input":{"tool_name":"arcpy.analysis.Buffer","parameters":{...}}}' | python record.py
```
