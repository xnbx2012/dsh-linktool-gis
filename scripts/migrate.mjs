import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { resolve, relative, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { parse } from 'yaml';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
// 源即 resources/plugin（仓库自包含）。历史上的外部 ../plugin 源已废弃——
// 它停留在纯 ArcPy 时代，缺 shared/gdal_engine.py 等五引擎文件，不再作为事实源。
const source = join(root, 'resources', 'plugin');
const target = source;
const walk = dir => readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]);
const posix = p => p.replaceAll('\\', '/');
const list = v => v == null ? [] : Array.isArray(v) ? v : String(v).split(',').map(x => x.trim()).filter(Boolean);
const sha = b => createHash('sha256').update(b).digest('hex');
// 与 verify.mjs 的行尾基准保持一致：文本文件按 LF 归一后记录/校验哈希，
// 检出（autocrlf）造成的 CRLF 差异不影响完整性语义。
const isText = (path) => /\.(md|json|py|txt|ya?ml|js|mjs|ts|html|css|bat|toml|cfg|sh|xml|csv|gitignore|lock|TAG|prj|bakcup|pyc|hold|in)$/.test(path) || path.includes('/.hold') || path.endsWith('.python-version') || /(^|\/)(INSTALLER|METADATA|RECORD|REQUESTED|WHEEL|top_level)$/.test(path.split('/').pop() || '');
const normalized = (raw, path) => isText(path) ? Buffer.from(raw.toString('utf8').replace(/\r\n/g, '\n'), 'utf8') : raw;
function document(path) {
  const bytes = readFileSync(path);
  const text = bytes.toString('utf8').replace(/^\uFEFF/, '');
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(text);
  // The source visualisation agent has an unindented multiline flow array.
  // Normalize only the parser's input; the actual document is copied byte-for-byte.
  const parserInput = match?.[1].replace(/^(capabilities:)\s*\r?\n(\[[\s\S]*?^\])/m, (_, key, value) => key + '\n' + value.split(/\r?\n/).map(line => '  ' + line).join('\n')).replace(/^(\s*description:[ \t]*)([^\r\n]*)/gm, (_, prefix, value) => prefix + (/^["'|>]/.test(value.trim()) ? value : JSON.stringify(value.trim())));
  const metadata = match ? parse(parserInput) : {};
  const body = match ? text.slice(match[0].length) : text;
  // bodySha256 与 lib/catalog.ts body() 同基准：LF 归一后哈希。
  return { path: posix(relative(source, path)), metadata, bodySha256: sha(Buffer.from(body.replace(/\r\n/g, '\n'))), fileSha256: sha(normalized(bytes, path)) };
}
const agents = walk(join(source, 'agents')).filter(p => p.endsWith('.md') && !p.endsWith('CLAUDE.md')).map(document).map(d => ({ ...d, name: d.metadata.name, tools: list(d.metadata.tools), disallowedTools: list(d.metadata.disallowedTools), skills: list(d.metadata.skills), mcpServers: list(d.metadata.mcpServers) }));
const skills = walk(join(source, 'skills')).filter(p => p.endsWith('SKILL.md')).map(document).map(d => ({ ...d, name: d.metadata.name, agent: d.metadata.agent ?? null, context: d.metadata.context ?? 'inline', allowedTools: list(d.metadata['allowed-tools'] ?? d.metadata.allowed_tools), invocation: { modelInvocable: d.metadata['disable-model-invocation'] !== true, userInvocable: d.metadata['user-invocable'] !== false } }));
const manifest = walk(source)
  // 运行时生成的引擎 schema 缓存不入清单（.gitignore 同步排除）；
  // MCP 服务器启动时按 7 天 TTL 重新生成，param-validate 降级容缺。
  .filter(p => posix(relative(source, p)) !== 'scripts/arcgis-mcp-server/schema.json')
  .map(p => {
    const bytes = readFileSync(p);
    return { path: posix(relative(source, p)), bytes: statSync(p).size, sha256: sha(normalized(bytes, p)) };
  });
const plugin = JSON.parse(readFileSync(join(source, '.claude-plugin', 'plugin.json'), 'utf8'));
mkdirSync(join(root, 'config'), { recursive: true });
writeFileSync(join(root, 'config', 'catalog.json'), JSON.stringify({ name: plugin.name, version: plugin.version, agents, skills, workflows: walk(join(source, 'workflows')).map(p => posix(relative(source, p))) }, null, 2) + '\n');
writeFileSync(join(root, 'config', 'mcp.json'), JSON.stringify(plugin.mcpServers, null, 2).replaceAll('CLAUDE_PLUGIN_ROOT', 'DSH_PLUGIN_ROOT').replaceAll('CLAUDE_PLUGIN_DIR', 'DSH_PLUGIN_ROOT') + '\n');
const hookConfig = JSON.parse(readFileSync(join(source, 'hooks', 'hooks.json.bakcup'), 'utf8').replaceAll('CLAUDE_PLUGIN_ROOT', 'DSH_PLUGIN_ROOT').replaceAll('CLAUDE_PROJECT_DIR', 'DSH_PROJECT_DIR').replaceAll('uv run python', 'uv run --no-project python').replaceAll('uv run --with-requirements', 'uv run --no-project --with-requirements'));
hookConfig.hooks.PreToolUse[0].hooks[0].command = 'uv run --no-project python "${DSH_ADAPTER_ROOT}/scripts/hook-runner.py" "${DSH_PLUGIN_ROOT}/scripts/modify-protect-hook/main.py"';
hookConfig.hooks.PostToolUse[0].hooks[0].command = 'uv run --no-project python "${DSH_ADAPTER_ROOT}/scripts/hook-runner.py" "${DSH_PLUGIN_ROOT}/scripts/gis-tool-log/enhanced_record.py"';
hookConfig.hooks.PreToolUse[1].hooks[0].command = 'uv run --no-project python "${DSH_ADAPTER_ROOT}/scripts/hook-runner.py" "${DSH_PLUGIN_ROOT}/scripts/modify-protect-hook/bash_guard.py"';
hookConfig.hooks.PreToolUse[2].hooks[2].command = 'uv run --no-project python "${DSH_ADAPTER_ROOT}/scripts/hook-runner.py" "${DSH_PLUGIN_ROOT}/scripts/modify-protect-hook/gis.py"';
writeFileSync(join(root, 'config', 'hooks.json'), JSON.stringify(hookConfig, null, 2) + '\n');
writeFileSync(join(root, 'config', 'source-manifest.json'), JSON.stringify({ source: '../plugin', target: 'resources/plugin', files: manifest, totalBytes: manifest.reduce((n, f) => n + f.bytes, 0) }, null, 2) + '\n');
writeFileSync(join(root, 'config', 'runtime.json'), JSON.stringify({ hooksEnabled: true, mcpEnabled: true, enabledServers: Object.keys(plugin.mcpServers), hookGuard: { pathRestrict: false, mcpRestrict: true, gisToolLog: true, paramValidate: true, dataBackup: true, resultValidate: true, failurePattern: true, contextCompress: true, antiBypass: true, skillMdGuard: true }, modelAliases: { haiku: { mode: 'inherit' }, sonnet: { mode: 'inherit' }, opus: { mode: 'inherit' } }, serverAliases: { 'pdf-read-mcp': 'pdf-reader-mcp' }, toolAliases: { Wrtie: 'Write', Web_Search: 'WebSearch' }, maxAgentDepth: 16, hookTimeoutMs: 600000, agentSkillRules: { 'gis-data-preview': ['gis-data-visualisation'], 'map-image-generate': ['gis-data-visualisation'], 'officecli-docx': ['report'], 'officecli-xlsx': ['report'] } }, null, 2) + '\n');
console.log(JSON.stringify({ agents: agents.length, skills: skills.length, mcpServers: Object.keys(plugin.mcpServers).length, files: manifest.length, bytes: manifest.reduce((n, f) => n + f.bytes, 0) }));
