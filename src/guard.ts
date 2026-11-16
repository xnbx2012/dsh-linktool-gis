import { isAbsolute, join, relative, resolve } from 'node:path';
import type { ToolExecution } from '@deepseek-ai/dsh-tools';
import { workspace } from './catalog.js';
import type { HookGuardConfig, SkillRecord } from './catalog.js';

/** Hooks carried by config/hooks.json that the settings page can switch off. */
export type HookSwitch =
  | 'pathRestrict' | 'mcpRestrict' | 'gisToolLog' | 'paramValidate' | 'dataBackup'
  | 'resultValidate' | 'failurePattern' | 'contextCompress' | 'antiBypass' | 'skillMdGuard';

export interface HookSwitches { get(name: HookSwitch): boolean }

export const switchesOf = (guard: HookGuardConfig | undefined): HookSwitches => {
  const g = guard ?? {};
  const get = (name: HookSwitch): boolean => g[name] ?? true;
  return {
    // 输出路径严格限制默认关闭；关闭时 Bash 路径白名单由适配层 guard 接管。
    get: (name) => name === 'pathRestrict' ? (g.pathRestrict ?? false) : get(name),
  };
};

/**
 * The matched code baseline is authorized to execute ArcPy code. It must not
 * inherit LinkTool's atomic-tool-only anti-bypass treatment (mirror of the
 * HookBridge benchmarkRoutes short-circuit).
 */
export const benchmarkCodeRoute = (exec: ToolExecution): boolean => {
  const routes = (globalThis as Record<symbol, unknown>)[Symbol.for('linktool.benchmark.architectures')] as Map<string, string> | undefined;
  return !!exec.agent && routes?.get(exec.agent.session.id) === 'code';
};

const inside = (path: string, root: string): boolean => {
  const rel = relative(resolve(root), resolve(path));
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel));
};

const projectAreas = ['01_DataBackup', '02_WorkSpace', '03_Result'] as const;

/**
 * Hard-floor command guard, independent of the bundled Python hooks. Path
 * restriction that the settings page can relax runs below the danger rules,
 * which never relax: disk formats, registry writes, and remote-code pipes stay
 * denied whether or not the GIS path policy is enabled.
 */
export function guardBashCommand(command: string, guard: HookGuardConfig, cwd: string): string | undefined {
  const lower = command.toLowerCase();
  const danger: Array<[RegExp, string]> = [
    [/\bformat\s+[a-zA-Z]:/, '磁盘格式化命令'],
    [/\bdiskpart\b/, '磁盘分区工具'],
    [/\bdd\s+if=/, '磁盘镜像/覆盖命令'],
    [/\bmkfs\./, '文件系统创建命令'],
    [/\bchkdsk\b/, '磁盘检查修复命令'],
    [/\breg\s+(?:delete|edit|add)\b/, '注册表写入/删除命令'],
    [/\b(?:wget|curl)\b[^|]*\|\s*(?:sh|bash|pwsh|powershell)\b/, '远程脚本直接执行管道'],
    [/>\s*\/dev\/(?:sd[a-z]|nvme)/, '直接写入物理块设备'],
  ];
  for (const [pattern, label] of danger) if (pattern.test(lower)) return `检测到危险操作（${label}），禁止执行。`;
  // The legacy bash_guard whitelist applies only while strict path limiting is on.
  if (!guard.pathRestrict) return undefined;
  for (const area of projectAreas) {
    if (lower.startsWith(area.toLowerCase())) return undefined;
  }
  const redirect = /(?:^|[\s;(])(?:>>|1>>|2>>|2>|1>|>|(?:<<?))\s*("[^"]+"|'[^']+'|[^\s&|;<>]+)/g;
  for (const match of command.matchAll(redirect)) {
    const target = match[1].replace(/^["']|["']$/g, '');
    if (!target || target.startsWith('&') || target.startsWith('/dev/')) continue;
    if (!isAbsolute(target)) {
      if (target.startsWith('..') || target.includes('..')) return `Bash 重定向目标 '${target}' 越出项目目录。`;
      continue;
    }
    if (projectAreas.some(area => inside(target, join(cwd, area)))) continue;
    return `Bash 重定向目标 '${target}' 越出项目目录（01_DataBackup/02_WorkSpace/03_Result）。`;
  }
  return undefined;
}

/**
 * GIS-command interception: route arcpy/code-execution attempts to the GIS MCP
 * server instead of ad-hoc shells. Only commands that actually reference GIS
 * execution are denied — plain file/text/network commands pass untouched, so
 * generic automation never trips this guard.
 */
export function guardArcpyCommand(command: string): string | undefined {
  if (/arcpy|arcgis|\.gdb\b|\.shp\b|shapefile/i.test(command)) {
    return '检测到通过命令行直接执行 GIS/ArcPy 操作。请改用 arcgis-mcp-server 的 execute_gis_tool MCP 工具执行该 GIS 操作，不要用 python -c、脚本包装等方式绕过 MCP。';
  }
  return undefined;
}

/** Bash wrapper-script bypass floor (anti-bypass.py Rule B, non-arcpy part). */
export function guardWrapperCommand(command: string): string | undefined {
  const wrapper = /(\.(?:bat|sh|cmd)\b.*\b(?:python|uv\s+run)\b)|(\b(?:bash|sh|cmd|source)\s+\S+\.(?:bat|sh|cmd)\b)/i;
  if (wrapper.test(command)) return 'Bash 命令尝试经 .bat/.sh 包装脚本执行（可能内嵌 arcpy），禁止绕过 GIS MCP。';
  return undefined;
}

/**
 * Write/Edit content floor (anti-bypass.py Rule A). arcpy content belongs to
 * the MCP restriction switch; the generic exec-smell check in executable
 * scripts stays with the bypass switch.
 */
export function guardWritableContent(toolName: string, args: Record<string, unknown>, mcpRestrict: boolean): string | undefined {
  if (!['Write', 'write', 'Edit', 'edit', 'Update'].includes(toolName)) return undefined;
  const content = args.content ?? args.new_string;
  if (typeof content !== 'string' || !content) return undefined;
  if (mcpRestrict && /import\s+arcpy|from\s+arcpy|arcpy\./i.test(content)) {
    return '写入内容含 arcpy 直接执行特征，禁止 Write/Edit。一切 arcpy 执行必须经 execute_gis_tool（由 @gis-tool 在 Workflow 契约内调用）。';
  }
  return undefined;
}

/** PreToolUse guard run before every binding evaluation (install()-side). */
export async function guardPreToolUse(exec: ToolExecution, switches: HookSwitches, mapArguments: (name: string) => Record<string, unknown>): Promise<string | undefined> {
  if (benchmarkCodeRoute(exec)) return undefined;
  const args = mapArguments(exec.name);
  const skillMd = switches.get('skillMdGuard') && ['Read', 'read'].includes(exec.name)
    && typeof args.file_path === 'string' && /(^|[/\\])SKILL\.md$/i.test(args.file_path);
  if (skillMd) return '禁止使用 Read 工具读取 SKILL.md 文件。请通过 Skill 工具以技能名称加载对应技能。';
  const mcpRestrict = switches.get('mcpRestrict');
  if (mcpRestrict) {
    const content = guardWritableContent(exec.name, args, true);
    if (content) return content;
  }
  if (exec.name === 'Bash' || exec.name === 'bash') {
    const command = typeof args.command === 'string' ? args.command : '';
    if (command) {
      if (mcpRestrict) {
        const gis = guardArcpyCommand(command);
        if (gis) return gis;
      }
      if (switches.get('antiBypass')) {
        const wrapper = guardWrapperCommand(command);
        if (wrapper) return wrapper;
      }
      const path = guardBashCommand(command, { pathRestrict: switches.get('pathRestrict') }, workspace(exec.agent));
      if (path) return path;
    }
  }
  return undefined;
}

/** hooks.json 绑定 → 设置开关的静态映射；设置页与运行时共用同一份键集。 */
export const hookSwitchOf = (hookId: string): HookSwitch | undefined => (hookId.includes('gis-tool-log') ? 'gisToolLog'
  : hookId.includes('param-validate') ? 'paramValidate'
  : hookId.includes('data-backup') ? 'dataBackup'
  : hookId.includes('result-validate') ? 'resultValidate'
  : hookId.includes('failure-pattern-detector') ? 'failurePattern'
  : hookId.includes('context-compress') ? 'contextCompress'
  : hookId.includes('modify-protect-hook') ? 'pathRestrict'
  : hookId.includes('anti-bypass') ? 'antiBypass'
  : undefined);
