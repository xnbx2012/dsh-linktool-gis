---
name: tool-report
description: Generates GIS process reports from task_plan.md, gis-tool-logs.json, outputs, and visualization assets.
agent: report
allowed_tools: [arcgis-mcp-server, knowledge-db]
---

# tool-report

## 1. 适用场景

用于生成 GIS 分析过程报告，重点回答“做了什么、为什么这样做、每一步得到什么结果”。

适用：
- 实验报告
- 操作流程报告
- GIS 工具执行记录
- 分析过程复盘

不适用：
- 评价结论、政策建议、深度原因分析 → 使用 `/conclusion-report`
- DOCX/XLSX 创建或排版 → 使用 `/officecli`

## 2. 输入与产出

输入：
- `02_WorkSpace/task_plan.md`：任务目标、计划步骤、验收标准。
- `02_WorkSpace/gis-tool-logs.json`：工具、参数、输入输出、错误与重试。
- `03_Result/`：最终结果数据和地图。
- `03_Result/assets/images/[Mission ID]/`：过程截图或结果图。

输出：
- 主报告：`03_Result/[Mission ID]_analysis_report.md`
- 可选索引：`02_WorkSpace/[Mission ID]_report_data.md`

## 3. 工作流

1. 建立章节清单：任务概览、数据准备、操作流程、图片与图注、附录。
2. 从日志中按执行顺序整理工具步骤。
3. 识别关键步骤；关键步骤独立成节，非关键步骤合并概述。
4. 为每个关键步骤匹配输出文件和图片。
5. 分段写入 Markdown。
6. 自检章节、日志、图片、路径、图注编号。

## 4. 过程报告结构

```markdown
# [Mission ID] GIS 分析过程报告

## 1. 任务概览
- 任务目标
- 执行日期
- 报告作者：LinkTool-report
- 参与环节：task-plan / gis-tool / visualisation / report

## 2. 数据准备与环境
| 数据项 | 路径 | CRS/WKID | 几何/栅格类型 | 关键字段 |
|---|---|---|---|---|

## 3. 操作流程与结果
按执行顺序组织，建议分为“数据准备、空间处理、统计汇总、结果输出”。

### 3.x [步骤组]
说明该组目的。

#### 3.x.y 步骤 N：[操作名称]
必须包含：输入数据、工具名称、关键参数意义、输出数据、结果图片和图注；无图片时说明缺失原因。

## 4. 附录
- 输出文件索引
- 工具执行日志摘要
- 错误与重试记录
```

## 5. 关键步骤识别与写法

满足任一条件即独立成节：

1. 产生 `03_Result/` 下最终交付物。
2. 直接对应 `task_plan.md` 的验收标准。
3. 执行关键空间转换：`Project`、`Clip`、`Select`、`Extract by Mask`、`Buffer`、`Intersect`、`Union`、`Erase`、`Identity`、`Reclassify`、`Raster Calculator`、`Weighted Overlay`、`Kernel Density`、`Hot Spot Analysis`。
4. 输出被后续 2 个及以上步骤使用。
5. 曾失败但最终重试成功。

非关键步骤：合并到步骤组概述中，用一句话说明工具和用途。

步骤叙述公式：

```text
使用 **[Tool]** 对 [输入数据] 执行 [目的]。关键参数 [参数]=[值] 的作用是 [影响]。处理后得到 [输出]，用于 [后续用途/验收标准]。
```

禁止只罗列参数，例如“参数：distance=200 Meters, dissolve_option=ALL”。

## 6. 图片、表格与附录规则

图片规则：
- 图片路径使用绝对路径。
- 图注连续编号：图 1、图 2……
- 每个关键步骤应有图片；缺失时写明“未找到对应可视化图片”，不要伪造。

表格规则：
- 数据源、输出文件、工具日志用表格。
- 长路径保留完整路径，不改写为模糊描述。

附录规则：
- 工具日志摘要列：序号、工具、输入、关键参数、输出、状态。
- 错误记录列：工具、错误、修正、重试结果。

## 7. 自检清单

交付前检查：

- Mission ID 一致。
- 每个关键步骤能追溯到 `gis-tool-logs.json`。
- 所有最终输出文件存在。
- 所有图片路径可访问，图注编号连续。
- 参数解释说明“为什么这样设置”，不是参数清单。
- 附录包含输出文件索引和日志摘要。

## 8. Few-shot 示例

### 示例 1：单步缓冲区过程报告

日志：`Buffer`，道路 → `road_buffer_200m`，`distance=200 Meters`，`dissolve_option=ALL`。

写法：
使用 **Buffer** 工具对道路中心线执行 200 米缓冲区分析。缓冲距离设置为 200 米，用于表示道路两侧可影响范围；`dissolve_option=ALL` 将重叠缓冲区合并，避免内部边界影响面积统计。输出 `road_buffer_200m` 作为后续用地叠加分析的范围约束。

### 示例 2：投影转换

日志：`Project`，CGCS2000 地理坐标 → 高斯-克吕格投影坐标。

写法：
使用 **Project** 工具将 CGCS2000 地理坐标数据转换为适合研究区的高斯-克吕格投影。该步骤保证后续缓冲距离和面积统计以米为单位计算，避免经纬度坐标下距离失真。

### 示例 3：多因子叠加

日志：`Intersect`，耕地图斑 + 坡度分区 + 土壤等级 → 综合评价单元。

写法：
使用 **Intersect** 工具叠加耕地图斑、坡度分区与土壤等级数据，输出同时包含地类、坡度和土壤属性的综合评价单元。该结果直接对应“形成评价单元”的验收标准，是后续等级统计的核心输入。

## 9. 按需参考

- 仅当需要生成 Word/DOCX 排版命令时，使用 `Read` 读取：`plugin/skills/tool-report/formatting-guide.md`。
- 常规 Markdown 过程报告不要读取该文件。
- DOCX/XLSX 生成与验证交给 `/officecli`。
## plan0701 Workflow 边界

- 过程报告必须作为完整 Workflow 的 Deliver/Conclusion 阶段执行，读取真实工具日志和产物。
- 不得替代数据处理、分析计算或验收阶段。
