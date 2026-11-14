---
name: gis-task-plan
description: "GIS任务规划全流程：数据探索→需求解读→任务分解→计划审批→执行→验收。仅限 @task-plan Agent 调用。"
context: fork
agent: task-plan
argument-hint: "[用户原始需求文本]"
---

# 工作空间规范

| 目录 | 权限 | 规则 |
|------|------|------|
| `01_DataBackup/` | 只读 | 禁止写入/修改/删除 |
| `02_WorkSpace/` | 读写 | 过程数据，GDB优先，命名清晰有序 |
| `03_Result/` | 读写 | 仅最终交付物，禁止混入中间数据 |

- 计划/笔记/索引 → `02_WorkSpace/`
- 禁止操作上述三目录外的任何路径

# Agent 调度表

| Agent | 职责 | Type标记 |
|-------|------|----------|
| `@gis-tool` | 原子GIS操作（缓冲区/裁剪/叠加/重分类等） | `GIS` |
| `@data-retrieval` | 快速数据摸底 | `Data` |
| `@gis-data-visualisation` | 网页可视化/制图 | `Viz` |
| `@report` | 过程报告/结论报告 | `Report` |

# 绝对禁令

- ❌ 编写 arcpy 代码替代 MCP 工具
- ❌ 未确认 CRS 一致就做空间叠加
- ❌ 把制图任务交给 `@gis-tool`
- ❌ 在未提取字段命名规范前生成字段创建/计算契约
- ❌ 调用 param-confirm/tool-execute/tool-report/tool-retry Skill

## 委派契约与 MCP 工具声明

> 本节声明为 **设计预期**，对应 `plugin/CROSS_AGENT_RULES.md` 规则一/四。

- `gis-task-plan` 使用 `context: fork`，fork **仅用于只读数据探索/数据画像**
- **分析动作不在 fork 子 Agent 内发起**；fork 探索结果以结构化产物回流主会话
- **分析工具（`execute_gis_tool` 等）在主会话 / fork 规划子 Agent 中不可用属设计预期**（主会话只持有属性查询类工具）
- 发现需要分析时，**必须通过 Workflow 契约委派 `@gis-tool` 执行**，禁止用 Bash/Write 兜底自执行
- **违例直接返回 `ENV_ERROR`**：`{status: ENV_ERROR, missing: ["execute_gis_tool"], next_action: "检查 plugin.json MCP 配置或重启会话"}`

---

# 规划流程

## Phase 1: 数据探索

1. 调用 `list_gdb_contents` 获取 `.gdb` 中的要素数据集和要素类
2. 对关键数据调用 `get_data_properties` 获取：
   - 坐标系（EPSG）、空间范围、几何类型、数据格式、字段列表
3. 按需调用 `query_feature_attributes`（前10行）：字段含义不明、需确认值域、代码值需对照

## Phase 2: 需求解读

### 2.1 任务解析

口语 → 结构化GIS需求：

```
任务类型: [选址分析/适宜性评价/耕地质量评价/空间统计/...]
分析对象: [具体对象]
核心目标: [可量化目标]
分析范围: [空间+时间范围]
```

### 2.2 数据清单

调用 `task-data-manage` Skill 筛选所需数据，形成清单：
- 全部匹配 → 直接下一步
- 存在疑点 → 调用 `data-doubt-check` 确认
- 缺少必需数据 → 问用户（提供替代/跳过选项）
- 缺少建议数据 → 标记为可选，不阻塞

### 2.3 参考资料

按任务类型补充：

| 步骤 | 内容 | 方法 |
|------|------|------|
| 国家标准 | 适用规范 | 按任务类型查表确定 |
| 字段命名规范 | 输出字段代码/类型/长度 | 阅读用户参考文档中的"字段规范/属性结构/附件"章节 |
| 网络搜索 | 技术方法/行业教程 | WebSearch 任务类型+工具名 |
| 知识库案例 | 相似GIS案例 | `search_knowledge` 任务类型+数据名 |

**字段命名规范提取**（评估/分级类任务必须执行）：
1. 阅读 `01_DataBackup/` 中的参考文档，查找字段规范章节
2. 提取字段代码、名称、类型、长度、小数位
3. 记录到 `task_plan.md` 的 `## 输出字段命名规范`
4. 下游所有 `output_field_names` 必须使用此规范中的字段代码

### 2.4 用户确认

仅在信息缺失时提问：

| 场景 | 询问内容 |
|------|---------|
| 目标模糊 | "质量评价是指耕地质量等级还是污染程度？" |
| 范围未定 | "分析应覆盖哪个行政区？" |
| 权重缺失 | "因子权重是等权还是已确定？" |
| 输出不明 | "需要地图、报告，还是仅数据？" |

## Phase 3: 任务分解

### 3.1 任务目标

写入 `02_WorkSpace/task_plan.md`：

```markdown
## 任务目标

### 业务背景
- 需求来源：[用户原始需求]
- 业务场景：[任务在业务流程中的位置]
- 决策支持：[分析结果支持哪些决策]

### 任务定义
- 任务类型：[...]
- 分析对象：[...]
- 分析范围：[空间范围]
- 输出目标：[交付物类型]

### 约束条件
- 数据约束：[可用/缺失数据]
- 标准约束：[遵循标准]
- 技术约束：[CRS/精度]
- 字段命名约束：[引用输出字段命名规范章节]

### 验收标准
#### 技术标准（机器可验证）
- [ ] AC-1: [文件存在，要素数≥1]
- [ ] AC-2: [CRS一致]
- [ ] AC-3: [几何类型正确，无空几何]
- [ ] AC-4: [关键字段空值率<阈值]
- [ ] AC-5: [字段名/类型/长度与规范一致]

#### 意图标准（人工确认）
- [ ] AC-N: [覆盖全部因子]
- [ ] AC-N: [输出路径位于03_Result/]
```

### 3.2 实施计划

```markdown
## 实施计划

### 技术路线
[2-3段整体思路]

### 数据处理流水线
| 阶段 | 内容 | 输入 | 输出 | 关键操作 |
|------|------|------|------|----------|

### 工具链规划
| 步骤 | GIS工具 | 来源 | 输入 | 输出 | 参数 |
|------|---------|------|------|------|------|

### 执行策略
- 顺序依赖：S1→S2→S3
- 并行：S4‖S5（输入相同，互不依赖）

### 风险与缓解
| 风险 | 影响 | 缓解 |
|------|------|------|
```

### 3.3 任务清单

```markdown
## 任务清单

| ID | 任务名称 | Type | 输入 | 输出 | 依赖 | 验收 | 状态 |
|----|---------|------|------|------|------|------|------|
| T1 | 筛选耕地地块 | GIS | ... | ... | — | AC-1 | Pending |
| T2 | 提取高程因子 | GIS | ... | ... | T1 | AC-2 | Pending |
```

**Type → Agent 映射**：
- `GIS` → `agentType: 'gis-tool'`
- `Data` → `agentType: 'data-retrieval'`
- `Viz` → `agentType: 'gis-data-visualisation'`
- `Report` → `agentType: 'report'`

### 3.4 GIS 原子契约

每个 `Type=GIS` 任务生成调度契约：

```markdown
## 契约 T[N]
- step_id: T[N]
- operation_type: [操作类型]
- required_arcgis_tool: [工具路径]
- input_paths: [输入路径]
- output_path: [输出路径]
- parameters: [参数]
- output_field_names: [字段代码列表，来自命名规范]
- preconditions: [前置条件]
- validation_criteria: [AC编号]
- retry_policy: [重试策略]
```

## Phase 4: 计划审批

1. 写入 `02_WorkSpace/task_plan.md`（含：任务目标/实施计划/任务清单/契约/数据清单/参考资料）
2. 若当前处于 **bypass 权限模式**（debug-server 环境，无需人工批准）：
   - 跳过 ExitPlanMode，直接进入 **Phase 5 执行**
   - `task_plan.md` 写入完成即视为"已批准"
3. 若处于 **plan 权限模式**（正常生产环境）：
   - 调用 `ExitPlanMode` 展示计划
   - 用户批准 → Phase 5；反馈修改 → 更新后重新展示

## Phase 5: 执行

1. 调用 `/workflow-dsl` 生成单一全流程 `workflow_script.js`（Prepare / Process / Analyze / Deliver / Verify），禁止多个短 Workflow 串联
2. 若处于 **bypass 权限模式**：直接提交 `Workflow` 工具执行，不等待用户确认
3. 若处于 **plan 权限模式**：展示脚本结构，等待用户确认后提交执行
4. 需求变更 → 返回 Phase 3 重新规划

## Phase 6: 验收与交付

1. 逐项验证 AC 标准（检查文件/属性/CRS/字段）
2. 生成验收报告
3. 失败 → 一次性汇总所有非致命错误，Edit 原 workflow_script.js 后用原 runId resume 1 次；总共最多 2 次 Workflow 调用
4. 向用户汇总交付物清单

---

# Few-shot 示例

## 示例 1: 简单缓冲区分析

**用户输入**："分析学校周边500米范围内的土地利用情况"

**任务分解**：
```
任务类型: 缓冲区+叠加分析
分析对象: 学校点位、土地利用图层
分析范围: 学校点位500m缓冲区
输出目标: 叠加分析结果数据
```

**任务清单**：
| ID | 任务 | Type | 输入 | 输出 | 依赖 |
|----|------|------|------|------|------|
| T1 | 学校500m缓冲区 | GIS | school.shp | 02_WorkSpace/school_buf500.shp | — |
| T2 | 土地利用裁剪 | GIS | landuse.shp + school_buf500.shp | 02_WorkSpace/landuse_clip.shp | T1 |
| T3 | 面积统计 | GIS | landuse_clip.shp | 02_WorkSpace/landuse_stats.dbf | T2 |

## 示例 2: 适宜性评价（多因素叠加）

**用户输入**："评价某市商业用地适宜性，考虑交通、人口、地价因素"

**任务分解**：
```
任务类型: 适宜性评价（多因素叠加）
分析对象: 商业用地
分析范围: 某市行政边界
输出目标: 适宜性等级图+评价报告
```

**任务清单**：
| ID | 任务 | Type | 输入 | 输出 | 依赖 |
|----|------|------|------|------|------|
| T1 | 数据摸底 | Data | 01_DataBackup/ | 数据清单 | — |
| T2 | 交通因子栅格化 | GIS | road.shp | 02_WorkSpace/factor_traffic.tif | T1 |
| T3 | 人口密度栅格化 | GIS | population.shp | 02_WorkSpace/factor_pop.tif | T1 |
| T4 | 地价因子插值 | GIS | land_price.shp | 02_WorkSpace/factor_price.tif | T1 |
| T5 | 加权叠加 | GIS | 3个因子栅格 | 02_WorkSpace/suitability.tif | T2,T3,T4 |
| T6 | 等级分类 | GIS | suitability.tif | 02_WorkSpace/suitability_grade.shp | T5 |
| T7 | 可视化 | Viz | suitability_grade.shp | 03_Result/maps/ | T6 |
| T8 | 报告生成 | Report | 全部结果 | 03_Result/report.docx | T6 |

## 示例 3: 耕地质量评价

**用户输入**："根据技术细则对XX县进行耕地质量评价并生成报告和图件"

**任务分解**：
```
任务类型: 耕地质量评价
分析对象: 全县耕地
分析范围: XX县行政边界
输出目标: 等级分布图+评价报告+成果数据
```

**任务清单**：
| ID | 任务 | Type | 输入 | 输出 | 依赖 |
|----|------|------|------|------|------|
| T1 | 数据摸底 | Data | 01_DataBackup/ | 数据清单+字段规范 | — |
| T2 | 耕地地块筛选 | GIS | 三调数据 | 02_WorkSpace/cropland_clip | T1 |
| T3 | 地形因子提取 | GIS | DEM | 02_WorkSpace/factor_terrain | T2 |
| T4 | 土壤因子提取 | GIS | 土壤数据 | 02_WorkSpace/factor_soil | T2 |
| T5 | 立地条件因子 | GIS | 基础数据 | 02_WorkSpace/factor_site | T2 |
| T6 | 综合指数计算 | GIS | T3-T5因子 | 02_WorkSpace/cei.tif | T3,T4,T5 |
| T7 | 等级分类 | GIS | cei.tif | 02_WorkSpace/grade.shp | T6 |
| T8 | 制图 | Viz | grade.shp | 03_Result/图件/ | T7 |
| T9 | 报告生成 | Report | 全部结果 | 03_Result/报告/ | T7 |

## 示例 4: 空间聚类/热点分析

**用户输入**："分析某市犯罪事件的空间聚集特征"

**任务清单**：
| ID | 任务 | Type | 输入 | 输出 | 依赖 |
|----|------|------|------|------|------|
| T1 | 核密度分析 | GIS | crime_points.shp | 02_WorkSpace/crime_kde.tif | — |
| T2 | 热点分析(Getis-Ord Gi*) | GIS | crime_points.shp | 02_WorkSpace/crime_hotspot.shp | — |
| T3 | 可视化 | Viz | crime_hotspot.shp | 03_Result/maps/ | T1,T2 |

## 示例 5: 选址分析

**用户输入**："为某区域选择最佳垃圾转运站位置"

**任务清单**：
| ID | 任务 | Type | 输入 | 输出 | 依赖 |
|----|------|------|------|------|------|
| T1 | 数据摸底 | Data | 01_DataBackup/ | 数据清单 | — |
| T2 | 约束条件缓冲区 | GIS | 居民区/水体/保护区 | 02_WorkSpace/restrict_buf | T1 |
| T3 | 需求区域分析 | GIS | 服务范围+人口 | 02_WorkSpace/demand_area | T1 |
| T4 | 可行区域提取 | GIS | restrict_buf + demand_area | 02_WorkSpace/feasible_area | T2,T3 |
| T5 | 适宜性评分 | GIS | feasible_area + 多因子 | 02_WorkSpace/site_score.tif | T4 |
| T6 | 最优选址 | GIS | site_score.tif | 02_WorkSpace/best_sites.shp | T5 |
| T7 | 可视化 | Viz | best_sites.shp | 03_Result/maps/ | T6 |
| T8 | 报告生成 | Report | 全部结果 | 03_Result/report.docx | T6 |
