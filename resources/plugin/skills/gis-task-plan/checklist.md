
## 核心检查项 (Essential Checks)

### 1. 任务规划清单检查
* [ ] **任务分解完成**：已生成包含Step、工具名称、说明、依赖项的Markdown表格
* [ ] **工具命名规范**：所有工具均使用`Toolbox.Tool`格式（如`analysis.Buffer`）
* [ ] **依赖关系明确**：每一步的依赖项已清晰标识


## 规划前置校验 (Pre-Planning Validation)

### 1. 数据诊断与环境 (Data Diagnosis)

* [ ] 已调用 `arcgis-mcp-server` 工具获取完整元数据。
* [ ] 所有输入数据的 WKID 坐标系已记录（地理 vs 投影）。
* [ ] 针对 WKID 不统一的情况，已规划 `management.Project`（矢量）或 `management.ProjectRaster`（栅格）步骤。
* [ ] 已明确当前工作空间 (Workspace) 的路径及其读写权限。

### 2. 数据缺口分析 (Gap Analysis)

* [ ] 已比对“业务目标”与“现有数据图层”的匹配度。
* [ ] 识别出的缺失项已向用户发起询问或规划了 API 抓取步骤（如高德 POI）。
* [ ] 外部数据源（API）的检索范围（Extent）已在规划中明确定义。

## 任务分解规范 (Task Decomposition)

### 3. 原子化与顺序 (Atomicity & Sequence)

* [ ] 每个步骤仅包含 **一个** 明确的 ArcGIS 工具全名（如 `analysis.Buffer`）。
* [ ] 步骤间存在数据依赖（DAG 结构）已通过 `depends_on` 标签明确。
* [ ] 无相互依赖的分支已标记 `can_parallel: true` 以优化执行效率。
* [ ] 规划中包含了环境设置步骤（如 `arcpy.env.overwriteOutput = True`）。

### 4. 跨 Agent 协作协议 (Inter-Agent Coordination)

* [ ] **工具执行 Agent**：已收到清晰的工具序列，且规划中 **未包含** 具体参数细节（由其自行查询）。
* [ ] **可视化 Agent**：已明确标注哪些中间/最终产物需要渲染，并指定了制图标准（如国家规范）。
* [ ] **分析报告 Agent**：已明确报告所需的统计维度（如面积占比、数量汇总）及文风要求。

## 健壮性与回退 (Robustness & Fallback)

### 5. 工具名与知识库校验

* [ ] 所有工具名称均符合 `<toolbox>.<tool>` 的标准格式。
* [ ] 已通过 RAG 知识库确认规划的工具在当前 ArcGIS Pro 版本中可用。

### 6. 容错逻辑设计

* [ ] 针对高风险步骤（如叠加分析），已预设“几何修复 (`RepairGeometry`) ”的回退路径。

---


## Agent 任务分发指令 (Dispatch Commands)


将生成的“mission_plan.md”规划发送至`gis_tool`、`report` 智能体`
send-task --to executor_agent --file 
 将“mission_plan.md”可视化需求预告给`visualisation`智能体

## 任务流评审提问
以选择题的形式供用户进行选择
1. 如果第一步 API 抓取的数据为空，我的规划是否有“停止并预警”的分支？
2. 每一个 `depends_on` 链接是否都有真实对应的上游输出？
3. 我是否为可视化 Agent 留出了足够的属性字段（如分类标签）用于美化显示？
4. 报告 Agent 是否知道去哪里抓取执行 Agent 生成的统计 Excel 文件？


## 输出风格约束：禁止任何开场白。直接输出 [Mission ID]。使用 Markdown 表格呈现任务流，表格中仅保留 Step、工具名称、说明、依赖 四列

## 输出验证

* [ ] **任务完整性**：规划清单与总结日志均已生成

## 任务分发指令
任务规划完成后，需要执行以下分发步骤：
向执行 Agent 发送任务：将生成的 mission_plan.md 文件发送给 `gis_tool`、`report` 智能体


## 输出风格约束
直接输出 [Mission ID] 和任务表格。工具执行完成时生成执行日志记录整个任务流程。