# CLAUDE.md — plugin/skills/

本目录存放所有 Skill 定义。每个子目录 = 一个 Skill，主文件为 `SKILL.md`。

---

## Skill 目录结构

```
skills/
├── gis-task-plan/         # 任务规划完整流程（仅 @task-plan 使用）
├── param-confirm/         # ArcGIS 参数核查（仅 @gis-tool 使用）
├── tool-execute/          # ArcGIS 工具执行（仅 @gis-tool 使用）
├── result-confirm/        # 执行结果核查（仅 @gis-tool 使用）
├── tool-retry/            # 错误修复与重试（仅 @gis-tool 使用）
├── data-retrieval/        # 数据检索与元数据探索（仅 @data-retrieval 使用）
├── gis-data-preview/      # GIS数据网页可视化（@gis-data-visualisation 使用）
├── officecli/             # Office文档生成（@report 使用）
├── report-generate/       # 标准化评价报告（@report 使用）
├── tool-report/           # GIS过程报告（@report 使用）
├── conclusion-report/     # 数据分析与报告攥写专家（@report 使用）
├── data-analyzer/         # 数据统计分析核心（@report 使用）
├── map-image-generate/    # 地图制图（@gis-data-visualisation 使用）
└── map-beautify-skills/   # 地图美化技能集
    └── beautify-routing/  # 地图美化路由（@gis-data-visualisation 使用）
```

---

## SKILL.md Frontmatter 规范

```yaml
---
name: skill-name                    # Skill 唯一标识（Agent frontmatter 中引用的名称）
description: "..."                  # Skill 说明（供 Claude 决定何时调用）
agent: agent_name                   # 限定只有哪个 Agent 可调用（可选）
context: fork                       # 上下文模式：fork = 独立上下文（可选）
allowed-tools: tool1, tool2         # Skill 内允许使用的工具（可选）
argument-hint: "..."                # 调用时的参数提示（可选）
---
```

---

## 当前 Skill 详情

### `gis-task-plan` — GIS 任务规划
- **name**: `gis-task-plan`
- **仅限**: `@task-plan` Agent
- **用途**: 完整的 8 阶段 GIS 任务规划工作流（数据探索 → 需求解读 → 任务分解 → 计划展示 → 工具执行 → 结果检查 → 后处理 → 收尾）
- **调用方式**: `/gis-task-plan` 或 Agent skill 声明中的 `gis-task-plan`
- **注意**: 任务规划文档固定写入 `02_WorkSpace/task_plan.md`

### `param-confirm` — 参数核查
- **name**: `param-confirm`
- **仅限**: `@gis-tool` Agent
- **用途**: 查询 ArcGIS Pro 官方文档，提取必填参数，与用户输入比对，补全缺失参数
- **工具**: `bing-search`（搜索 `site:pro.arcgis.com <工具名称>`）

### `tool-execute` — 工具执行
- **name**: `tool-execute`
- **仅限**: `@gis-tool` Agent
- **用途**: 完整的 ArcGIS 工具执行流程
- **流程**: 
  1. 调用 `scripts/search_tool.py` 获取工具唯一标识码（如 `arcpy.analysis.Buffer`）
  2. 查询工具文档
  3. 调用 arcgis-mcp-server `execute_gis_tool`
  4. 失败 → `/tool-retry`；成功 → `/result-confirm`
- **辅助脚本**: `tool-execute/scripts/search_tool.py`（本地工具标识码搜索）

### `result-confirm` — 结果核查
- **name**: `result-confirm`
- **仅限**: `@gis-tool` Agent
- **用途**: 通过 arcgis-mcp-server 验证工具输出：检查数据生成 → 验证属性（坐标系/范围/要素数）→ 抽样验证（≤10条示例）→ 返回结果摘要

### `tool-retry` — 错误重试
- **name**: `tool-retry`
- **仅限**: `@gis-tool` Agent
- **用途**: 诊断 ArcGIS 工具错误，搜索解决方案，修正参数后重试（最多3次）
- **常见错误处理**:
  - 000732：数据集不存在 → 检查路径/权限/格式
  - 000622：执行失败 → 检查几何类型/坐标系
  - 000725：输出已存在 → 更换输出名称重试
  - 许可错误 → 记录并提供替代方案

### `data-retrieval` — 快速数据摸底（任务分流前置）
- **name**: `data-retrieval`
- **仅限**: `@data-retrieval` Agent
- **用途**: 快速确认数据可用性，输出轻量数据速览卡片供任务分流决策
- **工作流**:
  1. **数据实体提取**：分析用户文本，识别数据路径、图层名、字段名
  2. **快速元数据**：调用 `list_gdb_contents`/`get_data_properties`（仅用户提及的数据，不全量探索）
  3. **输出数据速览卡片**：轻量摘要，直接返回，不写文件
- **约束**:
  - 工具调用 ≤ 4 次，maxTurns ≤ 8
  - 禁止调用 `query_feature_attributes`、`search_knowledge`（后续阶段的事）
  - 禁止联网（WebSearch/WebFetch）
  - 不写文件，不生成 data_profile.md
- **输出**: 数据速览卡片（直接返回，不写文件）

### `gis-data-preview` — GIS 网页可视化
- **name**: `gis-data-preview`
- **仅限**: `@gis-data-visualisation` Agent
- **核心脚本**: `gis-data-preview/scripts/visualize.py`
- **后端**: `gis-data-preview/scripts/backend/`（FastAPI + Uvicorn，端口 3003）
- **底图**: 高德地图（GCJ-02 坐标系）
- **CLI 命令**:
  ```bash
  python visualize.py start                    # 启动服务
  python visualize.py stop                     # 停止服务
  python visualize.py push --path <文件> --name <图层名>  # 推送图层
  python visualize.py auto-push                # PostToolUse Hook 自动推送
  ```
- **符号系统**: simple（简单）/ unique（唯一值）/ graduated（分级）
- **坐标转换**: 非 GeoJSON 格式自动转换；`北京54/CGCS2000 → WGS84 → GCJ-02`

### `officecli` — Office 文档生成
- **name**: `officecli`
- **仅限**: `@report` Agent
- **二进制**: `plugin/bin/officecli.exe`（随插件分发，无需安装）
- **子 Skill**: `officecli-docx`（Word 文档）、`officecli-xlsx`（Excel 表格）
- **能力**: 创建、编辑、分析 .docx/.xlsx/.pptx 文件
- **检查脚本**: `officecli/scripts/check_officecli.py`（定位二进制路径）

### `report-generate` — 标准化评价报告
- **name**: `report-generate`
- **用途**: 生成耕地质量评价、三普、三调等国家规范报告（Word 格式）
- **工具**: `arcgis-mcp-server`, `bing-search`, `knowledge-db`
- **报告结构**: 评价方法概述 → 评价结果与分析 → 问题与对策建议
- **字体规范**: 标题黑体 18/16/14pt，正文宋体 12pt，表格宋体 10.5pt，均黑色

### `tool-report` — 过程报告
- **name**: `tool-report`
- **仅限**: `@report` Agent
- **用途**: 记录 GIS 分析操作流程与结果的过程报告（实验报告形式）
- **数据来源**: 读取 `02_WorkSpace/gis-tool-logs.json` 执行日志

### `conclusion-report` — 标准化分析报告
- **name**: `conclusion-report`
- **仅限**: `@report` Agent
- **用途**: 调用 `/data-analyzer` 获取分析结果，根据用户需求动态构建报告结构，进行深度分析并生成 Word 文档
- **数据来源**: 通过 `data-analyzer` skill 输出 + 用户指定数据

### `data-analyzer` — 数据统计分析核心
- **name**: `data-analyzer`
- **用途**: 输出统计数据、文字分析结论和数据洞察；纯 Python 内置库，无需依赖
- **调用方式**: 通过 `conclusion-report` skill 调用
- **脚本**: `data-analyzer/analyzer.py`

### `map-image-generate` — 地图制图
- **name**: `map-image-generate`
- **仅限**: `@gis-data-visualisation` Agent
- **用途**: 使用 `color-style-mcp` 根据指定数据生成地图图片（300dpi PNG）
- **依赖 MCP**: `color-style-mcp` 的 `create_map` 工具

### `map-beautify-skills/beautify-routing` — 地图美化路由
- **name**: `beautify-routing`
- **仅限**: `@gis-data-visualisation` Agent
- **用途**: 当用户请求美化粗糙地图图片时使用，读取用户提示词与底图，按 skills 知识库分类规则与美化原则拼装中文 prompt，调 `beautify_image` MCP 工具完成图生图美化
- **配套文件**: `principles.md`, `purposes.md`, `styles.md`, `themes.md`, `negative_prompts.md`

---

## 新增 Skill

1. 在 `skills/` 下新建目录（目录名即 skill 的引用名）
2. 创建 `SKILL.md`，编写 frontmatter 和技能提示词
3. 相关脚本、数据库等放入同一目录
4. 在需要使用该 Skill 的 Agent 的 frontmatter `skills` 列表中声明

## 重要说明

- **禁止用 Read 工具直接读取 SKILL.md**：modify-protect-hook 会拦截此操作，应使用 Skill 工具加载
- `plugin/skills/` 目录下的路径被 Hook 放行，Skill 内的脚本可正常读写此目录内的文件
- 每个 Skill 应在 `description` 中明确说明**何时**以及**哪个 Agent** 可调用
