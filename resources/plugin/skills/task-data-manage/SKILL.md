---
name: task-data-manage
description: "根据任务类型进行任务数据筛选与清单生成。基于任务类型推导所需数据，扫描可用数据，并形成标准化的数据清单。仅供 @task-plan Agent 使用。"
agent: task-plan
context: fork
---

**!IMPORTANT** 此 Skill 必须在 `@task-plan` agent 内调用，严禁直接调用！

## Skill 定位

本 Skill 负责：根据任务类型推导所需数据，通过语义匹配扫描 `01_DataBackup/` 中的可用数据，并形成标准化的数据清单。

**输入**：任务类型、分析对象、分析范围（由 task-plan 的 2.4 Interpret Task Requirements 步骤提供）

**输出**：写入 `02_WorkSpace/task_plan.md` 的 `## Data Inventory` 小节

**执行时机**：任务解释之后，参考资料推理之前

详细流程、筛选标准、清单格式和示例见 `data-screening.md`。

## 与 data-doubt-check 的关系

- `data-doubt-check`：判断数据是否存疑（名称歧义、命名泛化、信息缺失等）
- `task-data-manage`：按任务类型筛选数据，形成清单

筛选过程中发现的存疑数据，会交给 `data-doubt-check` Skill 逐项确认。
