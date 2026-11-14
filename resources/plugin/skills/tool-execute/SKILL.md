---
name: tool-execute
description: 执行 ArcGIS 空间分析工具的完整流程。仅限 gis-tool Agent 使用。
allowed-tools: arcgis-mcp-server, bing-search
agent: gis-tool
context: fork
---

执行 ArcGIS 工具：$ARGUMENTS

# 步骤

0. **环境自检（强制）**
   执行前，调用一次 `execute_gis_tool`（可用最轻量的工具如 `arcpy.management.ListFields` 或直接用本合同工具）。
   - 调用成功 → 继续步骤 1
   - 返回"工具不存在"类错误 → 这是环境配置问题，立即返回 `{status: ENV_ERROR, detail: ...}`
   - 返回参数错误 → 工具可用，按错误修正参数即可
   禁止：基于"工具列表中没有"的判断而放弃。

1. **查工具标识**
   根据 $ARGUMENTS 确定搜索关键词，调用 `uv run python ./scripts/search_tool.py <关键词>` 获取工具唯一标识码（如 `arcpy.analysis.Buffer`）。一个关键词找不到可用多个关键词重试。

2. **查工具文档**
   用 `bing-search` 搜索 `site:pro.arcgis.com <工具名称>`，提取参数要求与约束条件。

3. **校验参数**
   检查参数是否完整且符合文档。不符合则调用 `/param-confirm` 向用户确认。

4. **执行工具**
   调用 `execute_gis_tool`，传入标识码和参数。输出路径规则：
   - 过程数据 → `02_WorkSpace/`（无 GDB 时先建一个）
   - 结果数据 → `03_Result/`（无 GDB 时先建一个）
   - 禁止输出到 `01_DataBackup/`

5. **处理结果**
   - 成功 → 调用 `/result-confirm` 验收
   - 失败 → 调用 `/tool-retry` 修复重试

# 栅格提取注意事项

执行 `ZonalStatisticsAsTable` + `UpdateCursor` 模式时：
- `zone_field` 必须用唯一标识字段（如 OBJECTID）
- `ignore_nodata` 设为 `DATA`
- `statistics_type` 设为 `MEAN`
- `UpdateCursor` 必须用 `zone_field` 值匹配临时表与目标要素类

## 反模式（严禁）
严禁用 Bash 执行 `uv run python`、`python -c`、`arcpy.xxx`
严禁用 Bash 写临时 .py 脚本绕过 MCP
严禁因为"MCP 工具慢/不可用"而改用 Bash
→ 以上行为会被 bash_guard 拦截，且视为执行失败。
→ 唯一合法的 GIS 操作方式：execute_gis_tool MCP 工具。
