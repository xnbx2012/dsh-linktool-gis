import { readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import ts from 'typescript';
import type { Context } from '@deepseek-ai/cordis';
import type { Agent } from '@deepseek-ai/dsh-agent';
import type { SubagentRun, ResolvedSubagentStartRequest } from '@deepseek-ai/dsh-subagent';
import type { WorkflowMeta } from '@deepseek-ai/dsh-workflow';
import type { ToolRunContext } from '@deepseek-ai/dsh-tools';
import { textTool, atomicJson } from './tools.js';
import { benchmarkPolicy, inside, workspace, getAgent } from './catalog.js';

export interface Checkpoint { version: 1; id: string; scriptPath: string; cwd: string; attempts: number; cache: Record<string, unknown>; status: string }
export interface WorkflowEnvelope { linktoolWorkflow: 1; prompt: string; options: Record<string, unknown>; runId: string; cacheKey: string; checkpointPath: string }
/** Read the exported meta as data: no source code runs in the host process. */
export function splitWorkflow(source: string): { meta: WorkflowMeta; script: string } {
  const ast = ts.createSourceFile('workflow.js', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const declaration = ast.statements.find(s => ts.isVariableStatement(s) && s.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword) && s.declarationList.declarations.some(d => ts.isIdentifier(d.name) && d.name.text === 'meta'));
  if (!declaration || !ts.isVariableStatement(declaration) || declaration.declarationList.declarations.length !== 1) throw new Error('Workflow requires a single literal export const meta = {...}');
  if ((declaration.declarationList.flags & ts.NodeFlags.Const) === 0) throw new Error('Workflow meta must be const');
  const initializer = declaration.declarationList.declarations[0]?.initializer;
  function literal(node: ts.Node | undefined): unknown {
    if (!node) throw new Error('Missing Workflow meta initializer');
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (ts.isNumericLiteral(node)) return Number(node.text);
    if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
    if (node.kind === ts.SyntaxKind.NullKeyword) return null;
    if (ts.isArrayLiteralExpression(node)) return node.elements.map(literal);
    if (ts.isObjectLiteralExpression(node)) return Object.fromEntries(node.properties.map(p => {
      if (!ts.isPropertyAssignment(p) || !p.name || !(ts.isIdentifier(p.name) || ts.isStringLiteral(p.name))) throw new Error('Workflow meta accepts only literal property assignments');
      if (['__proto__', 'constructor', 'prototype'].includes(p.name.text)) throw new Error('Unsafe Workflow meta property');
      return [p.name.text, literal(p.initializer)];
    }));
    throw new Error('Workflow meta must be literal JSON data');
  }
  const meta = literal(initializer) as WorkflowMeta;
  if (!meta || typeof meta.name !== 'string' || typeof meta.description !== 'string') throw new Error('Workflow meta requires name and description');
  const script = source.slice(0, declaration.getFullStart()) + source.slice(declaration.end);
  if (ast.statements.some(s => ts.isImportDeclaration(s) || ts.isExportDeclaration(s))) throw new Error('Workflow imports and exports other than meta are forbidden');
  return { meta, script };
}
function checkpointPath(agent: Agent, id: string): string {
  if (!/^wf_[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid Workflow runId');
  return join(workspace(agent), '02_WorkSpace', '.linktool_workflow', id + '.json');
}
/** Native dsh isolates code; this shim preserves the CC helper vocabulary and cache contract. */
export function workflowShim(script: string, checkpoint: Checkpoint): string {
  const snapshot = JSON.stringify({ id: checkpoint.id, cache: checkpoint.cache, path: checkpointPath({ session: { header: { cwd: checkpoint.cwd } } } as Agent, checkpoint.id) });
  return `return await (async (__nativeAgent) => {
  const __checkpoint = ${snapshot};
  const __cache = __checkpoint.cache;
  const agent = async (prompt, options = {}) => {
    const allowed = ['agentType', 'label', 'phase', 'schema', 'provider', 'model'];
    for (const key of Object.keys(options)) if (!allowed.includes(key)) throw new Error('Unsupported agent option: ' + key);
    const opts = { ...options };
    if (!opts.agentType) throw new Error('LinkTool Workflow agent() requires agentType');
    const key = JSON.stringify([prompt, opts]);
    if (Object.prototype.hasOwnProperty.call(__cache, key)) { log('Cache hit: ' + (opts.label || opts.agentType)); return __cache[key]; }
    const envelope = { linktoolWorkflow: 1, prompt, options: opts, runId: __checkpoint.id, cacheKey: key, checkpointPath: __checkpoint.path };
    const result = await __nativeAgent(JSON.stringify(envelope), { label: opts.label || opts.agentType, ...(opts.phase ? { phase: opts.phase } : {}) });
    if (result === null) return null;
    const value = JSON.parse(result);
    if (value && ['success', 'skipped', 'completed'].includes(value.status)) __cache[key] = value;
    return value;
  };
  ${script}
})(agent);`;
}
export function unwrapResult(run: SubagentRun): SubagentRun {
  return { ...run, async dispose() { await run.dispose(); }, result: run.result.then(result => {
    let value: unknown = result.structured;
    if (value === undefined) {
      const text = result.output.filter(b => b.type === 'text').map(b => b.type === 'text' ? b.text : '').join('\n');
      try { value = JSON.parse(text.replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '')); } catch { value = text; }
    }
    return { ...result, output: [{ type: 'text' as const, text: JSON.stringify(value) }] };
  }) };
}
export function registerWorkflow(ctx: Context, dispatch: (name: string, request: ResolvedSubagentStartRequest) => Promise<SubagentRun>, authorize: (exec: ToolRunContext) => Promise<void> = async () => {}): void {
  ctx.subagents.registerProvider({ name: 'linktool-workflow', capabilities: { agentOptions: true, agentPreset: true, outputSchema: true, depthLimit: true }, inheritsParentContext: false, async start(request) {
    const text = request.prompt.filter(b => b.type === 'text').map(b => b.type === 'text' ? b.text : '').join('');
    const envelope: WorkflowEnvelope = JSON.parse(text);
    if (envelope.linktoolWorkflow !== 1 || typeof envelope.prompt !== 'string') throw new Error('Invalid LinkTool Workflow envelope');
    const expectedPath = checkpointPath(request.parent, envelope.runId);
    if (resolve(envelope.checkpointPath) !== expectedPath) throw new Error('Invalid checkpoint path');
    const agent = getAgent(String(envelope.options.agentType));
    if (agent.name === 'question-classify') throw new Error('question-classify is not in the original Workflow agent whitelist');
    const run = unwrapResult(await dispatch(agent.name, { ...request, prompt: [{ type: 'text', text: envelope.prompt }], ...(envelope.options.schema ? { outputSchema: envelope.options.schema as NonNullable<ResolvedSubagentStartRequest['outputSchema']> } : {}), ...((envelope.options.provider || envelope.options.model) ? { agentOptions: { ...request.agentOptions, ...(envelope.options.provider ? { provider: String(envelope.options.provider) } : {}), ...(envelope.options.model ? { model: String(envelope.options.model) } : {}) } } : {}) }));
    return { ...run, async dispose() { await run.dispose(); }, result: run.result.then(result => {
      if (result.stopReason === 'completed') {
        const value = JSON.parse(result.output.filter(b => b.type === 'text').map(b => b.type === 'text' ? b.text : '').join(''));
        if (value && ['success', 'skipped', 'completed'].includes(value.status)) {
          const state: Checkpoint = JSON.parse(readFileSync(expectedPath, 'utf8'));
          state.cache[envelope.cacheKey] = value; atomicJson(expectedPath, state);
        }
      }
      return result;
    }) };
  } });
  ctx.tools.register(textTool('Workflow', 'Run the unchanged Claude Code GIS Workflow DSL on the native sandboxed dsh engine. Supports scriptPath, agentType, phases, parallel, pipeline and one resume.', { scriptPath: { type: 'string', required: true }, args: { type: 'object', additionalProperties: true }, resumeFromRunId: { type: 'string' } }, async (args, exec: ToolRunContext) => {
    if (!exec.agent) throw new Error('Workflow requires an agent');
    const cwd = workspace(exec.agent); const scriptPath = resolve(cwd, args.scriptPath);
    if (!inside(scriptPath, cwd)) throw new Error('Workflow scriptPath must be inside the workspace');
    await authorize(exec);
    const source = readFileSync(scriptPath, 'utf8'); const parsed = splitWorkflow(source);
    if (benchmarkPolicy(exec.agent).workflows?.includes(parsed.meta.name) || benchmarkPolicy(exec.agent).workflows?.includes(args.scriptPath)) throw new Error('Benchmark ablation: named Workflow removed');
    const id = args.resumeFromRunId ?? 'wf_' + randomUUID(); const path = checkpointPath(exec.agent, id);
    let checkpoint: Checkpoint;
    if (args.resumeFromRunId) {
      if (!existsSync(path)) throw new Error('Unknown Workflow runId; cannot silently restart');
      checkpoint = JSON.parse(readFileSync(path, 'utf8'));
      if (checkpoint.cwd !== cwd || checkpoint.scriptPath !== scriptPath) throw new Error('Resume must use the original workspace and scriptPath');
      if (checkpoint.attempts >= 2 + (benchmarkPolicy(exec.agent).resume_generation ?? 0)) throw new Error('WORKFLOW_RETRY_EXHAUSTED: controller continuation allowance exhausted');
      checkpoint.attempts += 1;
    } else checkpoint = { version: 1, id, scriptPath, cwd, attempts: 1, cache: {}, status: 'running' };
    checkpoint.status = 'running'; atomicJson(path, checkpoint);
    const engine = exec.agent.ctx.get('workflowEngine') ?? ctx.get('workflowEngine');
    if (!engine) throw new Error('ENV_ERROR: native workflowEngine is unavailable');
    let run;
    try {
      run = engine.start({ script: workflowShim(parsed.script, checkpoint), meta: parsed.meta, args: args.args ?? {}, subagentProvider: 'linktool-workflow', parent: exec.agent, signal: exec.signal });
      const result = await run.result;
      const current: Checkpoint = JSON.parse(readFileSync(path, 'utf8')); current.status = result.stopReason; atomicJson(path, current);
      const progressPath = join(cwd, '02_WorkSpace', '.workflow_runs.json');
      const progress = existsSync(progressPath) ? JSON.parse(readFileSync(progressPath, 'utf8')) : [];
      progress.push({ runId: id, engineRunId: run.id, name: parsed.meta.name, status: result.stopReason, attempts: current.attempts }); atomicJson(progressPath, progress.slice(-10));
      if (result.stopReason !== 'completed') throw new Error(JSON.stringify({ status: 'failed', runId: id, error: result.error }));
      return { runId: id, engineRunId: run.id, status: 'completed', result: result.value, agentsStarted: result.agentsStarted };
    } catch (error) {
      const current: Checkpoint = JSON.parse(readFileSync(path, 'utf8'));
      current.status = 'error'; atomicJson(path, current);
      throw error;
    } finally { await run?.dispose(); }
  }));
}
