# CLAUDE.md — plugin/agents/

Agent 定义文件目录。每个 `.md` 文件对应一个 Claude Code Agent，使用 YAML frontmatter + 系统提示词。

## Agent 索引

| Agent | 模型 | 核心职责 | Skill |
|-------|------|---------|-------|
| `@question-classify` | haiku | 数据摸底委派 + 问题三分类路由 | question-classify |
| `@task-plan` | opus | 完整 GIS 任务规划 + 生成全流程 Workflow 脚本 | gis-task-plan, data-doubt-check, task-data-manage, workflow-dsl |
| `@gis-tool` | sonnet | 单步原子 ArcGIS 操作（buffer/clip/intersect 等） | param-confirm, tool-execute, tool-retry, result-confirm |
| `@data-retrieval` | sonnet | 快速数据摸底（只读元数据查询），≤4 工具调用 | data-retrieval |
| `@gis-data-visualisation` | — | GeoJSON 转换 + Leaflet 网页推送 + color-style 专题图 | gis-data-preview, map-image-generate |
| `@report` | sonnet | 过程报告 / 标准化评价报告 Word 生成 | tool-report, conclusion-report, officecli |

## 核心规则

- **不新增 Agent**，修改直接编辑对应 `.md` 文件
- 完整复杂 GIS 任务必须由单一 Workflow 主控（Prepare / Process / Analyze / Deliver / Verify），禁止多短 Workflow 串联
- 总共最多 2 次 Workflow 调用：原始执行 1 次 + Edit 原脚本后 resume 1 次
- `@task-plan` 只做规划，不直接执行 `execute_gis_tool`
- `@gis-tool` 只做原子操作，禁止用 Python 替代 MCP 工具调用
- `tools` 最小权限原则，Skill 名与 `plugin/skills/` 子目录匹配
