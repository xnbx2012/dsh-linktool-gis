# CLAUDE.md — result-validate

结果验证 Hook（替代 result-confirm skill）。在 `PostToolUse` 阶段自动验证 GIS 工具输出数据的属性和几何正确性。

---

## 触发配置

```json
{
  "matcher": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
  "hooks": [
    { "type": "command", "command": "...result-validate/main.py" }
  ]
}
```

## 功能

### 属性检验（Hook 4）
- 统计每个字段的空值率，>80% 时警告
- 统计每个字段的零值率，>95% 时警告
- 检查要素总数，0 要素时严重警告

### 几何验证（Hook 5）
- 坐标系一致性：输出 CRS 是否与输入一致（非 Project 工具时）
- 范围合理性：输出范围是否极端扩大/缩小（>10 倍警告）
- 几何类型：输出 shapeType 是否符合预期
- 栅格属性：尺寸、波段数、像元大小

### 输出方式
- 验证报告通过 `additionalContext` 注入 Claude 上下文
- 严重警告（🔴 标记）同时输出到 stderr

## 依赖

- `shared/find_arcpy.py`：ArcPy 解释器定位
- ArcPy 调用延迟：~5-15s（每次 execute_gis_tool 都会触发）

## 验证阈值（config.json）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `null_warning_threshold` | 0.8 | 空值率警告阈值 |
| `zero_warning_threshold` | 0.95 | 零值率警告阈值 |
| `extent_ratio_threshold` | 10.0 | 范围变化倍数警告阈值 |
| `max_sample_records` | 1000 | 最大采样记录数 |

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 始终放行（PostToolUse 不阻止） |
| `1` | 脚本内部错误 |
