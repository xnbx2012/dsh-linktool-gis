import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { expandPaths, childEnvironment } from './paths.js';
import { packageRoot, readJson } from './catalog.js';
import { engineSwitchesFile } from './engines.js';

export interface McpConfig { type?: string; command?: string; args?: string[]; env?: Record<string, string>; cwd?: string; url?: string; headers?: Record<string, string> }
/** Return native dsh-mcp-client configuration with every path already resolved. */
export function resolveMcp(server: string, original: McpConfig, projectDir = process.cwd()): Record<string, unknown> {
  const relocate = (value: string) => expandPaths(value, projectDir, true);
  const env = Object.fromEntries(Object.entries(original.env ?? {}).map(([k, v]) => [k, relocate(v)]));
  for (const key of Object.keys(env)) if (process.env[key] !== undefined) env[key] = process.env[key]!;
  const common = { serverName: server, toolCallTimeoutMs: 600000, failOnStartupError: false };
  if (original.type === 'streamable-http') return { ...common, transport: 'streamable-http', url: relocate(process.env.LINKTOOL_MEMORY_URL ?? original.url!), headers: Object.fromEntries(Object.entries(original.headers ?? {}).map(([k, v]) => [k, relocate(k.toLowerCase() === 'authorization' ? process.env.LINKTOOL_MEMORY_AUTHORIZATION ?? v : v)])) };
  let command = relocate(original.command!); let args = (original.args ?? []).map(relocate);
  args = args.map(arg => arg === 'mcp[cli]' ? 'mcp[cli]>=1.26,<2' : arg);
  if (command === 'npx' && args[0] !== '-y' && args[0] !== '--yes') args.unshift('-y');
  let cwd = original.cwd ? relocate(original.cwd) : projectDir;
  // Replace the Windows wrapper with its equivalent uv invocation; avoid cmd quoting and stale venvs.
  if (/[/\\]knowledge-db-mcp[/\\]run\.bat$/i.test(command)) { cwd = dirname(command); command = 'uv'; args = ['run', 'python', join(cwd, 'main.py')]; }
  const script = args.find(a => a.endsWith('.py') && existsSync(a));
  if (script && existsSync(join(dirname(script), 'pyproject.toml')) && command === 'uv' && args[0] === 'run') {
    cwd = dirname(script); args = ['run', '--project', cwd, ...args.slice(1)];
  }
  else if (command === 'uv' && args[0] === 'run') args = ['run', '--no-project', ...args.slice(1)];
  return {
    ...common,
    transport: 'stdio',
    command, args, cwd,
    env: {
      ...childEnvironment(projectDir),
      ...env,
      UV_PROJECT_ENVIRONMENT: join(packageRoot, '.runtime', 'mcp', server),
      // 五引擎开关文件：适配层随设置页 volatile 写入实时落盘，MCP 每次调用读取。
      // color-style 需要同一份开关来选择制图后端（ArcGIS Pro 优先，QGIS 兜底）。
      ...(['arcgis-mcp-server', 'color-style'].includes(server) ? { LINKTOOL_ENGINE_SWITCHES: engineSwitchesFile() } : {}),
    },
  };
}
export function resolvedServers(projectDir = process.cwd()): Record<string, Record<string, unknown>> {
  const original = readJson<Record<string, McpConfig>>(join(packageRoot, 'config/mcp.json'));
  return Object.fromEntries(Object.entries(original).map(([name, config]) => [name, resolveMcp(name, config, projectDir)]));
}
