import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

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
export {
  childEnvironment,
  expandPaths
};
//# sourceMappingURL=paths.js.map
