import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

// src/mcp.ts
import { existsSync as existsSync3 } from "node:fs";
import { dirname as dirname3, join as join4 } from "node:path";

// src/paths.ts
import { join, dirname, resolve } from "node:path";
import { existsSync } from "node:fs";
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
function childEnvironment(cwd, role = "") {
  const root = resourceRoot;
  const env = {
    ...process.env,
    DSH_PLUGIN_ROOT: root,
    DSH_PLUGIN_DIR: root,
    DSH_PROJECT_DIR: cwd,
    CLAUDE_PLUGIN_ROOT: root,
    CLAUDE_PLUGIN_DIR: root,
    CLAUDE_PROJECT_DIR: cwd,
    CLAUDE_CONFIG_DIR: process.env.DSH_HOME ?? join(process.env.USERPROFILE ?? process.env.HOME ?? cwd, ".dsh"),
    CLAUDE_AGENT_NAME: role,
    CLAUDE_AGENT: role,
    CLAUDE_SUBAGENT_TYPE: role,
    PYTHONIOENCODING: "utf-8",
    PYTHONDONTWRITEBYTECODE: "1",
    USER_HOME: process.env.USERPROFILE ?? process.env.HOME ?? cwd,
    UV_PROJECT_ENVIRONMENT: join(packageRoot, ".runtime", "hooks")
  };
  const bin = join(resourceRoot, "bin");
  const uvBin = join(process.env.USERPROFILE ?? "", ".local", "bin");
  env.PATH = [bin, ...existsSync(uvBin) ? [uvBin] : [], process.env.PATH ?? ""].join(process.platform === "win32" ? ";" : ":");
  return env;
}

// src/catalog.ts
import { readFileSync, existsSync as existsSync2 } from "node:fs";
import { dirname as dirname2, resolve as resolve2, join as join2, relative, isAbsolute } from "node:path";
import { fileURLToPath as fileURLToPath2 } from "node:url";
import { BUNDLED_SKILL_RANK } from "@deepseek-ai/dsh-skill";
var packageRoot2 = resolve2(dirname2(fileURLToPath2(import.meta.url)), "..");
var resourceRoot2 = join2(packageRoot2, "resources", "plugin");
var catalog = JSON.parse(readFileSync(join2(packageRoot2, "config", "catalog.json"), "utf8"));
var readJson = (path) => JSON.parse(readFileSync(path, "utf8"));

// src/engines.ts
import { join as join3 } from "node:path";

// src/tools.ts
import { defineTool } from "@deepseek-ai/dsh-tools";

// src/engines.ts
var engineSwitchesFile = () => join3(packageRoot2, ".runtime", "engine-switches.json");

// src/mcp.ts
function resolveMcp(server, original, projectDir = process.cwd()) {
  const relocate = (value) => expandPaths(value, projectDir, true);
  const env = Object.fromEntries(Object.entries(original.env ?? {}).map(([k, v]) => [k, relocate(v)]));
  for (const key of Object.keys(env)) if (process.env[key] !== void 0) env[key] = process.env[key];
  const common = { serverName: server, toolCallTimeoutMs: 6e5, failOnStartupError: false };
  if (original.type === "streamable-http") return { ...common, transport: "streamable-http", url: relocate(process.env.LINKTOOL_MEMORY_URL ?? original.url), headers: Object.fromEntries(Object.entries(original.headers ?? {}).map(([k, v]) => [k, relocate(k.toLowerCase() === "authorization" ? process.env.LINKTOOL_MEMORY_AUTHORIZATION ?? v : v)])) };
  let command = relocate(original.command);
  let args = (original.args ?? []).map(relocate);
  args = args.map((arg) => arg === "mcp[cli]" ? "mcp[cli]>=1.26,<2" : arg);
  if (command === "npx" && args[0] !== "-y" && args[0] !== "--yes") args.unshift("-y");
  let cwd = original.cwd ? relocate(original.cwd) : projectDir;
  if (/[/\\]knowledge-db-mcp[/\\]run\.bat$/i.test(command)) {
    cwd = dirname3(command);
    command = "uv";
    args = ["run", "python", join4(cwd, "main.py")];
  }
  const script = args.find((a) => a.endsWith(".py") && existsSync3(a));
  if (script && existsSync3(join4(dirname3(script), "pyproject.toml")) && command === "uv" && args[0] === "run") {
    cwd = dirname3(script);
    args = ["run", "--project", cwd, ...args.slice(1)];
  } else if (command === "uv" && args[0] === "run") args = ["run", "--no-project", ...args.slice(1)];
  return {
    ...common,
    transport: "stdio",
    command,
    args,
    cwd,
    env: {
      ...childEnvironment(projectDir),
      ...env,
      UV_PROJECT_ENVIRONMENT: join4(packageRoot2, ".runtime", "mcp", server),
      // 五引擎开关文件：适配层随设置页 volatile 写入实时落盘，MCP 每次调用读取。
      // color-style 需要同一份开关来选择制图后端（ArcGIS Pro 优先，QGIS 兜底）。
      ...["arcgis-mcp-server", "color-style"].includes(server) ? { LINKTOOL_ENGINE_SWITCHES: engineSwitchesFile() } : {}
    }
  };
}
function resolvedServers(projectDir = process.cwd()) {
  const original = readJson(join4(packageRoot2, "config/mcp.json"));
  return Object.fromEntries(Object.entries(original).map(([name, config]) => [name, resolveMcp(name, config, projectDir)]));
}
export {
  resolveMcp,
  resolvedServers
};
//# sourceMappingURL=mcp.js.map
