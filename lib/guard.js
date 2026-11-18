import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

// src/guard.ts
import { isAbsolute as isAbsolute2, join as join3, relative as relative2, resolve as resolve3 } from "node:path";

// src/catalog.ts
import { readFileSync, existsSync } from "node:fs";
import { dirname as dirname2, resolve as resolve2, join as join2, relative, isAbsolute } from "node:path";
import { fileURLToPath as fileURLToPath2 } from "node:url";

// src/paths.ts
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
var packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
var resourceRoot = join(packageRoot, "resources", "plugin");

// src/catalog.ts
import { BUNDLED_SKILL_RANK } from "@deepseek-ai/dsh-skill";
var packageRoot2 = resolve2(dirname2(fileURLToPath2(import.meta.url)), "..");
var resourceRoot2 = join2(packageRoot2, "resources", "plugin");
var catalog = JSON.parse(readFileSync(join2(packageRoot2, "config", "catalog.json"), "utf8"));
function sessionKey(agent) {
  return agent?.session?.id ?? "";
}
function workspace(agent) {
  return agent?.session?.header?.cwd ?? process.cwd();
}

// src/guard.ts
var switchesOf = (guard) => {
  const g = guard ?? {};
  const get = (name) => g[name] ?? true;
  return {
    // 输出路径严格限制默认关闭；关闭时 Bash 路径白名单由适配层 guard 接管。
    get: (name) => name === "pathRestrict" ? g.pathRestrict ?? false : get(name)
  };
};
var benchmarkCodeRoute = (exec) => {
  const routes = globalThis[Symbol.for("linktool.benchmark.architectures")];
  return !!exec.agent && routes?.get(sessionKey(exec.agent)) === "code";
};
var inside = (path, root) => {
  const rel = relative2(resolve3(root), resolve3(path));
  return rel === "" || !rel.startsWith("..") && !isAbsolute2(rel);
};
var projectAreas = ["01_DataBackup", "02_WorkSpace", "03_Result"];
function guardBashCommand(command, guard, cwd) {
  const lower = command.toLowerCase();
  const danger = [
    [/\bformat\s+[a-zA-Z]:/, "\u78C1\u76D8\u683C\u5F0F\u5316\u547D\u4EE4"],
    [/\bdiskpart\b/, "\u78C1\u76D8\u5206\u533A\u5DE5\u5177"],
    [/\bdd\s+if=/, "\u78C1\u76D8\u955C\u50CF/\u8986\u76D6\u547D\u4EE4"],
    [/\bmkfs\./, "\u6587\u4EF6\u7CFB\u7EDF\u521B\u5EFA\u547D\u4EE4"],
    [/\bchkdsk\b/, "\u78C1\u76D8\u68C0\u67E5\u4FEE\u590D\u547D\u4EE4"],
    [/\breg\s+(?:delete|edit|add)\b/, "\u6CE8\u518C\u8868\u5199\u5165/\u5220\u9664\u547D\u4EE4"],
    [/\b(?:wget|curl)\b[^|]*\|\s*(?:sh|bash|pwsh|powershell)\b/, "\u8FDC\u7A0B\u811A\u672C\u76F4\u63A5\u6267\u884C\u7BA1\u9053"],
    [/>\s*\/dev\/(?:sd[a-z]|nvme)/, "\u76F4\u63A5\u5199\u5165\u7269\u7406\u5757\u8BBE\u5907"]
  ];
  for (const [pattern, label] of danger) if (pattern.test(lower)) return `\u68C0\u6D4B\u5230\u5371\u9669\u64CD\u4F5C\uFF08${label}\uFF09\uFF0C\u7981\u6B62\u6267\u884C\u3002`;
  if (!guard.pathRestrict) return void 0;
  for (const area of projectAreas) {
    if (lower.startsWith(area.toLowerCase())) return void 0;
  }
  const redirect = /(?:^|[\s;(])(?:>>|1>>|2>>|2>|1>|>|(?:<<?))\s*("[^"]+"|'[^']+'|[^\s&|;<>]+)/g;
  for (const match of command.matchAll(redirect)) {
    const target = match[1].replace(/^["']|["']$/g, "");
    if (!target || target.startsWith("&") || target.startsWith("/dev/")) continue;
    if (!isAbsolute2(target)) {
      if (target.startsWith("..") || target.includes("..")) return `Bash \u91CD\u5B9A\u5411\u76EE\u6807 '${target}' \u8D8A\u51FA\u9879\u76EE\u76EE\u5F55\u3002`;
      continue;
    }
    if (projectAreas.some((area) => inside(target, join3(cwd, area)))) continue;
    return `Bash \u91CD\u5B9A\u5411\u76EE\u6807 '${target}' \u8D8A\u51FA\u9879\u76EE\u76EE\u5F55\uFF0801_DataBackup/02_WorkSpace/03_Result\uFF09\u3002`;
  }
  return void 0;
}
function guardArcpyCommand(command) {
  const engineCli = /\bqgis_process\b|\bwhitebox_tools?\b|\bgdal[a-z_]*\b|\bogr[a-z0-9_]*\b|\binner_\w+\b|\bwbt_\w+\b/i;
  if (/arcpy|arcgis|\.gdb\b|\.shp\b|shapefile/i.test(command) || engineCli.test(command)) {
    return "\u68C0\u6D4B\u5230\u901A\u8FC7\u547D\u4EE4\u884C\u76F4\u63A5\u6267\u884C GIS/ArcPy/QGIS/Whitebox/GDAL \u64CD\u4F5C\u3002\u8BF7\u6539\u7528 arcgis-mcp-server \u7684 execute_gis_tool MCP \u5DE5\u5177\u6267\u884C\u8BE5 GIS \u64CD\u4F5C\uFF08tool_name \u524D\u7F00 inner_/wbt_/gdal_/qgis_/arcpy_ \u53EF\u6307\u5B9A\u5F15\u64CE\uFF09\uFF0C\u4E0D\u8981\u7528 python -c\u3001\u811A\u672C\u5305\u88C5\u7B49\u65B9\u5F0F\u7ED5\u8FC7 MCP\u3002";
  }
  return void 0;
}
function guardWrapperCommand(command) {
  const wrapper = /(\.(?:bat|sh|cmd)\b.*\b(?:python|uv\s+run)\b)|(\b(?:bash|sh|cmd|source)\s+\S+\.(?:bat|sh|cmd)\b)/i;
  if (wrapper.test(command)) return "Bash \u547D\u4EE4\u5C1D\u8BD5\u7ECF .bat/.sh \u5305\u88C5\u811A\u672C\u6267\u884C\uFF08\u53EF\u80FD\u5185\u5D4C arcpy\uFF09\uFF0C\u7981\u6B62\u7ED5\u8FC7 GIS MCP\u3002";
  return void 0;
}
function guardWritableContent(toolName, args, mcpRestrict) {
  if (!["Write", "write", "Edit", "edit", "Update"].includes(toolName)) return void 0;
  const content = args.content ?? args.new_string;
  if (typeof content !== "string" || !content) return void 0;
  if (mcpRestrict && (/import\s+arcpy|from\s+arcpy|arcpy\./i.test(content) || /\bwhitebox_tools\b|import\s+whitebox|\bqgis_process\b|\bogr2ogr\b|\bgdal(?:info|translate|warp|contour|dem|grid|rasterize|polygonize|merge|buildvrt|addo|sieve|fillnodata|nearblack|transform)\b/.test(content))) {
    return "\u5199\u5165\u5185\u5BB9\u542B GIS \u5F15\u64CE\uFF08arcpy/Whitebox/QGIS/GDAL CLI\uFF09\u76F4\u63A5\u6267\u884C\u7279\u5F81\uFF0C\u7981\u6B62 Write/Edit\u3002\u4E00\u5207 GIS \u6267\u884C\u5FC5\u987B\u7ECF execute_gis_tool\uFF08\u7531 @gis-tool \u5728 Workflow \u5951\u7EA6\u5185\u8C03\u7528\uFF09\u3002";
  }
  return void 0;
}
async function guardPreToolUse(exec, switches, mapArguments) {
  if (benchmarkCodeRoute(exec)) return void 0;
  const args = mapArguments(exec.name);
  const skillMd = switches.get("skillMdGuard") && ["Read", "read"].includes(exec.name) && typeof args.file_path === "string" && /(^|[/\\])SKILL\.md$/i.test(args.file_path);
  if (skillMd) return "\u7981\u6B62\u4F7F\u7528 Read \u5DE5\u5177\u8BFB\u53D6 SKILL.md \u6587\u4EF6\u3002\u8BF7\u901A\u8FC7 Skill \u5DE5\u5177\u4EE5\u6280\u80FD\u540D\u79F0\u52A0\u8F7D\u5BF9\u5E94\u6280\u80FD\u3002";
  const mcpRestrict = switches.get("mcpRestrict");
  if (mcpRestrict) {
    const content = guardWritableContent(exec.name, args, true);
    if (content) return content;
  }
  if (exec.name === "Bash" || exec.name === "bash") {
    const command = typeof args.command === "string" ? args.command : "";
    if (command) {
      if (mcpRestrict) {
        const gis = guardArcpyCommand(command);
        if (gis) return gis;
      }
      if (switches.get("antiBypass")) {
        const wrapper = guardWrapperCommand(command);
        if (wrapper) return wrapper;
      }
      const path = guardBashCommand(command, { pathRestrict: switches.get("pathRestrict") }, workspace(exec.agent));
      if (path) return path;
    }
  }
  return void 0;
}
var hookSwitchOf = (hookId) => hookId.includes("gis-tool-log") ? "gisToolLog" : hookId.includes("param-validate") ? "paramValidate" : hookId.includes("data-backup") ? "dataBackup" : hookId.includes("result-validate") ? "resultValidate" : hookId.includes("failure-pattern-detector") ? "failurePattern" : hookId.includes("context-compress") ? "contextCompress" : hookId.includes("modify-protect-hook") ? "pathRestrict" : hookId.includes("anti-bypass") ? "antiBypass" : void 0;
export {
  benchmarkCodeRoute,
  guardArcpyCommand,
  guardBashCommand,
  guardPreToolUse,
  guardWrapperCommand,
  guardWritableContent,
  hookSwitchOf,
  switchesOf
};
//# sourceMappingURL=guard.js.map
