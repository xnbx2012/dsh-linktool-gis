# GIS 调试分析 Workflow

> plan0701 约束：调试模式仍必须是单一全流程 Workflow，阶段按 Prepare / Process / Analyze / Deliver / Verify 组织；子 Agent 异常原地重试最多 5 次；失败后只允许 Edit 原脚本并用原 runId resume 1 次，总共最多 2 次 Workflow 调用。

> 适用场景：与 gis-standard-analysis 相同的全流程，但强制开启调试模式：每个关键阶段前展示状态并要求用户确认。用于开发调试、复杂任务验证或对比测试。

## 流程图

```text
工作空间检查 → [确认] → 数据画像 → [确认] → 执行计划生成 → [确认] → GIS 原子操作执行 → [确认] → 结果核查 → [确认] → 可视化 → [确认] → 报告 → [确认] → 交付汇总
```

与 gis-standard-analysis 的唯一区别：每个 Phase 之间插入强制用户确认。

## 输入/输出

与 gis-standard-analysis 相同。

## 调试模式规则

1. 每个关键阶段前，使用 `AskUserQuestion` 展示当前状态、待执行步骤和预期输出。
2. 等待用户确认后才进入下一阶段。
3. 用户可以随时要求修改计划或中止。
4. 当用户说"跳过确认"、"生产模式"时，切换到标准模式。

## Workflow 参考脚本

> **使用说明**：与 gis-standard-analysis 脚本结构相同，但在每个 phase 边界输出 `log()` 便于调试追踪。
> 用户确认由 `@task-plan` 在调用 Workflow 之前/之后控制，脚本内不调用 `AskUserQuestion`。

```javascript
export const meta = {
  name: 'gis-debug-analysis',
  description: 'GIS调试分析Workflow（每阶段输出状态供调试）',
  whenToUse: '需要调试/验证GIS工作流，每阶段输出详细状态信息供排查问题',
  phases: [
    { title: 'Check', detail: '工作空间检查' },
    { title: 'Profile', detail: '数据画像' },
    { title: 'Execute', detail: 'GIS原子操作' },
    { title: 'Deliver', detail: '可视化+报告+汇总' },
  ],
}

phase('Check')
log('[DEBUG] 工作空间检查完成，数据：' + JSON.stringify(args.dataPaths))

phase('Profile')
const profile = await agent(
  '基于工作空间中的数据和用户需求生成数据画像。输出：数据集清单、坐标系、几何类型、字段列表、空间范围。保存到 02_WorkSpace/data_profile.md。用户需求：' + args.userRequirement,
  { agentType: 'linktool-plugin:data-retrieval', label: 'DataProfile', phase: 'Profile' }
)
log('[DEBUG] 数据画像完成：' + JSON.stringify(profile).slice(0, 200))
// @task-plan 在此暂停，展示画像结果给用户确认

phase('Execute')
log('[DEBUG] 开始执行 ' + args.steps.length + ' 个GIS步骤')
const results = await pipeline(
  args.steps,
  step => agent(step.contract, {
    agentType: step.agentType || 'linktool-plugin:gis-tool',
    label: step.label || step.id,
    phase: 'Execute',
  })
)
const succeeded = results.filter(Boolean).length
log('[DEBUG] GIS执行完成：' + succeeded + '/' + args.steps.length + ' 成功')
// @task-plan 在此暂停，展示执行结果给用户确认

phase('Deliver')
const deliverables = []
if (args.needVisualization) {
  deliverables.push(() => agent('对以下数据生成网页可视化：' + JSON.stringify(args.resultPaths), {
    agentType: 'linktool-plugin:gis-data-visualisation', label: 'Visualize', phase: 'Deliver',
  }))
}
if (args.needReport) {
  deliverables.push(() => agent('基于执行结果生成' + args.reportType + '报告。执行日志：02_WorkSpace/gis-tool-logs.json', {
    agentType: 'linktool-plugin:report', label: 'Report', phase: 'Deliver',
  }))
}
if (deliverables.length > 0) {
  await parallel(deliverables)
}
return { summary: '[DEBUG] 调试分析Workflow完成', results: results }
```

## 失败处理

与 gis-standard-analysis 相同，使用断点续跑协议：
- 调试模式下，@task-plan 在每个 phase 边界展示状态快照
- Workflow 失败后，@task-plan 展示错误摘要 + 修复方案 + 脚本 diff，等待用户确认
- 用户确认后编辑原 `02_WorkSpace/workflow_script.js` 并 `resumeFromRunId` 续跑
- 调试模式下额外提供：每个阶段结束后的状态快照和用户决策记录

## args 结构

与 gis-standard-analysis 相同，额外支持断点续跑字段：

```javascript
args = {
  // ...与 gis-standard-analysis 相同的字段...

  // 断点续跑字段（Workflow 失败后 resume 时传入）
  isResume: false,              // 是否为 resume 续跑
  resumeAttempt: 0,             // 第几次续跑（0=原始，1=第一次，2=第二次）
  originalRunId: null,          // 原始 Workflow 的 runId（wf_xxxxx 格式）
  fixedSteps: [],               // 本次修改涉及的 step ID 列表
}
```

**🚨 args 格式硬性约束**：与 gis-standard-analysis 相同——`args` 必须传入 JS 对象字面量 `{ ... }`，禁止传入 JSON 字符串。否则脚本内 `args.xxx` 全部为 `undefined`。简单值优先硬编码到 prompt 中。
