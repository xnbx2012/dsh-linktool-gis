# CLAUDE.md — param-validate

GIS 工具参数形式校验 Hook。在 `PreToolUse` 阶段校验 `execute_gis_tool` 的参数是否完整和正确。

---

## 触发配置

```json
{
  "matcher": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
  "hooks": [
    { "type": "command", "command": "...param-validate/main.py" }
  ]
}
```

## 功能

1. **必填参数校验**：对照 `arcgis_tool_info.json` 检查必填参数是否齐全
2. **输入路径检查**：检查输入数据路径是否存在（支持 GDB 内要素类）
3. **未知参数警告**：不在工具参数列表中的参数会警告但不阻止

## 依赖

- `plugin/skills/tool-execute/scripts/arcgis_tool_info.json`：工具参数信息数据库
- 纯 Python，无 ArcPy 依赖，执行时间 <100ms

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 参数校验通过 |
| `2` | 缺少必填参数（阻止执行） |
| `1` | 脚本内部错误 |

## 调试

```bash
echo '{"tool_input":{"tool_name":"arcpy.analysis.Buffer","parameters":{"in_features":"test.shp"}}}' | uv run python main.py
```
