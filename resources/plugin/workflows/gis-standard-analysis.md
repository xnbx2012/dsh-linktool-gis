# GIS 标准分析 Workflow

> 适用场景：完整的 GIS 空间分析任务（选址、适宜性评价、多因子叠加等），需要从数据探索到最终交付的全流程。

## 流程图

```text
工作空间检查 → 数据画像 → 执行计划生成 → 用户确认 → GIS 原子操作执行 → 结果核查 → 可视化 → 报告 → 意图验证 → 交付汇总
```

**子 Agent 返回格式要求**（来自实际运行教训）：

每个子 Agent 必须返回 **结构化 JSON 对象**，禁止返回空字符串或纯文本。格式：
```json
{
  "status": "success" | "failed" | "needs_clarification",
  "data": <any>,           // 成功时包含数据
  "error": "string",       // 失败时包含错误描述
  "warnings": ["..."]      // 可选：警告信息
}
```

**父 Workflow 检查规则**（必须执行；子 Agent 异常原地重试最多 5 次）：
```javascript
function validateAgentResult(result, label) {
  if (!result || typeof result !== 'object') {
    return { ok: false, error: label + ' returned empty or non-object result' }
  }
  if (!['success', 'failed', 'needs_clarification'].includes(result.status)) {
    return { ok: false, error: label + ' missing valid status field' }
  }
  return { ok: true, value: result }
}

async function runAgentWithRetry(prompt, opts, maxRetries = 5) {
  let lastError = null
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const result = await agent(prompt, opts)
      const checked = validateAgentResult(result, opts.label || 'agent')
      if (checked.ok) return checked.value
      lastError = checked.error
      log((opts.label || 'agent') + ' 返回无效，原地重试 ' + attempt + '/' + maxRetries)
    } catch (e) {
      lastError = String(e && e.message ? e.message : e)
      log((opts.label || 'agent') + ' 异常，原地重试 ' + attempt + '/' + maxRetries + ': ' + lastError)
    }
  }
  return { status: 'failed', error: 'AGENT_RETRY_EXHAUSTED: ' + lastError, label: opts.label || 'agent' }
}

const errors = []
function collectError(stepId, result) {
  if (result && result.status === 'failed') {
    errors.push({ stepId, error: result.error || 'unknown error', warnings: result.warnings || [] })
  }
}
```

**为什么这是硬性约束**：之前 parallel() 包裹的 5 个子任务都返回"成功"但实际内容为空（空字符串），主 Agent 的 `indicators.filter(Boolean).length < 3` 判失败无法区分"成功但空"与"真正失败"，导致 12 分钟算力浪费。

## 输入

- 用户自然语言 GIS 需求
- `01_DataBackup/` 中的原始数据

## args 结构

Workflow 由 `@task-plan` 通过 `Workflow({ scriptPath: '...', args: { ... } })` 调用，脚本通过 `args.xxx` 访问传入参数。

```javascript
args = {
  // 现有字段
  userRequirement: '用户原始需求文本',
  steps: [
    {
      contract: '...',           // Agent Task Contract（含 Acceptance Criteria）
      agentType: 'gis-tool',
      label: 'Buffer_roads',
    }
  ],
  needVisualization: true,
  needReport: true,
  reportType: '过程报告',
  resultPaths: ['02_WorkSpace/suitable_zones'],

  // 新增字段
  goals: '## 意图标准\n- 分析结果覆盖所有因子\n- 输出在 03_Result/ 下',

  // 断点续跑字段（Workflow 失败后 resume 时传入）
  isResume: false,              // 是否为 resume 续跑
  resumeAttempt: 0,             // 第几次续跑（0=原始，1=唯一一次 resume；总共最多2次 Workflow 调用）
  originalRunId: null,          // 原始 Workflow 的 runId（wf_xxxxx 格式）
  fixedSteps: [],               // 本次修改涉及的 step ID 列表
}
```

**🚨 args 格式硬性约束**：`args` 必须传入 JavaScript 对象字面量 `{ ... }`（如上所示），**禁止**传入 JSON 字符串（如 `args: '{"key": "value"}'`）。字符串形式会导致脚本内 `args.xxx` 全部为 `undefined`。若某个值只在一处使用，优先硬编码到 prompt 字符串中，不依赖 `args`。

## 输出

- `02_WorkSpace/data_profile.md`：数据画像
- `02_WorkSpace/task_plan.md`：用户可读计划摘要
- `02_WorkSpace/workflow_script.js`：真实执行脚本
- `02_WorkSpace/gis-tool-logs.json`：执行日志（由 Hook 自动写入）
- `03_Result/`：最终交付成果

## 子 Agent 调用关系

| Phase | Agent | 职责 |
|-------|-------|------|
| 工作空间检查 | @task-plan 自身 | 遍历目录、验证数据存在性 |
| 数据画像 | @data-retrieval | 元数据检索、数据画像生成 |
| 执行计划生成 | @task-plan 自身 | 生成结构化执行步骤 |
| 用户确认 | @task-plan 自身 | ExitPlanMode + AskUserQuestion |
| GIS 原子操作执行 | @gis-tool | 每个步骤调用 /param-confirm → /tool-execute → /result-confirm → /tool-retry |
| 结果核查 | @gis-tool 内部 | /result-confirm Skill |
| 可视化/出图 | @gis-data-visualisation | GeoJSON 转换 + Leaflet 推送 + color-style-mcp 专题图（**禁止用 @gis-tool**） |
| 报告 | @report | officecli 生成 Word/MD |
| 交付汇总 | @task-plan 自身 | 清单式列出成果路径 |
| 意图验证 | @task-plan 自身（Workflow 内 Verify phase） | 对照 goals 逐条验证整体结果 |

## 动态 Workflow 参考脚本

> **使用说明**：此模板由 `@task-plan` 根据实际任务适配后写入 `02_WorkSpace/workflow_script.js`。
> `args` 中的数据由 `@task-plan` 在调用 `Workflow({ args: { ... } })` 时传入。

```javascript
export const meta = {
  name: 'gis-standard-analysis',
  description: 'GIS标准分析全流程',
  whenToUse: '完整的GIS空间分析任务（选址、适宜性评价、多因子叠加等），需要从数据探索到最终交付的全流程',
  phases: [
    { title: 'Prepare', detail: '工作空间检查、数据摸底、CRS策略' },
    { title: 'Process', detail: '投影、整理、预处理' },
    { title: 'Analyze', detail: 'GIS原子操作与指标计算' },
    { title: 'Deliver', detail: '可视化+报告+汇总' },
    { title: 'Verify', detail: '意图验证' },
  ],
}

phase('Prepare')
// ─── S12: 读取已有进度快照，决定是否跳过已完成的步骤 ───
// 进度文件由 gis-tool-log/enhanced_record.py 在每次工具执行后更新。
let progress = { total_calls: 0, completed_steps: {} }
try {
  const progressPath = '02_WorkSpace/.workflow_progress.json'
  // Workflow 脚本无 fs 权限，由 @task-plan 在 args 中传入
  if (args && args.existingProgress) {
    progress = args.existingProgress
  }
} catch (e) {
  // 进度文件不存在或解析失败，按全新工作流处理
}
log('已有进度：' + progress.total_calls + ' 次工具调用，' + Object.keys(progress.completed_steps || {}).length + ' 个已完成步骤')

// MCP 就绪探测：在数据画像之前验证 arcgis-mcp-server 是否可调用
// 避免首个工作流因 MCP 未就绪而白跑数十步骤
const mcpProbe = await agent(
  '仅执行一次最小化 MCP 工具调用验证 arcgis-mcp-server 是否就绪：调用 list_gdb_contents 对 cwd 的 01_DataBackup 目录，或对任意已知路径做 get_data_properties。若工具不可用或报"not available/未连接/工具未找到"，返回包含 ENV_UNAVAILABLE 的字符串；若正常，返回 {"status":"success","message":"MCP就绪"}。禁止执行任何 GIS 数据处理。',
  { agentType: 'linktool-plugin:gis-tool', label: 'MCPReadyCheck', phase: 'Prepare' }
)
if (!mcpProbe || (typeof mcpProbe === 'string' && mcpProbe.includes('ENV_UNAVAILABLE')) ||
    (typeof mcpProbe === 'object' && mcpProbe.status === 'failed' && mcpProbe.error && mcpProbe.error.includes('ENV_UNAVAILABLE'))) {
  log('ERROR: arcgis-mcp-server 未就绪，请重连 MCP 工具后重试')
  return { status: 'failed', error: 'ENV_UNAVAILABLE: arcgis-mcp-server 未就绪，请在 Claude Code 中重新连接 arcgis-mcp-server 后重新启动 Workflow' }
}
log('MCP 就绪检查通过')
// @task-plan 自身已完成工作空间检查，数据路径已记录在上下文中
log('工作空间检查完成')

phase('Prepare')
const profile = await agent(
  '基于工作空间中的数据和用户需求生成数据画像。输出：数据集清单、坐标系、几何类型、字段列表、空间范围。保存到 02_WorkSpace/data_profile.md。用户需求：' + args.userRequirement,
  { agentType: 'linktool-plugin:data-retrieval', label: 'DataProfile', phase: 'Prepare' }
)
log('数据画像完成')

phase('Analyze')
// args.steps 由 @task-plan 根据 DAG 生成，每项含 contract/agentType/label/id
// ─── S5: 跳过已完成步骤 ───
// 若 args.skipStepIds 包含某个 step.id 且 progress.completed_steps 中存在对应记录，
// 则跳过该 step 的执行（@task-plan 在 resume 时根据 .workflow_progress.json 填充此字段）。
const skipStepIds = (args && args.skipStepIds) || []
const filteredSteps = args.steps.filter(step => {
  if (skipStepIds.includes(step.id) && progress.completed_steps && progress.completed_steps[step.id]) {
    log('跳过已完成步骤: ' + step.id)
    return false
  }
  return true
})
const results = await pipeline(
  filteredSteps,
  step => agent(step.contract, {
    agentType: step.agentType || 'linktool-plugin:gis-tool',
    label: step.label || step.id,
    phase: 'Analyze',
  })
)
// ENV_UNAVAILABLE 门控：若有步骤报告 MCP 不可用，立即停止后续阶段
const envUnavailableSteps = results.filter(r =>
  r && typeof r === 'object' && r.status === 'failed' && r.error && r.error.includes('ENV_UNAVAILABLE')
)
if (envUnavailableSteps.length > 0) {
  log('ERROR: MCP 服务不可用 — ' + envUnavailableSteps[0].error)
  return { status: 'failed', error: 'ENV_UNAVAILABLE: arcgis-mcp-server 在执行阶段断开，请重连后使用 resumeFromRunId 续跑', results }
}
log('GIS操作完成，成功 ' + results.filter(Boolean).length + ' 个')

phase('Deliver')
const deliverables = []
if (args.needVisualization) {
  deliverables.push(() => agent('对以下数据生成网页可视化：' + JSON.stringify(args.resultPaths), {
    agentType: 'linktool-plugin:gis-data-visualisation', label: 'Visualize', phase: 'Deliver',
  }))
}
if (args.needReport) {
  deliverables.push(() => agent(
    '基于执行结果生成' + args.reportType + '报告。\n\n' +
    '数据源（按以下顺序逐个读取，不要一次性读取所有文件）：\n' +
    '1. 先读 02_WorkSpace/task_plan.md 了解任务结构和验收标准\n' +
    '2. 再读 02_WorkSpace/gis-tool-logs.json 了解执行过程\n' +
    '3. 按报告章节需要，逐个读取具体数据文件（用 query_feature_attributes 获取统计数据，不要读取完整属性表）\n' +
    '4. 输出路径：03_Result/\n\n' +
    '注意：分段写入报告，每次 Write/Edit 不超过 50 行。',
    { agentType: 'linktool-plugin:report', label: 'Report', phase: 'Deliver' }
  ))
}
if (deliverables.length > 0) {
  await parallel(deliverables)
}

// ─── Phase 5: 意图验证 ───
phase('Verify')
const verifyResult = await agent(
  [
    '## 意图验证任务',
    '你是一个独立的验证 Agent。你的任务是对照以下验收标准，检查 GIS 分析的整体结果。',
    '',
    '## 验收标准',
    args.goals,
    '',
    '## 已执行步骤结果',
    JSON.stringify(results, null, 2),
    '',
    '## 输出文件',
    JSON.stringify(args.resultPaths || []),
    '',
    '## 验证要求',
    '- 逐条检查每项验收标准',
    '- 使用 MCP 工具或 Read 工具验证文件存在性和数据属性',
    '- 输出结构化结果：',
    '  { passed: boolean, criteriaResults: [{ criterion, status: "PASS"|"FAIL", evidence }] }',
    '- 只有全部 PASS 时 passed 才为 true',
  ].join('\n'),
  { label: 'GoalVerify', phase: 'Verify' }
)

log('意图验证完成')
return {
  summary: 'GIS标准分析Workflow完成',
  results: results,
  verifyResult: verifyResult,
  // runId 由 Workflow 引擎自动生成（如 wf_abc123），@task-plan 从 Workflow 工具返回值中提取
}
```

## 失败处理

- GIS 工具执行失败：由 @gis-tool 内部 /param-confirm → /tool-execute → /result-confirm → /tool-retry 链路处理，最多重试 3 次。
- 重试仍失败：Workflow 脚本返回失败状态，@task-plan 收到汇总后使用 **断点续跑协议**（参见 `plugin/agents/task-plan.md` Section 4.3.1）处理：
  1. 自动分析失败原因（工具选择/参数/数据/前置条件/Agent 超时）
  2. 向用户展示错误摘要和修复方案，等待确认
  3. 编辑原 `02_WorkSpace/workflow_script.js` 修复失败步骤
  4. 调用 `Workflow({ scriptPath, resumeFromRunId: <原 runId> })` 续跑
  5. 已完成的 agent() 调用自动返回缓存结果，仅修改过的步骤重新执行
- 数据画像失败：终止 Workflow，提示用户检查数据。
- 意图验证失败：@task-plan 一次性汇总所有失败项，编辑原脚本后仅允许使用原 runId 做 1 次 resume 续跑；仍失败则报告用户。
- **禁止**生成新的 remediation/fix workflow 文件替代原脚本。
