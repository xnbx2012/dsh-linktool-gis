/**
 * LinkTool-GIS settings page, browser half.
 *
 * Registers one `settings.section` entry ("LinkTool-GIS") rendering:
 *   1. one switch row per configurable hook;
 *   2. the five-engine group (ArcGIS Pro / QGIS / WhiteboxTools / GDAL / 内置)
 *      with per-engine availability badges and a refresh button.
 *
 * Both groups are backed by the `linktool-plugin` Host namespace. Spelling the
 * namespace and slot contracts locally follows the official settings pages: a
 * client package must not import Host packages.
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
  hooksGroup: 'Hook 开关',
  pathRestrict: '输出路径严格限制',
  pathRestrictHint: '开启后文件工具、Bash 与 GIS 输出仅允许 01_DataBackup（只读）/02_WorkSpace/03_Result。默认关闭：路径策略交由 Harness 控制。',
  mcpRestrict: 'MCP 执行限制',
  mcpRestrictHint: '拦截 GIS 类命令行/代码并引导使用 GIS MCP 执行；普通命令行与代码操作不受影响。默认开启。',
  gisToolLog: 'GIS 工具日志记录',
  gisToolLogHint: '每次 execute_gis_tool 调用写入 02_WorkSpace/gis-tool-logs.json，供报告与复现使用。',
  paramValidate: '参数校验',
  paramValidateHint: '执行前对照工具 schema 检查必填参数与输入路径。',
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
  engineGroup: 'GIS 引擎',
  engineIntro: 'execute_gis_tool 的五类执行引擎。状态为本机探测结果；环境不可用的引擎会在首次探测后自动关闭。查看数据/数据库类基础能力始终由内置代码提供，不依赖任何引擎。',
  engineArcgis: 'ArcGIS Pro 引擎',
  engineArcgisHint: 'arcpy_* 工具，经 arcgispro-py3 执行，仅限 Windows。默认关闭。',
  engineQgis: 'QGIS 引擎',
  engineQgisHint: 'qgis_* 处理算法（native:buffer 等），进程内或经 qgis_process 执行。',
  engineWhitebox: 'WhiteboxTools 引擎',
  engineWhiteboxHint: 'wbt_* 工具（clip、breach_depressions_least_cost 等），首次使用会下载二进制。',
  engineGdal: 'GDAL 引擎',
  engineGdalHint: 'gdal_* 工具（gdal:translate、gdal:slope 等），进程内 rasterio/pyogrio 优先。',
  engineInner: '内置引擎',
  engineInnerHint: '纯 Python 工具（buffer、near、project 等），零外部依赖，始终建议开启。',
  engineStatusOk: '可用',
  engineStatusBad: '不可用',
  engineStatusUnknown: '未探测',
  engineStatusChecking: '探测中…',
  engineRefresh: '刷新引擎状态',
  engineRefreshing: '探测中…',
  engineRefreshFailed: '探测失败，请重试',
  unavailable: 'Host 未提供 linktool-plugin 配置，设置项不可用。',
};
const en = {
  title: 'LinkTool-GIS',
  intro: 'Enable switches for the GIS plugin hooks. Changes apply immediately (volatile config) without restarting the Harness.',
  hooksGroup: 'Hook switches',
  pathRestrict: 'Strict output path limitation',
  pathRestrictHint: 'When on, file tools, Bash and GIS output are limited to 01_DataBackup (read-only) / 02_WorkSpace / 03_Result. Off by default: path policy belongs to the Harness.',
  mcpRestrict: 'MCP execution restriction',
  mcpRestrictHint: 'Intercepts GIS command-line/code attempts and routes them to the GIS MCP; ordinary commands and code are untouched. On by default.',
  gisToolLog: 'GIS tool logging',
  gisToolLogHint: 'Writes every execute_gis_tool call to 02_WorkSpace/gis-tool-logs.json for reports and reproduction.',
  paramValidate: 'Parameter validation',
  paramValidateHint: 'Pre-checks required parameters and input paths against the tool schema.',
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
  engineGroup: 'GIS engines',
  engineIntro: 'Five execution engines behind execute_gis_tool. Status reflects a local probe; engines whose environment is missing are switched off automatically after the first probe. Data/database inspection always uses built-in code and depends on no engine.',
  engineArcgis: 'ArcGIS Pro engine',
  engineArcgisHint: 'arcpy_* tools via arcgispro-py3, Windows only. Off by default.',
  engineQgis: 'QGIS engine',
  engineQgisHint: 'qgis_* processing algorithms (native:buffer etc.), in-process or via qgis_process.',
  engineWhitebox: 'WhiteboxTools engine',
  engineWhiteboxHint: 'wbt_* tools (clip, breach_depressions_least_cost, …); the binary downloads on first use.',
  engineGdal: 'GDAL engine',
  engineGdalHint: 'gdal_* tools (gdal:translate, gdal:slope, …); in-process rasterio/pyogrio preferred.',
  engineInner: 'Built-in engine',
  engineInnerHint: 'Pure-Python tools (buffer, near, project, …) with zero external dependencies; keep it on.',
  engineStatusOk: 'Available',
  engineStatusBad: 'Unavailable',
  engineStatusUnknown: 'Not probed',
  engineStatusChecking: 'Probing…',
  engineRefresh: 'Refresh engine status',
  engineRefreshing: 'Probing…',
  engineRefreshFailed: 'Probe failed, please retry',
  unavailable: 'The Host does not serve the linktool-plugin namespace; settings are unavailable.',
};

interface RowSpec { field: string; labelKey: string; hintKey: string; order: number }
// Flat Config field per switch: settings writes address one schema dict key per
// segment and ConfigForm.set sends single-segment paths, so every toggle lives
// at the namespace root.
const ROWS: RowSpec[] = [
  { field: 'guardPathRestrict', labelKey: 'pathRestrict', hintKey: 'pathRestrictHint', order: 10 },
  { field: 'guardMcpRestrict', labelKey: 'mcpRestrict', hintKey: 'mcpRestrictHint', order: 20 },
  { field: 'guardGisToolLog', labelKey: 'gisToolLog', hintKey: 'gisToolLogHint', order: 30 },
  { field: 'guardParamValidate', labelKey: 'paramValidate', hintKey: 'paramValidateHint', order: 40 },
  { field: 'guardDataBackup', labelKey: 'dataBackup', hintKey: 'dataBackupHint', order: 50 },
  { field: 'guardResultValidate', labelKey: 'resultValidate', hintKey: 'resultValidateHint', order: 60 },
  { field: 'guardFailurePattern', labelKey: 'failurePattern', hintKey: 'failurePatternHint', order: 70 },
  { field: 'guardContextCompress', labelKey: 'contextCompress', hintKey: 'contextCompressHint', order: 80 },
  { field: 'guardAntiBypass', labelKey: 'antiBypass', hintKey: 'antiBypassHint', order: 90 },
  { field: 'guardSkillMd', labelKey: 'skillMdGuard', hintKey: 'skillMdGuardHint', order: 100 },
];

interface EngineRowSpec { field: string; engineKey: string; labelKey: string; hintKey: string; order: number }
// Five-engine group: flat engine* config fields; engineKey maps to the probe
// status keys inside the engineStatus JSON snapshot.
const ENGINE_ROWS: EngineRowSpec[] = [
  { field: 'engineArcgis', engineKey: 'arcpy', labelKey: 'engineArcgis', hintKey: 'engineArcgisHint', order: 10 },
  { field: 'engineQgis', engineKey: 'qgis', labelKey: 'engineQgis', hintKey: 'engineQgisHint', order: 20 },
  { field: 'engineWhitebox', engineKey: 'wbt', labelKey: 'engineWhitebox', hintKey: 'engineWhiteboxHint', order: 30 },
  { field: 'engineGdal', engineKey: 'gdal', labelKey: 'engineGdal', hintKey: 'engineGdalHint', order: 40 },
  { field: 'engineInner', engineKey: 'inner', labelKey: 'engineInner', hintKey: 'engineInnerHint', order: 50 },
];

interface StatusSnapshot { engines?: Record<string, { available?: boolean; detail?: string; version?: string }>; checked_at?: string }

/** Required services (cordis fiber inject) — official client plugins declare these so
 * activation waits for slots/locale/configForms to exist before apply runs. */
export const inject = ['slots', 'locale', 'configForms'];

export function apply(ctx: any): void {
  const t: Translate = ctx.locale.bind(NS);
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'linktool-gis: dictionaries');
  const form = ctx.configForms.get(NAMESPACE);
  const css = '.LTGIS_section{max-width:760px;color:var(--dsw-alias-label-primary);flex-direction:column;gap:16px;display:flex}.LTGIS_intro{color:var(--dsw-alias-label-secondary);margin:0;font-size:13px;line-height:20px}.LTGIS_unavailable{color:var(--dsw-alias-label-tertiary);margin:0;font-size:13px}.LTGIS_rows{flex-direction:column;display:flex}.LTGIS_row{border-bottom:.5px solid var(--dsw-alias-border-l2);justify-content:space-between;align-items:center;gap:24px;padding:16px 0;display:flex}.LTGIS_main{min-width:0;flex:1}.LTGIS_title{font-size:14px;line-height:20px}.LTGIS_hint{color:var(--dsw-alias-label-secondary);margin-top:4px;font-size:12px;line-height:18px}.LTGIS_failed{color:var(--dsw-alias-state-error-primary);margin-top:4px;font-size:12px}.LTGIS_group{margin-top:8px;font-size:13px;font-weight:600;color:var(--dsw-alias-label-secondary)}.LTGIS_status{font-size:12px;line-height:18px;margin-top:4px;display:inline-flex;align-items:center;gap:6px}.LTGIS_dot{width:8px;height:8px;border-radius:50%;flex:none}.LTGIS_ok{color:var(--dsw-alias-state-success-primary,#0a7d33)}.LTGIS_ok .LTGIS_dot{background:var(--dsw-alias-state-success-primary,#0a7d33)}.LTGIS_bad{color:var(--dsw-alias-state-error-primary)}.LTGIS_bad .LTGIS_dot{background:var(--dsw-alias-state-error-primary)}.LTGIS_unknown{color:var(--dsw-alias-label-tertiary)}.LTGIS_unknown .LTGIS_dot{background:var(--dsw-alias-label-tertiary)}.LTGIS_busy{color:var(--dsw-alias-label-secondary)}.LTGIS_busy .LTGIS_dot{background:var(--dsw-alias-label-secondary)}.LTGIS_refreshRow{justify-content:space-between;align-items:center;gap:24px;padding:12px 0 0;display:flex}.LTGIS_refreshBtn{border:.5px solid var(--dsw-alias-border-l2);background:transparent;color:var(--dsw-alias-label-primary);border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}.LTGIS_refreshBtn:disabled{opacity:.5;cursor:default}.LTGIS_ver{color:var(--dsw-alias-label-tertiary);font-size:11px;line-height:16px}';
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

  /** Parse the engineStatus JSON snapshot out of the live config value. */
  const readStatus = (snapshot: Snapshot): StatusSnapshot | undefined => {
    if (snapshot.status !== 'ready') return undefined;
    const raw = (snapshot.value as Record<string, unknown> | undefined)?.engineStatus;
    if (typeof raw !== 'string' || !raw.trim()) return undefined;
    try {
      const parsed = JSON.parse(raw) as StatusSnapshot;
      return parsed && typeof parsed === 'object' ? parsed : undefined;
    } catch {
      return undefined;
    }
  };

  function SwitchRow({ spec }: { spec: RowSpec }) {
    const snapshot = useSectionForm((s: Snapshot) => s) as Snapshot;
    const busy = (require('react') as typeof import('react')).useState(false);
    const failed = (require('react') as typeof import('react')).useState(false);
    const primitives = require('@deepseek-ai/dsh-client-ui-primitives');
    const [, setBusy] = busy;
    const [, setFailed] = failed;
    const field = spec.field; // flat Config key, e.g. guardPathRestrict
    const checked = snapshot.status === 'ready'
      ? Boolean((snapshot.value as Record<string, unknown> | undefined)?.[field])
      : field === 'guardPathRestrict'; // shipped default while loading
    const disabled = !snapshot.writable || busy[0];
    const onToggle = async (next: boolean) => {
      setBusy(true); setFailed(false);
      try { if (!await form.set(field, next)) setFailed(true); }
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

  function EngineRow({ spec, status }: { spec: EngineRowSpec; status: StatusSnapshot | undefined }) {
    const snapshot = useSectionForm((s: Snapshot) => s) as Snapshot;
    const busy = (require('react') as typeof import('react')).useState(false);
    const failed = (require('react') as typeof import('react')).useState(false);
    const primitives = require('@deepseek-ai/dsh-client-ui-primitives');
    const [, setBusy] = busy;
    const [, setFailed] = failed;
    const probe = status?.engines?.[spec.engineKey];
    const unknown = !probe || typeof probe.available !== 'boolean';
    const cls = unknown ? 'LTGIS_unknown' : probe!.available ? 'LTGIS_ok' : 'LTGIS_bad';
    const label = unknown ? t('engineStatusUnknown') : probe!.available ? t('engineStatusOk') : t('engineStatusBad');
    const detail = typeof probe?.detail === 'string' && probe.detail ? probe.detail : undefined;
    const checked = snapshot.status === 'ready'
      ? Boolean((snapshot.value as Record<string, unknown> | undefined)?.[spec.field])
      : spec.field !== 'engineArcgis'; // shipped default while loading
    const disabled = !snapshot.writable || busy[0];
    const onToggle = async (next: boolean) => {
      setBusy(true); setFailed(false);
      try { if (!await form.set(spec.field, next)) setFailed(true); }
      catch { setFailed(true); }
      finally { setBusy(false); }
    };
    const jsx = require('react/jsx-runtime');
    return jsx.jsxs('div', { className: 'LTGIS_row', children: [
      jsx.jsxs('div', { className: 'LTGIS_main', children: [
        jsx.jsx('div', { className: 'LTGIS_title', children: t(spec.labelKey) }),
        jsx.jsx('div', { className: 'LTGIS_hint', children: t(spec.hintKey) }),
        jsx.jsxs('div', { className: `LTGIS_status ${cls}`, children: [
          jsx.jsx('span', { className: 'LTGIS_dot', 'aria-hidden': 'true' }),
          detail ? jsx.jsx('span', { title: detail, children: label }) : jsx.jsx('span', { children: label }),
          // 探测到的引擎版本号：可用状态后的小字灰色标注（不可用/未探测不展示）。
          // 未知判断必须先于属性访问：首次探测前 engineStatus 尚未写入配置，
          // probe 为 undefined，先取 probe.available 会让整个设置分区崩溃空白。
          !unknown && probe!.available && probe!.version
            ? jsx.jsx('span', { className: 'LTGIS_ver', title: detail, children: probe!.version })
            : null,
        ] }),
        failed[0] ? jsx.jsx('div', { className: 'LTGIS_failed', role: 'alert', children: t('switchFailed') }) : null,
      ] }),
      jsx.jsx(primitives.Switch, { checked, disabled, label: t(spec.labelKey), onChange: onToggle }),
    ] });
  }

  function EngineRefreshRow({ status }: { status: StatusSnapshot | undefined }) {
    const react = require('react') as typeof import('react');
    const [refreshing, setRefreshing] = react.useState(false);
    const [failed, setFailed] = react.useState(false);
    const seen = react.useRef<string | undefined>(undefined);
    const snapshot = useSectionForm((s: Snapshot) => s) as Snapshot;
    const current = status?.checked_at;
    // Clear the probing state when a probe lands (checked_at changes from the
    // value seen at click time — also covers the very first probe, where
    // checked_at was previously undefined) or after a generous failsafe —
    // first probes can download the Whitebox binary.
    (0, react.useEffect)(() => {
      if (!refreshing) return;
      if (current !== undefined && current !== seen.current) {
        setRefreshing(false);
        return;
      }
      const timer = setTimeout(() => setRefreshing(false), 900_000);
      return () => clearTimeout(timer);
    }, [refreshing, current]);
    const onClick = async () => {
      seen.current = current;
      setRefreshing(true); setFailed(false);
      try {
        const prev = Number((snapshot.value as Record<string, unknown> | undefined)?.engineDetectRequest ?? 0);
        if (!await form.set('engineDetectRequest', (Number.isFinite(prev) ? prev : 0) + 1)) {
          setRefreshing(false); setFailed(true);
        }
      } catch {
        setRefreshing(false); setFailed(true);
      }
    };
    const jsx = require('react/jsx-runtime');
    return jsx.jsxs('div', { className: 'LTGIS_refreshRow', children: [
      jsx.jsx('div', { className: 'LTGIS_hint', children: status?.checked_at ?? '' }),
      failed ? jsx.jsx('div', { className: 'LTGIS_failed', role: 'alert', children: t('engineRefreshFailed') }) : null,
      jsx.jsx('button', { className: 'LTGIS_refreshBtn', type: 'button', disabled: refreshing || !snapshot.writable, onClick: () => { void onClick(); }, children: refreshing ? t('engineRefreshing') : t('engineRefresh') }),
    ] });
  }

  function LinkToolGisSection() {
    const snapshot = useSectionForm((s: Snapshot) => s) as Snapshot;
    const status = readStatus(snapshot);
    const jsx = require('react/jsx-runtime');
    const rows = [...ROWS].sort((a, b) => a.order - b.order).map(spec => jsx.jsx(SwitchRow, { spec }, spec.field));
    const engineRows = [...ENGINE_ROWS].sort((a, b) => a.order - b.order).map(spec => jsx.jsx(EngineRow, { spec, status }, spec.field));
    const body = snapshot.status === 'unavailable'
      ? jsx.jsx('p', { className: 'LTGIS_unavailable', children: t('unavailable') })
      : jsx.jsxs('div', { className: 'LTGIS_rows', children: [
        jsx.jsx('div', { className: 'LTGIS_group', children: t('hooksGroup') }),
        rows,
        jsx.jsx('div', { className: 'LTGIS_group', children: t('engineGroup') }),
        jsx.jsx('p', { className: 'LTGIS_intro', children: t('engineIntro') }),
        engineRows,
        jsx.jsx(EngineRefreshRow, { status }, 'engine-refresh'),
      ] });
    return jsx.jsxs('div', { className: 'LTGIS_section', children: [
      jsx.jsx('p', { className: 'LTGIS_intro', children: t('intro') }),
      body,
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
