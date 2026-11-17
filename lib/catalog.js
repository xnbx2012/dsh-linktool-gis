import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

// src/catalog.ts
import { readFileSync, existsSync } from "node:fs";
import { dirname as dirname2, resolve as resolve2, join as join2, relative, isAbsolute } from "node:path";
import { fileURLToPath as fileURLToPath2 } from "node:url";
import { createHash } from "node:crypto";

// src/paths.ts
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
var packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
var resourceRoot = join(packageRoot, "resources", "plugin");
function expandPaths(value, cwd = process.cwd(), strict = false) {
  const replacements = {
    DSH_ADAPTER_ROOT: packageRoot,
    DSH_PLUGIN_ROOT: resourceRoot,
    DSH_PLUGIN_DIR: resourceRoot,
    DSH_PROJECT_DIR: cwd,
    CLAUDE_PLUGIN_ROOT: resourceRoot,
    CLAUDE_PLUGIN_DIR: resourceRoot,
    CLAUDE_PROJECT_DIR: cwd
  };
  return value.replace(/\$\{([A-Z_]+)\}\$?/g, (token, name) => {
    const replacement = replacements[name] ?? (strict ? process.env[name] : void 0);
    if (replacement === void 0) return "";
    return replacement.replaceAll("\\", "/");
  });
}

// src/catalog.ts
import { BUNDLED_SKILL_RANK } from "@deepseek-ai/dsh-skill";
var packageRoot2 = resolve2(dirname2(fileURLToPath2(import.meta.url)), "..");
var resourceRoot2 = join2(packageRoot2, "resources", "plugin");
var guardFields = {
  pathRestrict: "guardPathRestrict",
  mcpRestrict: "guardMcpRestrict",
  gisToolLog: "guardGisToolLog",
  paramValidate: "guardParamValidate",
  dataBackup: "guardDataBackup",
  resultValidate: "guardResultValidate",
  failurePattern: "guardFailurePattern",
  contextCompress: "guardContextCompress",
  antiBypass: "guardAntiBypass",
  skillMdGuard: "guardSkillMd"
};
var catalog = JSON.parse(readFileSync(join2(packageRoot2, "config", "catalog.json"), "utf8"));
var readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
function loadRuntime() {
  return readJson(join2(packageRoot2, "config", "runtime.json"));
}
function body(doc) {
  const text = readFileSync(join2(resourceRoot2, doc.path), "utf8").replace(/^\uFEFF/, "");
  const match = /^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/.exec(text);
  const content = match ? text.slice(match[0].length) : text;
  if (createHash("sha256").update(content.replace(/\r\n/g, "\n")).digest("hex") !== doc.bodySha256) throw new Error(`Prompt integrity mismatch: ${doc.path}. Rebuild the catalog deliberately after source changes.`);
  return content;
}
function agentName(name) {
  return name.replace(/^@/, "").replace(/^linktool-plugin:/, "").replace(/^linktool:/, "");
}
function getAgent(name) {
  const doc = catalog.agents.find((a) => a.name === agentName(name));
  if (!doc) throw new Error(`Unknown LinkTool agent: ${name}`);
  return doc;
}
function getSkill(name) {
  const doc = catalog.skills.find((s) => s.name === name.replace(/^linktool-plugin:/, ""));
  if (!doc) throw new Error(`Unknown LinkTool skill: ${name}`);
  return doc;
}
function skillAllowed(skill, agent, config) {
  if (!agent) return true;
  const owners = skill.agent ? [agentName(skill.agent)] : config.agentSkillRules[skill.name];
  return !owners || owners.includes(agent.name);
}
function definition(skill) {
  return { name: skill.name, description: String(skill.metadata.description ?? ""), invocation: skill.invocation, source: "bundled", provider: "linktool-plugin", path: join2(resourceRoot2, skill.path), resourceBase: { kind: "directory", path: dirname2(join2(resourceRoot2, skill.path)) }, content: body(skill), metadata: { ...skill.metadata, linktool: { context: skill.context, agent: skill.agent, allowedTools: skill.allowedTools } } };
}
function skillProvider(agent, config) {
  return { name: "linktool-plugin", async list() {
    return catalog.skills.filter((s) => skillAllowed(s, agent, config)).map((s) => ({ ...definitionSummary(s), rank: BUNDLED_SKILL_RANK, locator: s.name, metadata: s.metadata }));
  }, async get(candidate) {
    const s = getSkill(String(candidate.locator));
    if (!skillAllowed(s, agent, config)) return void 0;
    return definition(s);
  } };
}
function definitionSummary(s) {
  return { name: s.name, description: String(s.metadata.description ?? ""), invocation: s.invocation, source: "bundled", provider: "linktool-plugin", path: join2(resourceRoot2, s.path), resourceBase: { kind: "directory", path: dirname2(join2(resourceRoot2, s.path)) } };
}
function workspace(agent) {
  return agent?.session.header.cwd ?? process.cwd();
}
function inside(path, root) {
  const rel = relative(resolve2(root), resolve2(path));
  return rel === "" || !rel.startsWith("..") && !isAbsolute(rel);
}
function resourcePath(path, agent, skill) {
  path = expandPaths(path, workspace(agent));
  const normalized = path.replaceAll("\\", "/").replace(/^\.\//, "");
  if (/^(?:plugin\/|\$\{CLAUDE_PLUGIN_ROOT\}\/)/.test(normalized)) return resolve2(resourceRoot2, normalized.replace(/^(?:plugin\/|\$\{CLAUDE_PLUGIN_ROOT\}\/)/, ""));
  if (skill && !isAbsolute(path)) {
    const local = resolve2(dirname2(join2(resourceRoot2, skill.path)), normalized);
    if (inside(local, resourceRoot2) && existsSync(local)) return local;
  }
  return resolve2(workspace(agent), path);
}
function benchmarkPolicy(agent) {
  return agent ? globalThis[Symbol.for("linktool.benchmark.policies")]?.get(agent.session.id) ?? {} : {};
}
export {
  agentName,
  benchmarkPolicy,
  body,
  catalog,
  definition,
  getAgent,
  getSkill,
  guardFields,
  inside,
  loadRuntime,
  packageRoot2 as packageRoot,
  readJson,
  resourcePath,
  resourceRoot2 as resourceRoot,
  skillAllowed,
  skillProvider,
  workspace
};
//# sourceMappingURL=catalog.js.map
