import { spawn } from 'node:child_process';
import { join } from 'node:path';
import type { Context } from '@deepseek-ai/cordis';
import type { Agent } from '@deepseek-ai/dsh-agent';
import type { ToolExecution, ToolExecutionResult } from '@deepseek-ai/dsh-tools';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import type {} from '@deepseek-ai/dsh-compaction';
import { mapArguments, mcpTarget } from './tools.js';
import { expandPaths, childEnvironment } from './paths.js';
import { benchmarkPolicy, packageRoot, resourceRoot, readJson, sessionKey, workspace, type RuntimeConfig, type SkillRecord } from './catalog.js';
import { guardPreToolUse, hookSwitchOf, switchesOf, type HookSwitches } from './guard.js';

declare module '@deepseek-ai/dsh-llm' { interface MessageSourceMap { 'linktool-hook': { kind: 'linktool-hook'; form: 'instructions' } } }
interface Hook { type: string; command: string; timeout?: number; async?: boolean }
interface Binding { matcher?: string; hooks: Hook[] }
interface HookOutput { hookSpecificOutput?: { permissionDecision?: string; permissionDecisionReason?: string; additionalContext?: string; updatedInput?: unknown }; decision?: string; reason?: string; additionalContext?: string; continue?: boolean; stopReason?: string }
export interface HookResult { deny?: string; contexts: string[] }
const names: Record<string, string> = { read: 'Read', read_image: 'Read', write: 'Write', edit: 'Edit', glob: 'Glob', grep: 'Grep', bash: 'Bash', pwsh: 'Bash', str_replace_editor: 'Edit' };
export function legacyTool(name: string): string {
  if (name === 'Wrtie') return 'Write';
  if (name === 'Update') return 'Edit';
  if (names[name]) return names[name];
  if (/^mcp__/.test(name) && !name.startsWith('mcp__plugin_linktool-plugin_')) return name.replace(/^mcp__([^_]+(?:-[^_]+)*)__/, 'mcp__plugin_linktool-plugin_$1__');
  return name;
}
/** Trusted packaged command hooks use the original stdin contract and UTF-8. */
export async function runCommand(command: string, payload: unknown, cwd: string, signal: AbortSignal, timeout: number, agentName = ''): Promise<{ code: number; stdout: string; stderr: string }> {
  const expanded = expandPaths(command, cwd);
  const isWindows = process.platform === 'win32';
  return new Promise((resolve, reject) => {
    const child = spawn(isWindows ? (process.env.ComSpec ?? 'cmd.exe') : '/bin/sh', isWindows ? ['/d', '/s', '/c', expanded] : ['-c', expanded], { cwd, windowsHide: true, windowsVerbatimArguments: isWindows, env: childEnvironment(cwd, agentName), stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = ''; let stderr = ''; let failure: Error | undefined;
    const terminate = () => {
      failure ??= new Error('Hook cancelled or timed out');
      if (isWindows && child.pid) { const killer = spawn('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' }); killer.on('error', () => child.kill()); } else child.kill('SIGTERM');
    };
    const timer = setTimeout(terminate, timeout); timer.unref();
    signal.addEventListener('abort', terminate, { once: true });
    child.stdout.on('data', b => { stdout += b.toString('utf8'); if (stdout.length > 2_000_000) terminate(); });
    child.stderr.on('data', b => { stderr = (stderr + b.toString('utf8')).slice(-16000); });
    child.stdin.on('error', () => {});
    child.on('error', e => { failure = e; });
    child.on('close', code => { clearTimeout(timer); signal.removeEventListener('abort', terminate); if (failure) reject(failure); else resolve({ code: code ?? 1, stdout, stderr }); });
    child.stdin.end(JSON.stringify(payload));
    if (signal.aborted) terminate();
  });
}
export class HookBridge {
  readonly bindings: Record<string, Binding[]>;
  /** Live settings-page switches; defaults come from runtime.json until volatile config writes arrive. */
  readonly switches: HookSwitches;
  constructor(private readonly ctx: Context, private readonly config: RuntimeConfig, private readonly identity: (agent: Agent | undefined) => string, private readonly currentSkill: (agent: Agent | undefined) => SkillRecord | undefined = () => undefined, live?: { switches: HookSwitches }) { this.bindings = readJson<{ hooks: Record<string, Binding[]> }>(join(packageRoot, 'config/hooks.json')).hooks; this.switches = live?.switches ?? switchesOf(config.hookGuard); }
  async run(event: string, exec?: ToolExecution, result?: Readonly<ToolExecutionResult>, agent?: Agent, signal: AbortSignal = new AbortController().signal): Promise<HookResult> {
    const owner = agent ?? exec?.agent;
    // The matched code baseline is authorized to execute ArcPy code. It must
    // not inherit LinkTool's atomic-tool-only anti-bypass treatment.
    const benchmarkRoutes = (globalThis as Record<symbol, unknown>)[Symbol.for('linktool.benchmark.architectures')] as Map<string, string | undefined> | undefined;
    if (owner && benchmarkRoutes?.get(sessionKey(owner)) === 'code') return { contexts: [] };
    const name = exec ? legacyTool(exec.name) : 'auto';
    const payload = { session_id: sessionKey(owner), transcript_path: '', cwd: workspace(owner), hook_event_name: event, agent_name: this.identity(owner), agent: this.identity(owner), tool_name: name, tool_use_id: exec?.callId ?? '', tool_input: exec ? mapArguments(mcpTarget(exec.name, this.config), exec.arguments, owner, this.currentSkill(owner)) : {}, ...(result ? { tool_response: { content: result.content, isError: result.isError, ...('value' in result ? { structuredContent: result.value } : {}), ...('error' in result ? { error: result.error } : {}) } } : {}) };
    // enhanced_record.py reads tool_input.tool_response; other CC hooks read
    // the top-level field. Supply both without modifying the preserved source.
    if (result) payload.tool_input.tool_response = payload.tool_response;
    const merged: HookResult = { contexts: [] };
    if (!this.config.hooksEnabled) return merged;
    for (const [bindingIndex, binding] of (this.bindings[event] ?? []).entries()) {
      if (binding.matcher && binding.matcher !== '*' && !new RegExp(`^(?:${binding.matcher})$`).test(name)) continue;
      for (const [hookIndex, hook] of binding.hooks.entries()) {
        const hookId=event+':'+bindingIndex+':'+hookIndex;
        // Settings-page switch: each bundled hook can be turned off without
        // reinstalling; unknown hooks keep the shipped always-on behavior.
        const hookSwitch = hookSwitchOf(hook.command);
        if (hookSwitch && !this.switches.get(hookSwitch)) continue;
        if (benchmarkPolicy(owner).hooks?.includes(hookId)) continue;
        const observer=(globalThis as Record<symbol,unknown>)[Symbol.for('linktool.benchmark.observe')] as ((sid:string,type:string,data:unknown)=>void)|undefined;
        const hookStart=performance.now();
        if (hook.type !== 'command' || hook.async) throw new Error(`Unsupported hook execution type in ${event}`);
        const run = await runCommand(hook.command, payload, workspace(owner), signal, (hook.timeout ?? this.config.hookTimeoutMs / 1000) * 1000, this.identity(owner));
        observer?.(sessionKey(owner), 'hook/end', { hook_id:hookId,event,session_id:sessionKey(owner),duration_ms:performance.now()-hookStart,exit_code:run.code });
        let output: HookOutput = {};
        if (run.stdout.trim().startsWith('{')) {
          try { output = JSON.parse(run.stdout); } catch { this.ctx.logger.warn(`LinkTool ${event}: non-JSON hook stdout`); }
        }
        const specific = output.hookSpecificOutput;
        if (specific?.updatedInput !== undefined) throw new Error(`LinkTool ${event}: updatedInput requires a dedicated input adapter`);
        if (run.code === 2 || output.decision === 'block' || specific?.permissionDecision === 'deny' || output.continue === false) {
          merged.deny = specific?.permissionDecisionReason ?? output.reason ?? output.stopReason ?? run.stderr.trim() ?? 'Hook denied operation';
          if (event === 'PreToolUse') return merged;
        } else if (run.code !== 0) {
          // CC command-hook exit 1 reports an internal error without blocking;
          // exit 2 and explicit permissionDecision=deny remain blocking.
          this.ctx.logger.warn(`LinkTool ${event}: hook exited ${run.code}: ${run.stderr}`);
          merged.contexts.push(`LinkTool ${event} hook execution failed (exit ${run.code}): ${run.stderr}`);
        }
        const context = specific?.additionalContext ?? output.additionalContext;
        if (context) merged.contexts.push(context);
      }
    }
    return merged;
  }
  install(): void {
    // Adapter-level guard: hard danger floor plus switchable GIS-command
    // interception, evaluated before any bundled hook spawns a Python process.
    this.ctx.on('tools/pre-execute', async (exec, next) => {
      if (!this.identity(exec.agent)) return next();
      const blocked = await guardPreToolUse(exec, this.switches, name => mapArguments(mcpTarget(name, this.config), exec.arguments, exec.agent, this.currentSkill(exec.agent)));
      if (blocked) return { kind: 'deny', reason: blocked };
      return next();
    });
    this.ctx.on('tools/pre-execute', async (exec, next) => {
      if (!this.identity(exec.agent)) return next();
      const result = await this.run('PreToolUse', exec, undefined, undefined, exec.signal);
      if (result.deny) return { kind: 'deny', reason: result.deny };
      // Current source has no pre-tool additionalContext; fail explicitly if configured later.
      if (result.contexts.length) exec.agent?.inject(this.message(result.contexts.join('\n')));
      return next();
    });
    this.ctx.on('tools/post-execute', async (exec, result, next) => {
      if (!this.identity(exec.agent)) return next();
      const hook = await this.run('PostToolUse', exec, result, undefined, exec.signal);
      const contexts = hook.contexts.map(text => this.message(text));
      if (hook.deny) return { kind: 'block', feedback: [{ type: 'text', text: hook.deny }], additionalContexts: contexts };
      const downstream = await next();
      return { ...downstream, additionalContexts: [...contexts, ...(downstream.additionalContexts ?? [])] };
    });
    const pending = new Set<string>();
    this.ctx.on('session/event', (session, event) => { if (event.type === 'compaction/end' && !event.data.error) pending.add(session?.id ?? ''); });
    this.ctx.on('agent/pre-step', async ({ agent, signal }, next) => {
      const decision = await next();
      if (!pending.has(sessionKey(agent)) || !this.identity(agent) || decision.kind !== 'enter') return decision;
      const hook = await this.run('PostCompact', undefined, undefined, agent, signal);
      pending.delete(sessionKey(agent));
      return { ...decision, messages: [...decision.messages, ...hook.contexts.map(text => this.message(text))] };
    });
    this.ctx.on('agent/created', async ({ agent, source, signal }) => {
      if (source === 'compact' && this.identity(agent)) {
        pending.delete(sessionKey(agent));
        const hook = await this.run('PostCompact', undefined, undefined, agent, signal);
        for (const text of hook.contexts) agent.inject(this.message(text));
      }
      return undefined;
    });
  }
  message(text: string) { return createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'linktool-hook', form: 'instructions' } }); }
}
