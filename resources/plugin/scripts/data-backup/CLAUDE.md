# CLAUDE.md — data-backup

数据备份保护 Hook。在 `PreToolUse` 阶段检测破坏性 GIS 工具，自动备份只读数据。

---

## 触发配置

```json
{
  "matcher": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
  "hooks": [
    { "type": "command", "command": "...data-backup/main.py" }
  ]
}
```

## 功能

1. **破坏性工具识别**：通过工具名和参数判断是否为原地修改工具
2. **自动数据备份**：检测到操作 `01_DataBackup` 中的数据时，自动复制到 `02_WorkSpace`
3. **参数自动重定向**：通过 `updatedInput` 将工具参数中的路径从只读目录重定向到副本

## 破坏性工具判断逻辑

- 无 `out_*` 输出参数的工具 → 可能是破坏性工具
- 已知破坏性工具列表：`CalculateField`, `AddField`, `DeleteField`, `DeleteFeatures` 等
- `arcpy.edit.*` 模块下的所有工具
- 有输出路径参数的工具视为安全（创建新数据）

## 依赖

- `shared/find_arcpy.py`：ArcPy 解释器定位（仅在需要复制时调用）
- ArcPy 调用延迟：~5-15s（仅在破坏性操作 + 只读数据时触发）

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 安全工具放行，或已成功备份并返回 updatedInput |
| `2` | 备份失败（阻止操作，提示手动复制） |
| `1` | 脚本内部错误 |

## 官方文档关键能力

此 Hook 使用 `hookSpecificOutput.updatedInput` 修改工具参数，这是 PreToolUse 的高级功能。
参考：https://code.claude.com/docs/zh-CN/hooks
