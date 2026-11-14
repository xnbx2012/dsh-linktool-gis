# 静态 Workflow 模板

本目录存放 Claude Code `Workflow` 工具的静态模板。`@task-plan` 根据任务类型选择最匹配的模板，生成实际执行的 `workflow_script.js` 并提交 `Workflow` 工具。

## 模板清单

| 模板 | 适用场景 |
|------|---------|
| `gis-standard-analysis.md` | 完整 GIS 空间分析（选址、适宜性评价、多因子叠加等） |
| `gis-data-profile-only.md` | 仅数据理解/数据画像，不执行 GIS 分析 |
| `gis-tool-execution-only.md` | 已知工具链的批量 GIS 工具执行 |
| `gis-visual-report.md` | 已有结果的可视化/报告交付 |
| `gis-debug-analysis.md` | 全流程调试模式，每阶段 log() 输出状态供调试追踪 |

## 模式选择规则

```
用户 GIS 需求
  ├─→ 完整分析任务 → gis-standard-analysis.md
  ├─→ 仅了解数据 → gis-data-profile-only.md
  ├─→ 已知工具链批量执行 → gis-tool-execution-only.md
  ├─→ 可视化/报告交付 → gis-visual-report.md
  ├─→ 调试/验证/对比测试 → gis-debug-analysis.md
  └─→ 强定制任务（无法匹配以上）→ 生成动态 workflow_script.js
```

## 模板结构规范

每个模板文档应包含：

1. **适用场景**：明确什么任务类型适合使用该模板
2. **流程图**：用文本流程图描述步骤顺序和分支
3. **输入/输出**：明确需要什么输入、产出什么输出
4. **子 Agent 调用关系表**：每个 Phase 对应的 Agent 和职责
5. **Workflow 参考脚本**：给出 Claude Code Workflow JS 的参考结构
6. **失败处理**：描述各阶段的失败处理策略（必须包含断点续跑协议）
7. **断点续跑**：描述 `resumeFromRunId` 的使用方式和约束

## 动态 Workflow

当任务无法用静态模板覆盖时，由 `@task-plan` 在 `02_WorkSpace/workflow_script.js` 中生成动态 Workflow。

动态 Workflow 规范：
- 完整复杂 GIS 任务必须生成**单一全流程 Workflow**，覆盖 Prepare / Process / Analyze / Deliver / Verify；禁止用多个短 Workflow 串联完成主体任务
- 必须包含 `export const meta = {...}` 和 `phase()` 调用
- 必须使用 `agent(..., { agentType: '...' })` 调度多个专用 Agent；禁止一个 Agent 包办数据、分析、制图、报告、验证全流程
- 禁止在脚本中绕过 `@gis-tool` 直接调用 `execute_gis_tool`
- 每个子 Agent 调用必须通过结构化结果校验；空返回、非对象返回或短暂异常必须原地重试，最多 5 次
- 建议使用 `pipeline()` 或 `parallel()` 而非人工屏障
- `task_plan.md` 是审批材料，`workflow_script.js` 是执行对象
- `@task-plan` 通过 `Workflow({ args: { ... } })` 传入数据，脚本内用 `args.xxx` 访问
- **`args` 格式硬性约束**：`args` 必须传入 JS 对象字面量 `{ ... }`，禁止传入 JSON 字符串（如 `args: '{"key": "value"}'`）。字符串形式导致脚本内 `args.xxx` 全部为 `undefined`。简单值优先硬编码到 prompt，不依赖 `args`
- 禁止 `Date.now()`、`Math.random()`、文件系统 API、TypeScript 类型注解

## 断点续跑 (Resume from Failure)

所有 Workflow 模板均支持 `resumeFromRunId` 断点续跑机制。当 Workflow 执行失败时，不需要重新运行整个 Workflow——已完成的 `agent()` 调用由引擎缓存直接返回，仅修复的步骤重新执行。

### 工作原理

```javascript
// 第一次执行
const result1 = await Workflow({ scriptPath: '02_WorkSpace/workflow_script.js', args })
// result1.runId = 'wf_abc123'

// 失败后，编辑脚本修复问题，然后 resume
const result2 = await Workflow({
  scriptPath: '02_WorkSpace/workflow_script.js',
  resumeFromRunId: result1.runId,  // 'wf_abc123'
  args: { ...args, isResume: true, resumeAttempt: 1, originalRunId: result1.runId }
})
```

Workflow 引擎会比较每个 `agent()` 调用的 (prompt, opts) 哈希：
- **哈希未变** → 返回缓存结果，不创建子 Agent
- **哈希已变** → 重新执行
- **新增调用** → 正常执行

### 约束

- 脚本中**禁止**使用 `Date.now()`、`Math.random()` 等（否则缓存匹配失效）
- `export const meta` 必须是纯字面量
- 最多 1 次 resume 续跑（总共 2 次 Workflow 调用：原始 + 1 次 resume）
- 必须在**同一会话**中 resume
- **禁止**生成新的 remediation/fix workflow 文件替代原脚本

### 失败处理流程

```
Workflow 失败
  → @task-plan 自动分析失败原因（工具选择/参数/数据/前置条件/Agent 超时）
  → 向用户展示错误摘要 + 修复方案，等待确认
  → 用户确认后 Edit 原 workflow_script.js
  → Workflow({ scriptPath, resumeFromRunId }) 续跑
  → 成功：进入意图验证
  → 仍失败：不得再启动第三次 Workflow，报告用户并附完整失败摘要
```

详细协议参见 `plugin/agents/task-plan.md` Section 4.3.1。

### 各模板续跑支持

| 模板 | 续跑支持 | 说明 |
|------|---------|------|
| `gis-standard-analysis.md` | 完全支持 | 完整的断点续跑协议 |
| `gis-debug-analysis.md` | 完全支持 | 调试模式下额外展示状态快照和脚本 diff |
| `gis-tool-execution-only.md` | 完全支持 | 单 phase 结构，续跑最简单 |
| `gis-data-profile-only.md` | 完全支持 | 单 step，失败通常无需 resume |
| `gis-visual-report.md` | 完全支持 | 可视化/报告可独立 resume |