import { join, dirname, resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const resourceRoot = join(packageRoot, 'resources', 'plugin');

/** Our resolver runs before dsh sees configuration; dsh does not expand these tokens.
 *  Credential placeholders like ${AMAP_MAPS_API_KEY} are environment variables the
 *  recipient configures; an unset variable falls back to an empty value so the
 *  repository ships without any real credentials. */
export function expandPaths(value: string, cwd = process.cwd(), strict = false): string {
  const replacements: Record<string, string> = {
    DSH_ADAPTER_ROOT: packageRoot,
    DSH_PLUGIN_ROOT: resourceRoot, DSH_PLUGIN_DIR: resourceRoot, DSH_PROJECT_DIR: cwd,
    CLAUDE_PLUGIN_ROOT: resourceRoot, CLAUDE_PLUGIN_DIR: resourceRoot, CLAUDE_PROJECT_DIR: cwd,
  };
  return value.replace(/\$\{([A-Z_]+)\}\$?/g, (token, name: string) => {
    const replacement = replacements[name] ?? (strict ? process.env[name] : undefined);
    if (replacement === undefined) return '';
    return replacement.replaceAll('\\', '/');
  });
}
export function childEnvironment(cwd: string, role = ''): NodeJS.ProcessEnv {
  const root = resourceRoot;
  const env: NodeJS.ProcessEnv = { ...process.env, DSH_PLUGIN_ROOT: root, DSH_PLUGIN_DIR: root, DSH_PROJECT_DIR: cwd,
    CLAUDE_PLUGIN_ROOT: root, CLAUDE_PLUGIN_DIR: root, CLAUDE_PROJECT_DIR: cwd,
    CLAUDE_CONFIG_DIR: process.env.DSH_HOME ?? join(process.env.USERPROFILE ?? process.env.HOME ?? cwd, '.dsh'),
    CLAUDE_AGENT_NAME: role, CLAUDE_AGENT: role, CLAUDE_SUBAGENT_TYPE: role, PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1',
    USER_HOME: process.env.USERPROFILE ?? process.env.HOME ?? cwd,
    UV_PROJECT_ENVIRONMENT: join(packageRoot, '.runtime', 'hooks') };
  const bin = join(resourceRoot, 'bin');
  const uvBin = join(process.env.USERPROFILE ?? '', '.local', 'bin');
  env.PATH = [bin, ...(existsSync(uvBin) ? [uvBin] : []), process.env.PATH ?? ''].join(process.platform === 'win32' ? ';' : ':');
  return env;
}
