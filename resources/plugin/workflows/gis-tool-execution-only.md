# GIS 工具批量执行 Workflow

> plan0701 约束：本模板仅适用于已知工具链的局部批量执行，不得用于从零开始的完整复杂 GIS 任务。若用户任务需要数据摸底、分析、制图、报告、验收全流程，必须改用 `gis-standard-analysis.md`。子 Agent 异常原地重试最多 5 次；失败后只允许 resume 1 次。

> 适用场景：用户已明确知道要执行哪些 GIS 工具、输入输出路径和参数，只需要按依赖顺序批量执行，不需要数据画像或复杂规划。

## 流程图

```text
参数校验 → 按依赖关系串/并行执行 → 每步结果核查 → 汇总
```

## 输入

- 明确的 GIS 工具列表（含工具名、输入路径、输出路径、参数）
- 串行/并行依赖关系

## 输出

- `02_WorkSpace/` 中的中间数据
- `03_Result/` 中的结果数据（如适用）

## 子 Agent 调用关系

| Phase | Agent | 职责 |
|-------|-------|------|
| 参数校验 | @gis-tool | /param-confirm Skill |
| 工具执行 | @gis-tool | /tool-execute Skill |
| 结果核查 | @gis-tool | /result-confirm Skill |
| 异常修复 | @gis-tool | /tool-retry Skill |

## Workflow 参考脚本

> **使用说明**：`@task-plan` 将工具链写入 `args.steps`，每项包含 `{ id, contract, agentType, label }`。

```javascript
export const meta = {
  name: 'gis-tool-execution',
  description: 'GIS工具批量执行Workflow',
  whenToUse: '已明确知道要执行哪些GIS工具、输入输出路径和参数，只需按依赖顺序批量执行',
  phases: [
    { title: 'Execute', detail: '按依赖执行GIS工具' },
  ],
}

phase('Execute')
const results = await pipeline(
  args.steps,
  step => agent(step.contract, {
    agentType: step.agentType || 'linktool-plugin:gis-tool',
    label: step.label || step.id,
    phase: 'Execute',
  })
)
log('执行完成，成功 ' + results.filter(Boolean).length + '/' + args.steps.length)
return results
```

## 失败处理

- 单步失败：由 @gis-tool 内部重试链路处理。
- 重试仍失败：Workflow 终止，向用户报告。
