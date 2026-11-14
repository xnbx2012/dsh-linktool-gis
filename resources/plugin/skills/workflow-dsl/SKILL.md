---
name: workflow-dsl
description: "Claude Code Workflow DSL 编写规范、原子 GIS 合同格式与示例。仅限 @task-plan Agent 调用。"
agent: task-plan
context: fork
---

# Workflow DSL

## 1. 目标

用于 `@task-plan` 编写可运行、可缓存、可续跑的 Workflow 脚本。

## 2. 核心规则

1. `meta` 必须是纯字面量
2. 禁止 `Date.now()`、`new Date()`、`Math.random()`
3. 禁止 Node.js 文件系统 API
4. 禁止 TypeScript 类型注解
5. 禁止直接调 MCP 工具
6. 禁止在 Workflow 内再问用户问题

## 3. 语法规范

### 3.1 脚本骨架

```javascript
export const meta = {
  name: 'workflow-name',
  description: 'one line description',
  phases: [{ title: 'Phase A' }, { title: 'Phase B' }],
}

phase('Phase A')
const result = await agent('prompt', { label: 'A1', phase: 'Phase A' })

phase('Phase B')
const items = await parallel([
  () => agent('prompt 1', { label: 'B1', phase: 'Phase B' }),
  () => agent('prompt 2', { label: 'B2', phase: 'Phase B' }),
])

return { result, items }
```

### 3.2 语法约束

- `export const meta = {...}` 必须位于脚本最前
- `phase()` 的标题必须与 `meta.phases[].title` 一致
- `agent()` 的第一个参数必须是 prompt 字符串
- `parallel()` 只能接收 `() => agent(...)` 形式的 thunk 数组
- `pipeline()` 的 stage 签名为 `(prev, item, index) => ...`
- 允许使用普通 JavaScript 控制流：`if`、`for`、`while`、`try/catch`

### 3.3 `pipeline()` 约定

- 适合一批条目逐项执行同一链路
- 前一项可先进入下一阶段，不必等全部完成
- 用于“发现 → 转换 → 验证”这类流水线

### 3.4 `parallel()` 约定

- 仅在后续阶段必须同时拿到全部结果时使用
- 不要把纯映射、纯整理硬写成 barrier
- 默认优先 `pipeline()`，只有确需同步汇总时才用 `parallel()`

## 4. `args` 规则

- 默认不用 `args`
- 只在以下情况使用：
  - 多个 `agent()` 复用同一结构化数据
  - 需要传数组或嵌套对象
- 不要把简单标量放进 `args`
- `args` 必须是对象字面量，不要传 JSON 字符串

## 5. 原子 GIS 合同

每个交给 `@gis-tool` 的步骤，都写成一个合同块。

```markdown
## 原子 GIS 操作合同
- workflow_id:
- step_id:
- parent_goal:
- operation_type:
- required_arcgis_tool:
- input_paths:
- output_path:
- parameters:
- output_field_names:
- field_naming_convention:
- preconditions:
- expected_result:
- validation_criteria:
- retry_policy:
- downstream_dependencies:
```

### 合同规则

1. 一个合同 = 一个原子 GIS 操作
2. 输出路径只能在 `02_WorkSpace/` 或 `03_Result/`
3. 合同缺工具、输入、输出、关键参数、前置条件、验证标准时，先补齐
4. 补不齐就返回 `CONTRACT_INCOMPLETE`
5. `output_field_names` 一律写精确字段码，不自造缩写
6. `validation_criteria` 必须含字段非空率要求
7. 复杂流程必须拆成多份合同，不要在一个合同里塞完整 workflow
8. `output_path` 必须写**完整扩展名**，且全 Workflow 统一格式：
   - 矢量过程数据统一用 GDB 要素类：`02_WorkSpace/process.gdb/<name>`（禁止 .shp 与 GDB 混用）
   - 下游 `input_paths` 必须与上游 `output_path` **逐字一致**
9. 合同中禁止出现裸名（如 `gd_poly`），必须带容器路径（如 `02_WorkSpace/process.gdb/gd_poly`）

## 6. 合同与任务粒度

- 单次派发只做一个原子指标或一个计算阶段
- 单次任务尽量控制在 5~8 次 MCP 调用内
- 超出范围时拆分后再派发

## 7. 错误处理

1. `@gis-tool` 负责单步 ArcGIS 工具参数/执行错误处理
2. 若步骤失败，返回 `{ status: 'failed', step_id, error, warnings }`
3. Workflow 继续执行不依赖该步骤的分支，并把失败项加入 `errors[]`
4. 子 Agent 空返回、非结构化返回或短暂异常时，必须由 Workflow 包装器原地重试，最多 5 次
5. 完整任务最多 2 次 Workflow 调用：原始执行 1 次 + 修改原脚本后 resume 1 次；仍失败则转人工处理
6. 隐性失败要靠字段非空率检测发现

### 7.1 子 Agent 原地重试模板

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
      log((opts.label || 'agent') + ' invalid result, retry ' + attempt + '/' + maxRetries)
    } catch (e) {
      lastError = String(e && e.message ? e.message : e)
      log((opts.label || 'agent') + ' exception, retry ' + attempt + '/' + maxRetries + ': ' + lastError)
    }
  }
  return { status: 'failed', error: 'AGENT_RETRY_EXHAUSTED: ' + lastError, label: opts.label || 'agent' }
}
```

> 为保持 `resumeFromRunId` 缓存命中，重试时不要改变核心 prompt/opts；仅用 `log()` 记录 attempt。

## 8. Few-shot

### 例1：最小脚本

```javascript
export const meta = {
  name: 'single-buffer',
  description: 'Single road buffer step',
  phases: [{ title: 'Buffer', detail: 'Generate buffer' }],
}

phase('Buffer')
const result = await agent(
  '## 原子 GIS 操作合同\n- step_id: W1\n- operation_type: Buffer\n- required_arcgis_tool: arcpy.analysis.Buffer\n- input_paths: 01_DataBackup/roads.shp\n- output_path: 02_WorkSpace/buf_roads_300m\n- parameters: distance=300 Meters, dissolve=ALL\n- validation_criteria: 输出存在，要素数量 >= 1\n',
  { agentType: 'linktool-plugin:gis-tool', label: 'Buffer', phase: 'Buffer' }
)

return { summary: 'done', result }
```

### 例2：并行多个缓冲

```javascript
export const meta = {
  name: 'batch-buffer',
  description: 'Batch buffer analysis',
  phases: [{ title: 'Buffer', detail: 'Run buffers in parallel' }],
}

const layers = [
  { label: 'roads', input: '01_DataBackup/roads.shp', output: '02_WorkSpace/buf_roads', dist: '300 Meters' },
  { label: 'rivers', input: '01_DataBackup/rivers.shp', output: '02_WorkSpace/buf_rivers', dist: '100 Meters' },
]

phase('Buffer')
const buffers = await parallel(
  layers.map(layer => () => agent(
    `## 原子 GIS 操作合同\n- step_id: ${layer.label}\n- operation_type: Buffer\n- required_arcgis_tool: arcpy.analysis.Buffer\n- input_paths: ${layer.input}\n- output_path: ${layer.output}\n- parameters: distance=${layer.dist}, dissolve=ALL\n- validation_criteria: 输出存在，字段非空率 ≥ 80%\n`,
    { agentType: 'linktool-plugin:gis-tool', label: layer.label, phase: 'Buffer' }
  ))
)

return { summary: 'batch complete', buffers }
```

### 例3：多阶段分析交回上游

```javascript
export const meta = {
  name: 'site-selection-handback',
  description: 'Hand back multi-stage site selection planning',
  phases: [{ title: 'Plan', detail: 'Return to task-plan' }],
}

phase('Plan')
const r = await agent(
  '这是多阶段选址分析，不能拆成单步。请重新做任务规划。',
  { agentType: 'linktool-plugin:task-plan', label: 'Replan', phase: 'Plan' }
)

return { summary: 'handed back', r }
```

### 例4：子 Agent 原地重试包装

```javascript
export const meta = {
  name: 'fix-loop',
  description: 'Retry one failed GIS step',
  phases: [{ title: 'Process', detail: 'Run and retry once' }],
}

phase('Process')
let out = await agent(contract, { agentType: 'linktool-plugin:gis-tool', label: 'Step1', phase: 'Process' })
if (!out) {
  out = await agent(contract, { agentType: 'linktool-plugin:gis-tool', label: 'Step1-Retry', phase: 'Process' })
}

return { summary: 'retry done', out }
```

### 例5：流水线派发

```javascript
export const meta = {
  name: 'pipeline-example',
  description: 'Pipeline for parcel factors',
  phases: [
    { title: 'Prepare', detail: 'Prepare items' },
    { title: 'Process', detail: 'Run item pipeline' },
  ],
}

const items = [
  { id: 'A', input: '01_DataBackup/a.shp', output: '02_WorkSpace/a_buf' },
  { id: 'B', input: '01_DataBackup/b.shp', output: '02_WorkSpace/b_buf' },
]

phase('Process')
const result = await pipeline(
  items,
  (prev, item) => agent(
    `## 原子 GIS 操作合同\n- step_id: ${item.id}\n- operation_type: Buffer\n- required_arcgis_tool: arcpy.analysis.Buffer\n- input_paths: ${item.input}\n- output_path: ${item.output}\n- parameters: distance=100 Meters, dissolve=ALL\n- validation_criteria: 输出存在，字段非空率 ≥ 80%\n`,
    { agentType: 'linktool-plugin:gis-tool', label: item.id, phase: 'Process' }
  ),
  (prev) => prev
)

return { summary: 'pipeline complete', result }
```

## 9. Agent 白名单（强制）

> 本节对应 `plugin/CROSS_AGENT_RULES.md`，脚本生成前**必须**用以下白名单校验所有 `agentType` 值。

```javascript
// ✅ 已注册的 Agent 类型（全限定名：plugin名:Agent名）
const AGENT_WHITELIST = [
  'linktool-plugin:task-plan',        // 任务规划（仅 fork 子 Agent，非主会话直接执行分析）
  'linktool-plugin:gis-tool',         // GIS 工具执行（分析类工具唯一合法执行者）
  'linktool-plugin:data-retrieval',   // 数据摸底（只读查询）
  'linktool-plugin:gis-data-visualisation', // 可视化/制图
  'linktool-plugin:report',            // 报告生成
]
// ❌ 禁止使用（未注册或已被废弃的类型）
// 特别注意：不要使用 'linktool-plugin:task-plan' 作为分析步骤的执行者；
// task-plan 是规划者，不是分析执行者，分析必须委派给 gis-tool。
```

**生成脚本前必须校验**：
```javascript
if (!AGENT_WHITELIST.includes(agentType)) {
  throw new Error(`Agent type '${agentType}' not in whitelist. ` +
    `Use one of: ${AGENT_WHITELIST.join(', ')}`)
}
```

---

## 10. 断点续跑与前置依赖检查（强制）

> 每个 Workflow 脚本生成前必须读取 `.gis_workflow_state.json`，每个 step 前必须检查前置依赖。

**生成前**：
```javascript
// 读取状态文件
const stateFile = path.join(cwd, '02_WorkSpace', '.gis_workflow_state.json')
const state = fs.existsSync(stateFile) ? JSON.parse(fs.readFileSync(stateFile, 'utf-8')) : { tasks: {} }

// 已完成步骤直接复用（幂等性）
if (state.tasks[stepId]?.status === 'Completed') {
  return { status: 'skipped', stepId, reason: 'already completed' }
}
```

**每个 GIS step 前注入前置依赖检查**：
```javascript
// step_id=T2 depends on T1
const t1State = state.tasks['T1']
if (!t1State || t1State.status !== 'Completed') {
  throw new Error(`T2 blocked: T1 status=${t1State?.status || 'not started'}. ` +
    `Workflow must resume from last checkpoint.`)
}
```

**T8/T9 前置依赖**：
- T9（报告生成）必须在 T8（统计表）完成后执行，或在脚本中显式声明 `T9 depends on T8 output_path`

---

## 11. 反模式

- 把 Workflow 写成普通文档
- 缺少 `meta`
- 直接调用 MCP 工具
- 在脚本里问用户问题
- 把简单标量硬塞进 `args`
- 用 `parallel` 代替真正需要同步结果的场景
- Read 工具调用中传空字符串 `pages=""`（若非 PDF 或无需指定页码，完全省略 `pages` 参数）
