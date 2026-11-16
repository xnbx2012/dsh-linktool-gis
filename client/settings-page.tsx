/**
 * LinkTool-GIS settings page, browser half.
 *
 * Registers one `settings.section` entry ("LinkTool-GIS") rendering a switch
 * row per configurable hook, backed by the `linktool-plugin` Host namespace.
 * Spelling the namespace and slot contracts locally follows the official
 * settings pages: a client package must not import Host packages.
 */
interface Snapshot {
  status: 'loading' | 'ready' | 'unavailable';
  value: Record<string, unknown> | undefined;
  revision: number | undefined;
  writable: boolean;
}
interface ConfigForm {
  getSnapshot(): Snapshot;
  subscribe(listener: () => void): () => void;
  set(field: string, value: unknown): Promise<boolean>;
  unset(field: string): Promise<boolean>;
}
interface ConfigFormsFace {
  get(entryId: string): ConfigForm;
  whileServed(namespaces: readonly string[], register: (served: ReadonlySet<string>) => () => void): () => void;
}
type Translate = (key: string, params?: Record<string, string | number>) => string;
interface SwitchProps { checked: boolean; disabled?: boolean; label: string; onChange: (checked: boolean) => void }

const NAMESPACE = 'linktool-plugin';
const NS = 'settings.linktoolGis';
const zh = {
  title: 'LinkTool-GIS',
  intro: 'GIS 插件各 Hook 的启用开关。改动立即生效（volatile 配置），无需重启 Harness。',
  pathRestrict: '输出路径严格限制',
  pathRestrictHint: '开启后文件工具、Bash 与 GIS 输出仅允许 01_DataBackup（只读）/02_WorkSpace/03_Result。默认关闭：路径策略交由 Harness 控制。',
  mcpRestrict: 'MCP 执行限制',
  mcpRestrictHint: '拦截 GIS 类命令行/代码并引导使用 GIS MCP 执行；普通命令行与代码操作不受影响。默认开启。',
  gisToolLog: 'GIS 工具日志记录',
  gisToolLogHint: '每次 execute_gis_tool 调用写入 02_WorkSpace/gis-tool-logs.json，供报告与复现使用。',
  paramValidate: '参数校验',
  paramValidateHint: '执行前对照 ArcPy 工具 schema 检查必填参数与输入路径。',
  dataBackup: '数据备份',
  dataBackupHint: '破坏性 GIS 工具操作 01_DataBackup 数据前自动备份并重定向。',
  resultValidate: '结果验证',
  resultValidateHint: 'GIS 输出属性空值率、要素数与几何一致性的自动检查。',
  failurePattern: '失败模式检测',
  failurePatternHint: '同一工具连续失败时提示停止重试并报告根因。',
  contextCompress: '上下文压缩摘要',
  contextCompressHint: '上下文压缩后重新注入 GIS 操作历史摘要。',
  antiBypass: '绕过防护',
  antiBypassHint: '禁止经 Write/Edit 或 .bat/.sh 包装脚本产出 arcpy 执行。',
  skillMdGuard: 'SKILL.md 保护',
  skillMdGuardHint: '禁止 Read 直读技能定义文件，改用 Skill 工具加载。',
  switchFailed: '开关写入失败，请重试',
  unavailable: 'Host 未提供 linktool-plugin 配置，设置项不可用。',
};
const en = {
  title: 'LinkTool-GIS',
  intro: 'Enable switches for the GIS plugin hooks. Changes apply immediately (volatile config) without restarting the Harness.',
  pathRestrict: 'Strict output path limitation',
  pathRestrictHint: 'When on, file tools, Bash and GIS output are limited to 01_DataBackup (read-only) / 02_WorkSpace / 03_Result. Off by default: path policy belongs to the Harness.',
  mcpRestrict: 'MCP execution restriction',
  mcpRestrictHint: 'Intercepts GIS command-line/code attempts and routes them to the GIS MCP; ordinary commands and code are untouched. On by default.',
  gisToolLog: 'GIS tool logging',
  gisToolLogHint: 'Writes every execute_gis_tool call to 02_WorkSpace/gis-tool-logs.json for reports and reproduction.',
  paramValidate: 'Parameter validation',
  paramValidateHint: 'Pre-checks required parameters and input paths against the ArcPy tool schema.',
  dataBackup: 'Data backup',
  dataBackupHint: 'Backs up and redirects 01_DataBackup inputs before destructive GIS tools.',
  resultValidate: 'Result validation',
  resultValidateHint: 'Automatic checks of output attribute null rates, feature counts, and geometry.',
  failurePattern: 'Failure pattern detection',
  failurePatternHint: 'Advises stopping retries after the same tool fails repeatedly.',
  contextCompress: 'Context compaction summary',
  contextCompressHint: 'Re-injects the compressed GIS operation history after compaction.',
  antiBypass: 'Bypass protection',
  antiBypassHint: 'Denies arcpy execution produced through Write/Edit or .bat/.sh wrapper scripts.',
  skillMdGuard: 'SKILL.md protection',
  skillMdGuardHint: 'Reading skill definitions through Read is forbidden; load them with Skill.',
  switchFailed: 'Toggle failed, please retry',
  unavailable: 'The Host does not serve the linktool-plugin namespace; settings are unavailable.',
};

interface RowSpec { field: string; labelKey: string; hintKey: string; order: number }
const ROWS: RowSpec[] = [
  { field: 'hookGuard.pathRestrict', labelKey: 'pathRestrict', hintKey: 'pathRestrictHint', order: 10 },
  { field: 'hookGuard.mcpRestrict', labelKey: 'mcpRestrict', hintKey: 'mcpRestrictHint', order: 20 },
  { field: 'hookGuard.gisToolLog', labelKey: 'gisToolLog', hintKey: 'gisToolLogHint', order: 30 },
  { field: 'hookGuard.paramValidate', labelKey: 'paramValidate', hintKey: 'paramValidateHint', order: 40 },
  { field: 'hookGuard.dataBackup', labelKey: 'dataBackup', hintKey: 'dataBackupHint', order: 50 },
  { field: 'hookGuard.resultValidate', labelKey: 'resultValidate', hintKey: 'resultValidateHint', order: 60 },
  { field: 'hookGuard.failurePattern', labelKey: 'failurePattern', hintKey: 'failurePatternHint', order: 70 },
  { field: 'hookGuard.contextCompress', labelKey: 'contextCompress', hintKey: 'contextCompressHint', order: 80 },
  { field: 'hookGuard.antiBypass', labelKey: 'antiBypass', hintKey: 'antiBypassHint', order: 90 },
  { field: 'hookGuard.skillMdGuard', labelKey: 'skillMdGuard', hintKey: 'skillMdGuardHint', order: 100 },
];

/** Required services (cordis fiber inject) — official client plugins declare these so
 * activation waits for slots/locale/configForms to exist before apply runs. */
export const inject = ['slots', 'locale', 'configForms'];

export function apply(ctx: any): void {
  const t: Translate = ctx.locale.bind(NS);
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'linktool-gis: dictionaries');
  const form = ctx.configForms.get(NAMESPACE);
  const css = '.LTGIS_section{max-width:760px;color:var(--dsw-alias-label-primary);flex-direction:column;gap:16px;display:flex}.LTGIS_intro{color:var(--dsw-alias-label-secondary);margin:0;font-size:13px;line-height:20px}.LTGIS_unavailable{color:var(--dsw-alias-label-tertiary);margin:0;font-size:13px}.LTGIS_rows{flex-direction:column;display:flex}.LTGIS_row{border-bottom:.5px solid var(--dsw-alias-border-l2);justify-content:space-between;align-items:center;gap:24px;padding:16px 0;display:flex}.LTGIS_main{min-width:0;flex:1}.LTGIS_title{font-size:14px;line-height:20px}.LTGIS_hint{color:var(--dsw-alias-label-secondary);margin-top:4px;font-size:12px;line-height:18px}.LTGIS_failed{color:var(--dsw-alias-state-error-primary);margin-top:4px;font-size:12px}';
  ctx.effect(() => {
    if (typeof document === 'undefined') return;
    const tagId = '@linktool/dsh-plugin/settings.module.css';
    if (document.querySelector('style[data-plugin-css="' + tagId + '"]') !== null) return;
    const tag = document.createElement('style');
    tag.dataset.plugin = '@linktool/dsh-plugin';
    tag.dataset.pluginCss = tagId;
    tag.textContent = css;
    document.head.appendChild(tag);
    return () => { tag.remove(); };
  }, 'linktool-gis: styles');

  const useSectionForm = (selector: (snapshot: Snapshot) => unknown) => {
    const react = require('react') as typeof import('react');
    const [value, setValue] = react.useState(() => selector(form.getSnapshot()));
    (0, react.useEffect)(() => form.subscribe(() => setValue(selector(form.getSnapshot()))), []);
    return value;
  };

  function SwitchRow({ spec }: { spec: RowSpec }) {
    const snapshot = useSectionForm((s: Snapshot) => s) as Snapshot;
    const busy = (require('react') as typeof import('react')).useState(false);
    const failed = (require('react') as typeof import('react')).useState(false);
    const primitives = require('@deepseek-ai/dsh-client-ui-primitives');
    const [, setBusy] = busy;
    const [, setFailed] = failed;
    const field = spec.field.split('.')[1];
    const checked = snapshot.status === 'ready'
      ? Boolean((snapshot.value as Record<string, unknown> | undefined)?.[field])
      : field === 'pathRestrict'; // shipped default while loading
    const disabled = !snapshot.writable || busy[0];
    const onToggle = async (next: boolean) => {
      setBusy(true); setFailed(false);
      try { if (!await form.set('hookGuard.' + field, next)) setFailed(true); }
      catch { setFailed(true); }
      finally { setBusy(false); }
    };
    const jsx = require('react/jsx-runtime');
    return jsx.jsxs('div', { className: 'LTGIS_row', children: [
      jsx.jsxs('div', { className: 'LTGIS_main', children: [
        jsx.jsx('div', { className: 'LTGIS_title', children: t(spec.labelKey) }),
        jsx.jsx('div', { className: 'LTGIS_hint', children: t(spec.hintKey) }),
        failed[0] ? jsx.jsx('div', { className: 'LTGIS_failed', role: 'alert', children: t('switchFailed') }) : null,
      ] }),
      jsx.jsx(primitives.Switch, { checked, disabled, label: t(spec.labelKey), onChange: onToggle }),
    ] });
  }

  function LinkToolGisSection() {
    const snapshot = useSectionForm((s: Snapshot) => s) as Snapshot;
    const jsx = require('react/jsx-runtime');
    const rows = [...ROWS].sort((a, b) => a.order - b.order).map(spec => jsx.jsx(SwitchRow, { spec }, spec.field));
    return jsx.jsxs('div', { className: 'LTGIS_section', children: [
      jsx.jsx('p', { className: 'LTGIS_intro', children: t('intro') }),
      snapshot.status === 'unavailable' ? jsx.jsx('p', { className: 'LTGIS_unavailable', children: t('unavailable') }) : jsx.jsx('div', { className: 'LTGIS_rows', children: rows }),
    ] });
  }

  ctx.effect(() => ctx.configForms.whileServed([NAMESPACE], () => ctx.slots.inject('settings.section', () => ctx.slots.register({
    name: 'settings.section',
    id: 'linktool-gis',
    order: 90,
    label: () => t('title'),
    locale: NS,
  }, LinkToolGisSection))), 'linktool-gis: settings section');
}
