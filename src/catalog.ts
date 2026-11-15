import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve, join, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import type { Agent } from '@deepseek-ai/dsh-agent';
import type { SkillDefinition, SkillProvider } from '@deepseek-ai/dsh-skill';
import { expandPaths } from './paths.js';
import { BUNDLED_SKILL_RANK } from '@deepseek-ai/dsh-skill';

export const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const resourceRoot = join(packageRoot, 'resources', 'plugin');
export interface Document { path: string; metadata: Record<string, unknown>; bodySha256: string; fileSha256: string; name: string }
export interface AgentRecord extends Document { tools: string[]; disallowedTools: string[]; skills: string[]; mcpServers: string[] }
export interface SkillRecord extends Document { agent: string | null; context: string; allowedTools: string[]; invocation: { modelInvocable: boolean; userInvocable: boolean } }
export interface RuntimeConfig {
  hooksEnabled: boolean; mcpEnabled: boolean; enabledServers: string[];
  modelAliases: Record<string, { mode: 'inherit' } | { mode: 'route'; provider: string; model: string; reasoningEffort?: string }>;
  serverAliases: Record<string, string>; toolAliases: Record<string, string>;
  agentSkillRules: Record<string, string[]>; maxAgentDepth: number; hookTimeoutMs: number;
}
export const catalog: { name: string; version: string; agents: AgentRecord[]; skills: SkillRecord[]; workflows: string[] } = JSON.parse(readFileSync(join(packageRoot, 'config', 'catalog.json'), 'utf8'));
export const readJson = <T>(path: string): T => JSON.parse(readFileSync(path, 'utf8'));
export function loadRuntime(): RuntimeConfig { return readJson(join(packageRoot, 'config', 'runtime.json')); }
export function body(doc: Document): string {
  const text = readFileSync(join(resourceRoot, doc.path), 'utf8').replace(/^\uFEFF/, '');
  const match = /^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/.exec(text);
  const content = match ? text.slice(match[0].length) : text;
  // \u54C8\u5E0C\u524D\u5F52\u4E00\u5316\u884C\u5C3E\uFF1Agit \u68C0\u51FA\uFF08autocrlf/eol \u5C5E\u6027\uFF09\u4E0E zip \u89E3\u538B\u53EF\u80FD\u6539\u53D8\u6B63\u6587\u884C\u5C3E\uFF0C
  // \u63D0\u793A\u8BCD\u8BED\u4E49\u4E0D\u53D7\u5F71\u54CD\uFF1BbodySha256 \u7EDF\u4E00\u6309 LF \u6B63\u6587\u8BB0\u5F55\u3002
  if (createHash('sha256').update(content.replace(/\r\n/g, '\n')).digest('hex') !== doc.bodySha256) throw new Error(`Prompt integrity mismatch: ${doc.path}. Rebuild the catalog deliberately after source changes.`);
  return content;
}
export function agentName(name: string): string { return name.replace(/^@/, '').replace(/^linktool-plugin:/, '').replace(/^linktool:/, ''); }
export function getAgent(name: string): AgentRecord {
  const doc = catalog.agents.find(a => a.name === agentName(name));
  if (!doc) throw new Error(`Unknown LinkTool agent: ${name}`);
  return doc;
}
export function getSkill(name: string): SkillRecord {
  const doc = catalog.skills.find(s => s.name === name.replace(/^linktool-plugin:/, ''));
  if (!doc) throw new Error(`Unknown LinkTool skill: ${name}`);
  return doc;
}
export function skillAllowed(skill: SkillRecord, agent: AgentRecord | undefined, config: RuntimeConfig): boolean {
  if (!agent) return true;
  const owners = skill.agent ? [agentName(skill.agent)] : config.agentSkillRules[skill.name];
  return !owners || owners.includes(agent.name);
}
export function definition(skill: SkillRecord): SkillDefinition {
  return { name: skill.name, description: String(skill.metadata.description ?? ''), invocation: skill.invocation, source: 'bundled', provider: 'linktool-plugin', path: join(resourceRoot, skill.path), resourceBase: { kind: 'directory', path: dirname(join(resourceRoot, skill.path)) }, content: body(skill), metadata: { ...skill.metadata, linktool: { context: skill.context, agent: skill.agent, allowedTools: skill.allowedTools } } };
}
export function skillProvider(agent: AgentRecord | undefined, config: RuntimeConfig): SkillProvider {
  return { name: 'linktool-plugin', async list() { return catalog.skills.filter(s => skillAllowed(s, agent, config)).map(s => ({ ...definitionSummary(s), rank: BUNDLED_SKILL_RANK, locator: s.name, metadata: s.metadata })); }, async get(candidate) { const s = getSkill(String(candidate.locator)); if (!skillAllowed(s, agent, config)) return undefined; return definition(s); } };
}
function definitionSummary(s: SkillRecord) { return { name: s.name, description: String(s.metadata.description ?? ''), invocation: s.invocation, source: 'bundled' as const, provider: 'linktool-plugin', path: join(resourceRoot, s.path), resourceBase: { kind: 'directory' as const, path: dirname(join(resourceRoot, s.path)) } }; }
export function workspace(agent?: Agent): string { return agent?.session.header.cwd ?? process.cwd(); }
export function inside(path: string, root: string): boolean { const rel = relative(resolve(root), resolve(path)); return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel)); }
/** Resolve literal old prompt paths without rewriting their prompt bodies. */
export function resourcePath(path: string, agent?: Agent, skill?: SkillRecord): string {
  path = expandPaths(path, workspace(agent));
  const normalized = path.replaceAll('\\', '/').replace(/^\.\//, '');
  if (/^(?:plugin\/|\$\{CLAUDE_PLUGIN_ROOT\}\/)/.test(normalized)) return resolve(resourceRoot, normalized.replace(/^(?:plugin\/|\$\{CLAUDE_PLUGIN_ROOT\}\/)/, ''));
  if (skill && !isAbsolute(path)) {
    const local = resolve(dirname(join(resourceRoot, skill.path)), normalized);
    if (inside(local, resourceRoot) && existsSync(local)) return local;
  }
  return resolve(workspace(agent), path);
}

export interface BenchmarkPolicy { agents?: string[]; skills?: string[]; tools?: string[]; mcp?: string[]; hooks?: string[]; workflows?: string[]; workflow?: boolean; resume_generation?: number }
export function benchmarkPolicy(agent?: Agent): BenchmarkPolicy { return agent ? ((globalThis as Record<symbol, unknown>)[Symbol.for('linktool.benchmark.policies')] as Map<string, BenchmarkPolicy> | undefined)?.get(agent.session.id) ?? {} : {}; }
