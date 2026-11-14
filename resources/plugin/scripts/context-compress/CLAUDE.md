# CLAUDE.md — context-compress

上下文压缩 Hook。在 `PostCompact` 阶段重新注入 GIS 操作历史摘要，在 `PostToolUse` 阶段注入单行压缩摘要。

---

## 触发配置

```json
{
  "PostCompact": [
    {
      "matcher": "auto",
      "hooks": [
        { "type": "command", "command": "...context-compress/main.py" }
      ]
    }
  ]
}
```

## 功能

1. **PostCompact**：上下文压缩后，读取 `02_WorkSpace/gis-tool-logs.json`，生成压缩的操作历史摘要，通过 `additionalContext` 重新注入
2. **PostToolUse**（由 `enhanced_record.py` 处理）：每次 GIS 工具执行后注入一行摘要

## 摘要格式

PostCompact 注入格式：
```
[GIS 操作历史摘要]
#1 14:30:00 Buffer ← roads → roads_buffer
#2 14:31:15 Clip ← roads_buffer, study_area → roads_clipped
```

PostToolUse 注入格式：
```
[GIS-LOG] #550e8400 Buffer | 输入: roads → roads_buffer
```

## 依赖

- 纯 Python，无 ArcPy 依赖
- 读取 `02_WorkSpace/gis-tool-logs.json`

## 官方文档关键能力

- `additionalContext`：通过 `hookSpecificOutput.additionalContext` 注入文本到 Claude 上下文
- `PostCompact`：上下文压缩后触发的事件
- 参考：https://code.claude.com/docs/zh-CN/hooks
