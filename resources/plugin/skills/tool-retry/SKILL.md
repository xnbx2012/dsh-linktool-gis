---
name: tool-retry
description: 诊断并修复 ArcGIS 工具执行失败的错误。仅限 gis-tool Agent 使用。
allowed-tools: bing-search, memory-server
agent: gis-tool
context: fork
---

当工具执行失败或结果核验不通过时，按以下步骤排查修复。

> 配套文件：同目录 `root-causes.md` 提供错误码速查表与字段规范化规则。

# 步骤

## 1. 查 memory-server

进入排查前第一步：

1. **规范化键**：
   - `tool_name`：ArcGIS 全名 `工具箱.工具`（如 `analysis.Buffer`），参见 `root-causes.md` §2
   - `error_code`：6 位纯数字（去 `ERROR ` 前缀，如 `000725`）
2. **检索**：
   - 已知错误码 → `read_tool_error_memory(tool_name, error_code, top_k=3)`
   - 仅知工具 → `read_tool_error_memory(tool_name)`
3. **采用**：
   - 命中且方案适用 → 套用 `fix_approach` 修正，调 `/tool-execute` 重试，跳过联网搜索
   - 未命中或不适用 → 继续步骤 2–4

## 2. 识别错误

从错误日志提取：工具名称、错误代码、报错关键词。对照 `root-causes.md` §1 错误码速查表确认含义。

## 3. 搜索解决方案

用 `bing-search` 依次搜索：
- `site:pro.arcgis.com <报错关键词>`
- `site:pro.arcgis.com <工具名称>`
- `site:pro.arcgis.com <错误代码>`

## 4. 定根因并修复

结合搜索结果与本次上下文，定出精准根因（写清"这一次为什么错"）：
- 参数值是否正确
- 路径是否有效（中文字符、不存在、权限）
- 工具名是否准确
- 几何/坐标系是否兼容

修正后调用 `/tool-execute` 重试。

## 5. 确认结果

重试成功后调用 `/result-confirm` 验收。

## 6. 生成待沉淀记录

修复成功后，生成待沉淀记录带回 `gis-tool` Agent（本 Skill 不直接写库）：

| 字段 | 说明 |
|------|------|
| `tool_name` | ArcGIS 全名，如 `analysis.Buffer` |
| `error_code` | 6 位纯数字，如 `000725` |
| `error_cause` | 精准根因，如「输出名与现有要素类同名」 |
| `fix_approach` | 生效修正，如「追加 `_v2` 后缀后重新执行」 |

### 写入门控

- ✅ 写：有 6 位真实错误码 + 根因明确 + 修正生效 + 最终验收通过
- ❌ 不写：许可/扩展/架构问题；视觉核验 FAIL（无真实错误码）；最终验收未通过

> `gis-tool` Agent 在 `/result-confirm` 全部 PASS 后，才调用 `write_tool_error_memory` 写入。
## plan0701 边界

- 本 Skill 只处理 ArcGIS 工具参数、工具执行和结果异常的重试。
- Workflow 子 Agent 空返回、非结构化返回或短暂异常由 Workflow 的 `runAgentWithRetry()` 原地重试处理，最多 5 次；不要把 Agent 异常误写为 ArcGIS 工具参数错误。
