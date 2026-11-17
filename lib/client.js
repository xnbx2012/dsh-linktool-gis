window.__ModuleLoader__.load({
	id: "@linktool/dsh-plugin",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// client/settings-page.tsx
var settings_page_exports = {};
__export(settings_page_exports, {
  apply: () => apply,
  inject: () => inject
});
module.exports = __toCommonJS(settings_page_exports);
var NAMESPACE = "linktool-plugin";
var NS = "settings.linktoolGis";
var zh = {
  title: "LinkTool-GIS",
  intro: "GIS \u63D2\u4EF6\u5404 Hook \u7684\u542F\u7528\u5F00\u5173\u3002\u6539\u52A8\u7ACB\u5373\u751F\u6548\uFF08volatile \u914D\u7F6E\uFF09\uFF0C\u65E0\u9700\u91CD\u542F Harness\u3002",
  pathRestrict: "\u8F93\u51FA\u8DEF\u5F84\u4E25\u683C\u9650\u5236",
  pathRestrictHint: "\u5F00\u542F\u540E\u6587\u4EF6\u5DE5\u5177\u3001Bash \u4E0E GIS \u8F93\u51FA\u4EC5\u5141\u8BB8 01_DataBackup\uFF08\u53EA\u8BFB\uFF09/02_WorkSpace/03_Result\u3002\u9ED8\u8BA4\u5173\u95ED\uFF1A\u8DEF\u5F84\u7B56\u7565\u4EA4\u7531 Harness \u63A7\u5236\u3002",
  mcpRestrict: "MCP \u6267\u884C\u9650\u5236",
  mcpRestrictHint: "\u62E6\u622A GIS \u7C7B\u547D\u4EE4\u884C/\u4EE3\u7801\u5E76\u5F15\u5BFC\u4F7F\u7528 GIS MCP \u6267\u884C\uFF1B\u666E\u901A\u547D\u4EE4\u884C\u4E0E\u4EE3\u7801\u64CD\u4F5C\u4E0D\u53D7\u5F71\u54CD\u3002\u9ED8\u8BA4\u5F00\u542F\u3002",
  gisToolLog: "GIS \u5DE5\u5177\u65E5\u5FD7\u8BB0\u5F55",
  gisToolLogHint: "\u6BCF\u6B21 execute_gis_tool \u8C03\u7528\u5199\u5165 02_WorkSpace/gis-tool-logs.json\uFF0C\u4F9B\u62A5\u544A\u4E0E\u590D\u73B0\u4F7F\u7528\u3002",
  paramValidate: "\u53C2\u6570\u6821\u9A8C",
  paramValidateHint: "\u6267\u884C\u524D\u5BF9\u7167 ArcPy \u5DE5\u5177 schema \u68C0\u67E5\u5FC5\u586B\u53C2\u6570\u4E0E\u8F93\u5165\u8DEF\u5F84\u3002",
  dataBackup: "\u6570\u636E\u5907\u4EFD",
  dataBackupHint: "\u7834\u574F\u6027 GIS \u5DE5\u5177\u64CD\u4F5C 01_DataBackup \u6570\u636E\u524D\u81EA\u52A8\u5907\u4EFD\u5E76\u91CD\u5B9A\u5411\u3002",
  resultValidate: "\u7ED3\u679C\u9A8C\u8BC1",
  resultValidateHint: "GIS \u8F93\u51FA\u5C5E\u6027\u7A7A\u503C\u7387\u3001\u8981\u7D20\u6570\u4E0E\u51E0\u4F55\u4E00\u81F4\u6027\u7684\u81EA\u52A8\u68C0\u67E5\u3002",
  failurePattern: "\u5931\u8D25\u6A21\u5F0F\u68C0\u6D4B",
  failurePatternHint: "\u540C\u4E00\u5DE5\u5177\u8FDE\u7EED\u5931\u8D25\u65F6\u63D0\u793A\u505C\u6B62\u91CD\u8BD5\u5E76\u62A5\u544A\u6839\u56E0\u3002",
  contextCompress: "\u4E0A\u4E0B\u6587\u538B\u7F29\u6458\u8981",
  contextCompressHint: "\u4E0A\u4E0B\u6587\u538B\u7F29\u540E\u91CD\u65B0\u6CE8\u5165 GIS \u64CD\u4F5C\u5386\u53F2\u6458\u8981\u3002",
  antiBypass: "\u7ED5\u8FC7\u9632\u62A4",
  antiBypassHint: "\u7981\u6B62\u7ECF Write/Edit \u6216 .bat/.sh \u5305\u88C5\u811A\u672C\u4EA7\u51FA arcpy \u6267\u884C\u3002",
  skillMdGuard: "SKILL.md \u4FDD\u62A4",
  skillMdGuardHint: "\u7981\u6B62 Read \u76F4\u8BFB\u6280\u80FD\u5B9A\u4E49\u6587\u4EF6\uFF0C\u6539\u7528 Skill \u5DE5\u5177\u52A0\u8F7D\u3002",
  switchFailed: "\u5F00\u5173\u5199\u5165\u5931\u8D25\uFF0C\u8BF7\u91CD\u8BD5",
  unavailable: "Host \u672A\u63D0\u4F9B linktool-plugin \u914D\u7F6E\uFF0C\u8BBE\u7F6E\u9879\u4E0D\u53EF\u7528\u3002"
};
var en = {
  title: "LinkTool-GIS",
  intro: "Enable switches for the GIS plugin hooks. Changes apply immediately (volatile config) without restarting the Harness.",
  pathRestrict: "Strict output path limitation",
  pathRestrictHint: "When on, file tools, Bash and GIS output are limited to 01_DataBackup (read-only) / 02_WorkSpace / 03_Result. Off by default: path policy belongs to the Harness.",
  mcpRestrict: "MCP execution restriction",
  mcpRestrictHint: "Intercepts GIS command-line/code attempts and routes them to the GIS MCP; ordinary commands and code are untouched. On by default.",
  gisToolLog: "GIS tool logging",
  gisToolLogHint: "Writes every execute_gis_tool call to 02_WorkSpace/gis-tool-logs.json for reports and reproduction.",
  paramValidate: "Parameter validation",
  paramValidateHint: "Pre-checks required parameters and input paths against the ArcPy tool schema.",
  dataBackup: "Data backup",
  dataBackupHint: "Backs up and redirects 01_DataBackup inputs before destructive GIS tools.",
  resultValidate: "Result validation",
  resultValidateHint: "Automatic checks of output attribute null rates, feature counts, and geometry.",
  failurePattern: "Failure pattern detection",
  failurePatternHint: "Advises stopping retries after the same tool fails repeatedly.",
  contextCompress: "Context compaction summary",
  contextCompressHint: "Re-injects the compressed GIS operation history after compaction.",
  antiBypass: "Bypass protection",
  antiBypassHint: "Denies arcpy execution produced through Write/Edit or .bat/.sh wrapper scripts.",
  skillMdGuard: "SKILL.md protection",
  skillMdGuardHint: "Reading skill definitions through Read is forbidden; load them with Skill.",
  switchFailed: "Toggle failed, please retry",
  unavailable: "The Host does not serve the linktool-plugin namespace; settings are unavailable."
};
var ROWS = [
  { field: "guardPathRestrict", labelKey: "pathRestrict", hintKey: "pathRestrictHint", order: 10 },
  { field: "guardMcpRestrict", labelKey: "mcpRestrict", hintKey: "mcpRestrictHint", order: 20 },
  { field: "guardGisToolLog", labelKey: "gisToolLog", hintKey: "gisToolLogHint", order: 30 },
  { field: "guardParamValidate", labelKey: "paramValidate", hintKey: "paramValidateHint", order: 40 },
  { field: "guardDataBackup", labelKey: "dataBackup", hintKey: "dataBackupHint", order: 50 },
  { field: "guardResultValidate", labelKey: "resultValidate", hintKey: "resultValidateHint", order: 60 },
  { field: "guardFailurePattern", labelKey: "failurePattern", hintKey: "failurePatternHint", order: 70 },
  { field: "guardContextCompress", labelKey: "contextCompress", hintKey: "contextCompressHint", order: 80 },
  { field: "guardAntiBypass", labelKey: "antiBypass", hintKey: "antiBypassHint", order: 90 },
  { field: "guardSkillMd", labelKey: "skillMdGuard", hintKey: "skillMdGuardHint", order: 100 }
];
var inject = ["slots", "locale", "configForms"];
function apply(ctx) {
  const t = ctx.locale.bind(NS);
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), "linktool-gis: dictionaries");
  const form = ctx.configForms.get(NAMESPACE);
  const css = ".LTGIS_section{max-width:760px;color:var(--dsw-alias-label-primary);flex-direction:column;gap:16px;display:flex}.LTGIS_intro{color:var(--dsw-alias-label-secondary);margin:0;font-size:13px;line-height:20px}.LTGIS_unavailable{color:var(--dsw-alias-label-tertiary);margin:0;font-size:13px}.LTGIS_rows{flex-direction:column;display:flex}.LTGIS_row{border-bottom:.5px solid var(--dsw-alias-border-l2);justify-content:space-between;align-items:center;gap:24px;padding:16px 0;display:flex}.LTGIS_main{min-width:0;flex:1}.LTGIS_title{font-size:14px;line-height:20px}.LTGIS_hint{color:var(--dsw-alias-label-secondary);margin-top:4px;font-size:12px;line-height:18px}.LTGIS_failed{color:var(--dsw-alias-state-error-primary);margin-top:4px;font-size:12px}";
  ctx.effect(() => {
    if (typeof document === "undefined") return;
    const tagId = "@linktool/dsh-plugin/settings.module.css";
    if (document.querySelector('style[data-plugin-css="' + tagId + '"]') !== null) return;
    const tag = document.createElement("style");
    tag.dataset.plugin = "@linktool/dsh-plugin";
    tag.dataset.pluginCss = tagId;
    tag.textContent = css;
    document.head.appendChild(tag);
    return () => {
      tag.remove();
    };
  }, "linktool-gis: styles");
  const useSectionForm = (selector) => {
    const react = require("react");
    const [value, setValue] = react.useState(() => selector(form.getSnapshot()));
    (0, react.useEffect)(() => form.subscribe(() => setValue(selector(form.getSnapshot()))), []);
    return value;
  };
  function SwitchRow({ spec }) {
    const snapshot = useSectionForm((s) => s);
    const busy = require("react").useState(false);
    const failed = require("react").useState(false);
    const primitives = require("@deepseek-ai/dsh-client-ui-primitives");
    const [, setBusy] = busy;
    const [, setFailed] = failed;
    const field = spec.field;
    const checked = snapshot.status === "ready" ? Boolean(snapshot.value?.[field]) : field === "guardPathRestrict";
    const disabled = !snapshot.writable || busy[0];
    const onToggle = async (next) => {
      setBusy(true);
      setFailed(false);
      try {
        if (!await form.set(field, next)) setFailed(true);
      } catch {
        setFailed(true);
      } finally {
        setBusy(false);
      }
    };
    const jsx = require("react/jsx-runtime");
    return jsx.jsxs("div", { className: "LTGIS_row", children: [
      jsx.jsxs("div", { className: "LTGIS_main", children: [
        jsx.jsx("div", { className: "LTGIS_title", children: t(spec.labelKey) }),
        jsx.jsx("div", { className: "LTGIS_hint", children: t(spec.hintKey) }),
        failed[0] ? jsx.jsx("div", { className: "LTGIS_failed", role: "alert", children: t("switchFailed") }) : null
      ] }),
      jsx.jsx(primitives.Switch, { checked, disabled, label: t(spec.labelKey), onChange: onToggle })
    ] });
  }
  function LinkToolGisSection() {
    const snapshot = useSectionForm((s) => s);
    const jsx = require("react/jsx-runtime");
    const rows = [...ROWS].sort((a, b) => a.order - b.order).map((spec) => jsx.jsx(SwitchRow, { spec }, spec.field));
    return jsx.jsxs("div", { className: "LTGIS_section", children: [
      jsx.jsx("p", { className: "LTGIS_intro", children: t("intro") }),
      snapshot.status === "unavailable" ? jsx.jsx("p", { className: "LTGIS_unavailable", children: t("unavailable") }) : jsx.jsx("div", { className: "LTGIS_rows", children: rows })
    ] });
  }
  ctx.effect(() => ctx.configForms.whileServed([NAMESPACE], () => ctx.slots.inject("settings.section", () => ctx.slots.register({
    name: "settings.section",
    id: "linktool-gis",
    order: 90,
    label: () => t("title"),
    locale: NS
  }, LinkToolGisSection))), "linktool-gis: settings section");
}
//# sourceMappingURL=client.js.map

		return { apply: module.exports.apply, inject: module.exports.inject };
	}
});
//# sourceMappingURL=client.js.map