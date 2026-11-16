import { AsyncLocalStorage } from 'node:async_hooks';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import type {} from '@deepseek-ai/dsh-user-questions';
import type { SessionId } from '@deepseek-ai/dsh-session';
import type { Context } from '@deepseek-ai/cordis';
import type { Agent, AgentOptions } from '@deepseek-ai/dsh-agent';
import type { SubagentRun, SubagentActivation, ResolvedSubagentStartRequest, SubagentStartRequest } from '@deepseek-ai/dsh-subagent';
import { renderSkillContent } from '@deepseek-ai/dsh-skill';
import { resolvedServers } from './mcp.js';
import * as McpClient from '@deepseek-ai/dsh-mcp-client';
import { HookBridge } from './hooks.js';
import { benchmarkPolicy, catalog, packageRoot, resourceRoot, loadRuntime, readJson, body, getAgent, getSkill, agentName, skillAllowed, skillProvider, definition, workspace, inside, type AgentRecord, type SkillRecord, type RuntimeConfig, type HookGuardConfig } from './catalog.js';
import { textTool, registerTasks, registerResources, aliasDefinition, builtins, mcpTarget, mapArguments, toolAllowed, atomicJson } from './tools.js';
import { registerWorkflow } from './workflow.js';
import { switchesOf, type HookSwitch, type HookSwitches } from './guard.js';
import z from '@deepseek-ai/schemastery';

export const name = 'linktool-plugin';
export const inject = ['tools', 'skills', 'systemPrompt', 'subagents', 'agents'];
export interface Config { hooksEnabled?: boolean; mcpEnabled?: boolean; enabledServers?: string[]; hookGuard?: HookGuardConfig }
// Settings-page switch surface: every hookGuard field is volatile, so toggles
// commit into the running fiber without remounting the plugin (hooks would
// otherwise miss tool calls during the restart window).
export const Config = z.object({
  hooksEnabled: z.boolean().volatile().default(true),
  mcpEnabled: z.boolean().default(true),
  enabledServers: z.array(z.string()).default([]),
  hookGuard: z.object({
    pathRestrict: z.boolean().volatile().default(false).description('输出路径严格限制：仅允许 01_DataBackup（只读）/02_WorkSpace/03_Result'),
    mcpRestrict: z.boolean().volatile().default(true).description('MCP 执行限制：拦截 GIS 类命令行/代码并引导使用 GIS MCP'),
    gisToolLog: z.boolean().volatile().default(true).description('GIS 工具日志：记录每次 execute_gis_tool 调用'),
    paramValidate: z.boolean().volatile().default(true).description('参数校验：execute_gis_tool 必填参数与输入路径预检'),
    dataBackup: z.boolean().volatile().default(true).description('数据备份：破坏性 GIS 工具执行前自动备份只读数据'),
    resultValidate: z.boolean().volatile().default(true).description('结果验证：GIS 输出的属性/几何自动检查'),
    failurePattern: z.boolean().volatile().default(true).description('失败模式检测：连续失败时建议停止重试'),
    contextCompress: z.boolean().volatile().default(true).description('上下文压缩摘要：压缩后重新注入 GIS 操作历史'),
    antiBypass: z.boolean().volatile().default(true).description('绕过防护：禁止经 Write/Edit/包装脚本产出 arcpy 执行'),
    skillMdGuard: z.boolean().volatile().default(true).description('SKILL.md 保护：禁止 Read 直读技能定义文件'),
  }),
});
interface AgentState { agent: AgentRecord; parent?: Agent; activeSkill?: SkillRecord; skillArgs?: string; steps: number; approved?: boolean; registrations: Map<string, () => void>; releaseRestriction?: () => void; preparingAliases?: boolean }
interface McpConfig { type?: string; command?: string; args?: string[]; env?: Record<string, string>; cwd?: string; url?: string; headers?: Record<string, string> }
// 0.2.1-rc.5: startActivation returns a SubagentActivation; adapt it to the SubagentRun shape the rest of the adapter consumes.
// The inner activation's childId is already registered with the subagent manager, so the wrapping
// provider must surface a fresh run id — the manager rejects provider runs whose id collides with a live session.
const toRun = (activation: SubagentActivation): SubagentRun => ({ id: randomUUID() as SessionId, result: activation.result, dispose: () => activation.dispose() });

export function apply(ctx: Context, overrides: Config = {}): void {
  const config: RuntimeConfig = { ...loadRuntime(), ...overrides };
  const pending = new AsyncLocalStorage<AgentState>();
  const states = new WeakMap<Agent, AgentState>();
  const live = new Set<Agent>();
  const initializedRoots = new WeakSet<Agent>();
  const rootSkills = new WeakMap<Agent, SkillRecord>();
  const identity = (agent?: Agent) => agent ? states.get(agent)?.agent.name ?? 'main' : '';
  // Volatile hookGuard writes commit into the running fiber: keep the resolved
  // reference so the settings page flips hooks without an entry remount.
  const liveGuard = overrides.hookGuard ?? config.hookGuard;
  const guardRef = (liveGuard as unknown as { pathRestrict?: { get?(): unknown } })?.pathRestrict?.get ? liveGuard : { ...(liveGuard ?? {}) };
  const switches: HookSwitches = {
    get: (name: HookSwitch) => {
      const section = guardRef as Record<string, unknown>;
      const value = section[name];
      if (value && typeof value === 'object' && typeof (value as { get?: unknown }).get === 'function') {
        const resolved = (value as { get(): unknown }).get();
        return typeof resolved === 'boolean' ? resolved : switchesOf(config.hookGuard).get(name);
      }
      return switchesOf(config.hookGuard).get(name);
    },
  };
  const hooks = new HookBridge(ctx, config, identity, agent => agent ? states.get(agent)?.activeSkill ?? rootSkills.get(agent) : undefined, { switches });
  registerTasks(ctx);
  registerResources(ctx, config);
  const refs = new Set<string>();
  for (const doc of [...catalog.agents, ...catalog.skills]) for (const match of body(doc).matchAll(/mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_]+/g)) refs.add(match[0]);
  for (const agent of catalog.agents) for (const tool of agent.tools) if (tool.startsWith('mcp__')) refs.add(tool);
  for (const skill of catalog.skills) for (const tool of skill.allowedTools) if (tool.startsWith('mcp__')) refs.add(tool);

  const skillGrants = (name: string, state: AgentState): boolean => (state.activeSkill?.allowedTools ?? []).some(allowed => {
    if (allowed === name || mcpTarget(allowed, config) === mcpTarget(name, config)) return true;
    return name.startsWith(`mcp__${config.serverAliases[allowed] ?? allowed}__`) || name.startsWith(`mcp__plugin_linktool-plugin_${config.serverAliases[allowed] ?? allowed}__`) || (allowed === 'officecli' && ['Bash', 'Read'].includes(name));
  });
  const allowed = (name: string, state: AgentState): boolean => {
    const target = mcpTarget(name, config);
    if (state.agent.disallowedTools.some(n => n === name || mcpTarget(n, config) === target)) return false;
    if (target.endsWith('__execute_gis_tool') && ['task-plan', 'report', 'data-retrieval'].includes(state.agent.name)) return false;
    return toolAllowed(name, state.agent, config) || skillGrants(name, state) || (name === 'skill' && state.agent.tools.includes('Skill')) || (name === 'linktool_memory' && state.agent.metadata.memory === 'project');
  };
  function refresh(agent: Agent): void {
    const state = states.get(agent); if (!state || state.preparingAliases) return;
    state.preparingAliases = true;
    try {
      state.releaseRestriction?.(); state.releaseRestriction = undefined;
      for (const dispose of state.registrations.values()) dispose();
      state.registrations.clear();
      const scoped = agent.ctx;
      const wanted = new Set([...state.agent.tools, ...Object.keys(builtins).filter(n => allowed(n, state)), ...refs].filter(n => allowed(n, state)));
      for (const schema of ctx.tools.schemas(agent)) if (schema.name.startsWith('mcp__') && allowed(schema.name, state)) wanted.add(schema.name);
      for (const alias of wanted) {
        if (['ListMcpResourcesTool', 'ReadMcpResourceTool'].includes(alias)) continue;
        // DeepSeek function names are limited to 64 characters. Legacy MCP
        // identifiers remain metadata; expose only native server-qualified names.
        if (alias.startsWith('mcp__plugin_linktool-plugin_')) continue;
        if (state.registrations.has(alias) || ['Skill', 'skill', 'Agent', 'Workflow', 'ToolSearch', 'linktool_memory'].includes(alias) || alias.startsWith('Task')) continue;
        let target = mcpTarget(alias, config);
        if (target === 'bash' && !ctx.tools.get('bash', agent)) target = 'pwsh';
        const tool = ctx.tools.get(target, agent);
        if (!tool || alias === target) continue;
        state.registrations.set(alias, scoped.get('tools')!.register(aliasDefinition(alias, target, tool, () => state.activeSkill)));
      }
      // Scoped aliases are exact allowed capabilities; filter every inherited tool too.
      const globalAllowed = ctx.tools.schemas().map(t => t.name).filter(n => allowed(n, state));
      state.releaseRestriction = scoped.get('tools')!.restrict({ allow: globalAllowed });
    } finally { state.preparingAliases = false; }
  }

  async function dispatch(name: string, request: ResolvedSubagentStartRequest, skill?: SkillRecord, carryContext = false): Promise<SubagentRun> {
    const record = getAgent(name);
    if (benchmarkPolicy(request.parent).agents?.includes(record.name)) throw new Error(`Benchmark ablation: agent ${record.name} removed`);
    const options: AgentOptions = { ...request.agentOptions };
    const alias = record.metadata.model ? config.modelAliases[String(record.metadata.model)] : undefined;
    if (alias?.mode === 'route') Object.assign(options, { provider: alias.provider, model: alias.model, ...(alias.reasoningEffort ? { reasoningEffort: alias.reasoningEffort } : {}) });
    const providerName = carryContext ? 'fork' : 'spawn';
    const runtime = request.parent.ctx.get('subagents')!;
    if (!runtime.getProvider(providerName)) throw new Error(`ENV_ERROR: native ${providerName} provider unavailable`);
    const state: AgentState = { agent: record, parent: request.parent, activeSkill: skill, skillArgs: skill ? request.prompt.filter(b => b.type === 'text').map(b => b.type === 'text' ? b.text : '').join('\n') : undefined, steps: 0, registrations: new Map() };
    return pending.run(state, async () => toRun(await runtime.startActivation({ provider: providerName, label: request.label ?? record.name, delivery: 'caller', signal: request.signal, request: { ...request, agentOptions: options, maxDepth: config.maxAgentDepth } })));
  }
  function start(name: string, request: SubagentStartRequest): Promise<SubagentRun> { return ctx.subagents.startActivation({ provider: 'linktool:' + agentName(name), label: request.label ?? agentName(name), delivery: 'caller', signal: request.signal, request }).then(toRun); }
  const providerCapabilities = { agentOptions: true, agentPreset: true, outputSchema: true, depthLimit: true };
  for (const record of catalog.agents) ctx.subagents.registerProvider({ name: 'linktool:' + record.name, capabilities: providerCapabilities, inheritsParentContext: false, start: request => dispatch(record.name, request) });
  registerWorkflow(ctx, dispatch, async exec => {
    if (!exec.agent) throw new Error('Workflow requires a caller');
    if (benchmarkPolicy(exec.agent).workflow) throw new Error('Benchmark ablation: Workflow removed');
    const state = states.get(exec.agent);
    if (state?.agent.metadata.permissionMode !== 'plan') return;
    const planPath = join(workspace(exec.agent), '02_WorkSpace', 'task_plan.md');
    if (!existsSync(planPath)) throw new Error('PLAN_REQUIRED: Write task_plan.md before executing the Workflow');
    const plan = readFileSync(planPath, 'utf8'); const digest = createHash('sha256').update(plan).digest('hex');
    const approvalPath = join(workspace(exec.agent), '.dsh', 'linktool-plan-approval.json');
    if (existsSync(approvalPath) && readJson<{ digest: string }>(approvalPath).digest === digest) { state.approved = true; return; }
    // Explicit controller authorization for unattended benchmark runs only.
    if (process.env.LINKTOOL_BENCH_AUTO_APPROVE === '1' && process.env.LINKTOOL_BENCH_RUN_ID) {
      atomicJson(approvalPath, { digest, approvedBy: 'benchmark-controller', runId: process.env.LINKTOOL_BENCH_RUN_ID });
      state.approved = true; return;
    }
    const benchmarkAuthorizations = (globalThis as Record<symbol, unknown>)[Symbol.for('linktool.benchmark.authorization')] as Map<string, string> | undefined;
    const benchmarkRun = benchmarkAuthorizations?.get(exec.agent.session.id);
    if (benchmarkRun) {
      atomicJson(approvalPath, { digest, approvedBy: 'native-benchmark-controller', runId: benchmarkRun });
      state.approved = true; return;
    }
    let root = exec.agent;
    while (states.get(root)?.parent) root = states.get(root)!.parent!;
    const questions = root.ctx.get('userQuestions');
    if (!questions) throw new Error('APPROVAL_REQUIRED: user question service is unavailable; plan remains unapproved');
    const result = await questions.ask({ agent: root, signal: exec.signal, questions: [{ id: 'linktool-plan', header: 'GIS 任务计划', question: '批准以下 GIS 任务计划并执行完整 Workflow？', detail: plan, options: [{ label: '批准执行', description: '执行计划中的 GIS 操作并生成交付物。' }, { label: '暂不执行', description: '保持规划状态并返回修改意见。' }] }] });
    if (!result.answers.find(a => a.id === 'linktool-plan')?.selected.includes('批准执行')) throw new Error('PLAN_NOT_APPROVED: execution was not approved');
    atomicJson(approvalPath, { digest, approvedBy: root.session.id }); state.approved = true;
  });

  const agentTool = textTool('Agent', 'Delegate to a registered LinkTool agent. Choose subagent_type from the original linktool-plugin:<agent> names. Named agents start with no parent conversation; prompt must contain all required inputs.', { subagent_type: { type: 'string', required: true, enum: catalog.agents.map(a => 'linktool-plugin:' + a.name) }, prompt: { type: 'string', required: true }, description: { type: 'string' } }, async (args, exec) => {
    if (!exec.agent) throw new Error('Agent requires a live caller');
    const state = states.get(exec.agent);
    if (state?.agent.disallowedTools.includes('Agent') || state?.agent.name === 'task-plan') throw new Error('This agent cannot directly delegate; use its Workflow contract');
    const run = await start(args.subagent_type, { parent: exec.agent, prompt: [{ type: 'text', text: args.prompt }], label: args.description, signal: exec.signal });
    try { const result = await run.result; if (result.stopReason !== 'completed') throw new Error(`LinkTool agent stopped: ${result.stopReason}${result.diagnostic ? ': ' + result.diagnostic : ''}`); return result.structured ?? result.output; } finally { await run.dispose(); }
  });
  ctx.tools.register(agentTool);
  ctx.tools.register({ ...agentTool, name: 'linktool_agent' });

  async function invokeSkill(name: string, args: string, agent: Agent, signal: AbortSignal): Promise<unknown> {
    const skill = getSkill(name); const state = states.get(agent);
    if (benchmarkPolicy(agent).skills?.includes(skill.name)) throw new Error(`Benchmark ablation: skill ${skill.name} removed`);
    if (!skill.invocation.modelInvocable || !skillAllowed(skill, state?.agent, config)) throw new Error(`Skill ${name} is unavailable to ${identity(agent)}`);
    if (skill.context !== 'fork') {
      if (state) { state.activeSkill = skill; state.skillArgs = args; atomicJson(join(workspace(agent), '.dsh', 'linktool-agents', agent.session.id + '.json'), { agent: state.agent.name, skill: skill.name, skillArgs: args }); refresh(agent); }
      else rootSkills.set(agent, skill);
      return renderSkillContent({ ...definition(skill), content: body(skill).replaceAll('$ARGUMENTS', args) });
    }
    const record = skill.agent ? getAgent(skill.agent) : state?.agent;
    if (!record) throw new Error(`Fork skill ${name} has no agent binding`);
    const providerName = `linktool-skill:${skill.name}`;
    const run = toRun(await ctx.subagents.startActivation({ provider: providerName, label: skill.name, delivery: 'caller', signal, request: { parent: agent, prompt: [{ type: 'text', text: args || `执行技能 ${skill.name}。调用者必须通过 args 显式传入所需输入；没有输入时返回需要补充的信息。` }] } }));
    try { const result = await run.result; if (result.stopReason !== 'completed') throw new Error(`Fork skill stopped: ${result.stopReason}`); return result.structured ?? result.output; } finally { await run.dispose(); }
  }
  for (const skill of catalog.skills.filter(s => s.context === 'fork')) ctx.subagents.registerProvider({ name: 'linktool-skill:' + skill.name, capabilities: providerCapabilities, inheritsParentContext: false, async start(request) {
    if (benchmarkPolicy(request.parent).skills?.includes(skill.name)) throw new Error('Benchmark ablation: fork skill removed');
    const caller = states.get(request.parent)?.agent;
    if (!skillAllowed(skill, caller, config)) throw new Error('Skill agent binding denied');
    const record = skill.agent ? getAgent(skill.agent) : caller;
    if (!record) throw new Error('Fork skill has no named agent');
    return dispatch(record.name, request, skill);
  } });
  const skillTool = textTool('Skill', 'Load a LinkTool skill. Inline skills use the current conversation; context:fork skills execute with their declared agent in an independent conversation. Pass the task and all required data in args.', { skill: { type: 'string', required: true }, args: { type: 'string' } }, async (args, exec) => { if (!exec.agent) throw new Error('Skill requires an agent'); return invokeSkill(args.skill, args.args ?? '', exec.agent, exec.signal); });
  ctx.tools.register(skillTool);
  ctx.skills.registerProvider(() => skillProvider(undefined, config));

  ctx.on('agent/created', async ({ agent }) => {
    let state = pending.getStore();
    const parent = state?.parent ?? ctx.agents.currentInitiator();
    const policyMap = (globalThis as Record<symbol, unknown>)[Symbol.for('linktool.benchmark.policies')] as Map<string, unknown> | undefined;
    if (parent && policyMap?.has(parent.session.id)) policyMap.set(agent.session.id, policyMap.get(parent.session.id));
    const roleMap = ((globalThis as Record<symbol, unknown>)[Symbol.for('linktool.benchmark.roles')] ??= new Map()) as Map<string,string>;
    const removal = benchmarkPolicy(agent);
    agent.ctx.get('tools')!.guard(exec => {
      const target=mcpTarget(exec.name,config);
      if (removal.tools?.includes(exec.name) || removal.tools?.includes(target) || removal.mcp?.some(n => target.startsWith(`mcp__${config.serverAliases[n] ?? n}__`))) return 'Benchmark ablation: tool/MCP removed';
      if (removal.workflow && /workflow/i.test(exec.name)) return 'Benchmark ablation: Workflow removed';
      return undefined;
    });
    const rolePath = join(workspace(agent), '.dsh', 'linktool-agents', agent.session.id + '.json');
    if (!state && existsSync(rolePath)) {
      const saved = readJson<{ agent: string; skill?: string; skillArgs?: string }>(rolePath);
      state = { agent: getAgent(saved.agent), activeSkill: saved.skill ? getSkill(saved.skill) : undefined, skillArgs: saved.skillArgs, steps: 0, registrations: new Map() };
    }
    roleMap.set(agent.session.id, state?.agent.name ?? 'main');
    const observer=(globalThis as Record<symbol,unknown>)[Symbol.for('linktool.benchmark.observe')] as ((sid:string,type:string,data:unknown)=>void)|undefined;
    observer?.(agent.session.id,'agent/role',{session_id:agent.session.id,agent_label:state?.agent.name ?? 'main'});
    if (!state) {
      if (initializedRoots.has(agent)) return undefined;
      initializedRoots.add(agent);
      for (const alias of [...Object.keys(builtins), ...refs]) {
        if (['ListMcpResourcesTool', 'ReadMcpResourceTool'].includes(alias)) continue;
        if (alias.startsWith('mcp__plugin_linktool-plugin_')) continue;
        let target = mcpTarget(alias, config);
        if (target === 'bash' && !ctx.tools.get('bash', agent)) target = 'pwsh';
        const tool = ctx.tools.get(target, agent);
        if (tool && alias !== target) agent.ctx.get('tools')!.register(aliasDefinition(alias, target, tool, () => rootSkills.get(agent)));
      }
      agent.ctx.get('tools')!.register(skillTool);
      agent.ctx.get('tools')!.register(textTool('skill', 'LinkTool-aware skill loader: preserves context:fork execution and inline skill loading.', { name: { type: 'string', required: true }, args: { type: 'string' } }, async (args, exec) => {
        if (!exec.agent) throw new Error('Missing agent');
        if (catalog.skills.some(s => s.name === args.name)) return invokeSkill(args.name, args.args ?? '', exec.agent, exec.signal);
        const other = await exec.agent.ctx.get('skills')!.get(args.name, { cwd: workspace(exec.agent), scope: exec.agent, signal: exec.signal });
        if (!other || !other.invocation.modelInvocable) throw new Error('Skill unavailable');
        return renderSkillContent(other);
      }));
      return undefined;
    }
    if (states.has(agent)) return undefined;
    states.set(agent, state); live.add(agent);
    const current = state;
    atomicJson(rolePath, { agent: current.agent.name, ...(current.activeSkill ? { skill: current.activeSkill.name, skillArgs: current.skillArgs ?? '' } : {}) });
    const scoped = agent.ctx;
    // Shadow deployment persona; keep all original whitespace and literal {{...}} intact.
    scoped.get('systemPrompt')!.section({ name: 'deployment:persona-prefix', order: 0, text: body(state.agent), interpolate: false });
    for (const skillName of state.agent.skills.filter(n => !removal.skills?.includes(n))) { const skill = getSkill(skillName); scoped.get('systemPrompt')!.section({ name: 'linktool:preload:' + skill.name, order: 50, text: body(skill), interpolate: false }); }
    if (state.activeSkill) {
      const input = pending.getStore()?.activeSkill;
      scoped.get('systemPrompt')!.section({ name: 'linktool:active-skill', order: 51, text: body(input ?? current.activeSkill!).replaceAll('$ARGUMENTS', current.skillArgs ?? ''), interpolate: false });
    }
    scoped.get('systemPrompt')!.section({ name: 'linktool:runtime', order: 60, interpolate: false, text: `迁移运行时信息（原始角色与技能正文未修改）：\nAgent 标识：linktool-plugin:${state.agent.name}\n工作目录：${workspace(agent)}\n插件资源根目录：${resourceRoot}\n原始 plugin/ 路径由工具适配层解析至插件资源；Skill 内 ./scripts/ 相对于技能目录解析。\n显式调用独立上下文 Skill 时，args 必须传入完整任务和输入；不要认为独立上下文会复制当前聊天历史。\nAgent 的 skills 列表已按原配置预加载完整正文；其他技能按需加载。\n仅使用当前工具清单；没有暴露的工具不得通过其他途径绕过。${state.agent.metadata.model ? `\n原模型别名：${state.agent.metadata.model}；当前路由：${JSON.stringify(config.modelAliases[String(state.agent.metadata.model)] ?? { mode: 'inherit' })}。` : ''}` });
    scoped.get('skills')!.registerProvider(() => skillProvider(state.agent, config));
    scoped.get('systemPrompt')!.section({ name: 'linktool:skill-catalog', order: 61, interpolate: false, text: catalog.skills.filter(s => !removal.skills?.includes(s.name) && skillAllowed(s, state.agent, config) && s.invocation.modelInvocable).map(s => `Skill ${s.name} (context=${s.context}, agent=${s.agent ?? 'current'}): ${String(s.metadata.description ?? '')}`).join('\n') });
    scoped.get('systemPrompt')!.section({ name: 'linktool:mcp-names', order: 62, interpolate: false, text: `原正文的 MCP 名称作为语义标识保留。执行时必须使用实际 Harness 短工具名（DeepSeek 函数名称最多 64 字符），仅调用当前工具清单存在的项目：\n${[...refs].filter(n => allowed(n, current)).map(n => `${n} → ${mcpTarget(n, config)}`).join('\n')}` });
    if (state.agent.tools.includes('Skill')) {
      scoped.get('tools')!.register(skillTool);
      scoped.get('tools')!.register(textTool('skill', 'LinkTool scoped skill loader; context and agent binding are enforced.', { name: { type: 'string', required: true }, args: { type: 'string' } }, async (args, exec) => { if (!exec.agent) throw new Error('Missing agent'); return invokeSkill(args.name, args.args ?? '', exec.agent, exec.signal); }));
    }
    if (state.agent.tools.includes('ToolSearch')) scoped.get('tools')!.register(textTool('ToolSearch', 'Inspect actual registered tool schemas; unavailable servers are not presented as working tools.', { query: { type: 'string', required: true }, max_results: { type: 'integer' } }, async (args, exec) => ctx.tools.schemas(exec.agent).filter(t => t.name.includes(args.query) || t.description?.includes(args.query)).slice(0, args.max_results ?? 10)));
    if (state.agent.metadata.memory === 'project') {
      const path = join(workspace(agent), '.dsh', 'agent-memory', state.agent.name, 'MEMORY.md');
      scoped.get('systemPrompt')!.section({ name: 'linktool:project-memory', order: 55, interpolate: false, text: () => existsSync(path) ? readFileSync(path, 'utf8') : '' });
      scoped.get('tools')!.register(textTool('linktool_memory', 'Read or replace this agent project memory. Shared by this agent in the current project only.', { content: { type: 'string' } }, async args => { if (args.content !== undefined) { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, args.content); } return existsSync(path) ? readFileSync(path, 'utf8') : ''; }));
    }
    scoped.get('tools')!.guard(exec => {
      if (!allowed(exec.name, current)) return `Tool ${exec.name} denied by LinkTool agent ${current.agent.name}`;
      const args = mapArguments(mcpTarget(exec.name, config), exec.arguments, exec.agent, current.activeSkill);
      if (current.agent.metadata.permissionMode === 'plan' && !current.approved) {
        if (exec.name.endsWith('__execute_gis_tool')) return 'Agent is in planning mode';
        if (['Write', 'write', 'Edit', 'edit', 'Update'].includes(exec.name) && typeof args.file_path === 'string' && !/[/\\]02_WorkSpace[/\\](task_plan\.md|workflow_script\.js)$/.test(args.file_path)) return 'Planning mode only permits task_plan.md and workflow_script.js';
      }
      for (const field of ['file_path', 'path']) if (typeof args[field] === 'string' && ['Write', 'write', 'Edit', 'edit', 'Update'].includes(exec.name) && inside(args[field] as string, resourceRoot)) return 'Packaged plugin resources are read-only';
      return undefined;
    });
    scoped.on('agent/pre-step', async ({ step }, next) => {
      const decision = await next();
      if (decision.kind !== 'enter') return decision;
      if (typeof current.agent.metadata.maxTurns === 'number' && ++current.steps > current.agent.metadata.maxTurns) return { kind: 'reject' };
      return decision;
    });
    refresh(agent);
    return undefined;
  });
  ctx.on('agent/disposed', ({ agent }) => { live.delete(agent); });
  let refreshing = false;
  ctx.on('tools/change', () => { if (refreshing) return; refreshing = true; try { for (const agent of live) refresh(agent); } finally { refreshing = false; } });
  hooks.install();
  // A user slash invocation must honor the same independent-context contract.
  ctx.on('agent/pre-step', async ({ agent, messages, signal }, next) => {
    const forkMessages = messages.filter(m => { if (m.source.kind !== 'skill-invocation') return false; const invokedName = m.source.name; return catalog.skills.some(s => s.name === invokedName && s.context === 'fork'); });
    if (!forkMessages.length) return next();
    const outputs = [];
    for (const message of forkMessages) {
      if (message.source.kind !== 'skill-invocation') continue;
      const args = messages.filter(m => m.source.kind !== 'skill-invocation').flatMap(m => m.content).filter(b => b.type === 'text').map(b => b.type === 'text' ? b.text : '').join('\n');
      outputs.push(hooks.message(JSON.stringify(await invokeSkill(message.source.name, args, agent, signal))));
    }
    const downstream = await next();
    if (downstream.kind !== 'enter') return downstream;
    return { ...downstream, messages: [...downstream.messages.filter(m => !forkMessages.some(f => f.id === m.id)), ...outputs] };
  });

  ctx.systemPrompt.section({ name: 'linktool:entry', order: 100, interpolate: false, text: `LinkTool GIS 专用插件已加载。GIS 请求使用 Agent 工具委派 linktool-plugin:question-classify；明确指定的角色可直接委派。角色列表：\n${catalog.agents.map(a => `- linktool-plugin:${a.name}: ${String(a.metadata.description ?? '')}`).join('\n')}\n完整复杂任务由 task-plan 通过迁移后的 Workflow 工具执行。提示词中原始工具名仍可由相应 Agent 使用。` });
  ctx.systemPrompt.section({ name: 'linktool:mcp-names', order: 101, interpolate: false, text: `实际 MCP 调用使用 Harness 短工具名；原提示词名称映射如下，仅调用当前已注册的工具：\n${[...refs].map(n => `${n} → ${mcpTarget(n, config)}`).join('\n')}` });
  if (config.mcpEnabled) {
    for (const [server, resolved] of Object.entries(resolvedServers())) {
      if (config.enabledServers.includes(server)) ctx.plugin(McpClient, resolved as unknown as McpClient.Config);
    }
  }
}
