import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

// src/hooks.ts
import { spawn } from "node:child_process";
import { join as join3 } from "node:path";
import { createUserMessage } from "@deepseek-ai/dsh-llm";

// src/tools.ts
import { defineTool } from "@deepseek-ai/dsh-tools";

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
    if (inside(local, resourceRoot2) && existsSync2(local)) return local;
  }
  return resolve2(workspace(agent), path);
}
function benchmarkPolicy(agent) {
  return agent ? globalThis[Symbol.for("linktool.benchmark.policies")]?.get(agent.session.id) ?? {} : {};
}

// src/tools.ts
var builtins = { Read: "read", Write: "write", Edit: "edit", Update: "edit", Glob: "glob", Grep: "grep", Bash: "bash", WebFetch: "web_fetch", WebSearch: "web_search", Web_Search: "web_search", ListMcpResourcesTool: "list_mcp_resources", ReadMcpResourceTool: "read_mcp_resource", Wrtie: "write", AskUserQuestion: "ask_user_question" };
function mcpTarget(name, config) {
  const match = /^mcp__(?:plugin_linktool-plugin_)?(.+)__(.+)$/.exec(name);
  if (!match) return builtins[config.toolAliases[name] ?? name] ?? name;
  const server = config.serverAliases[match[1]] ?? match[1];
  return `mcp__${server}__${match[2]}`;
}
function mapArguments(target, raw, agent, skill) {
  const input = { ...raw };
  for (const key of ["file_path", "path"]) if (typeof input[key] === "string") input[key] = resourcePath(input[key], agent, skill);
  if (target === "web_search" && typeof input.query === "string") {
    input.queries = [input.query];
    delete input.query;
  }
  if (target === "web_fetch") delete input.prompt;
  if (target === "bash" || target === "pwsh") {
    input.description ??= "Execute the packaged LinkTool command";
    if (input.timeout !== void 0) {
      input.timeoutMs = input.timeout;
      delete input.timeout;
    }
    if (typeof input.command === "string") input.command = translateCommand(input.command, agent, skill);
  }
  return input;
}
function translateCommand(command, agent, skill) {
  const replace = (text, pattern) => text.replace(pattern, (path, offset) => {
    const relocated = resourcePath(path, agent, skill).replaceAll("\\", "/");
    if (!inside(relocated, resourceRoot2)) return path;
    return ['"', "'"].includes(text[offset - 1]) ? relocated : "'" + relocated.replaceAll("'", "'\\''") + "'";
  });
  let out = replace(command, /(?:\.\/)?plugin\/(?:skills|scripts|bin|workflows)\/[^\s"'`]+/g);
  out = replace(out, /\$\{(?:CLAUDE|DSH)_PLUGIN_(?:ROOT|DIR)\}\$?\/(?:skills|scripts|bin|workflows)\/[^\s"'`]+/g);
  if (skill) out = replace(out, /(?:\.\/)?scripts\/[^\s"'`]+/g);
  out = expandPaths(out, workspace(agent));
  return out;
}

// src/hooks.ts
var names = { read: "Read", read_image: "Read", write: "Write", edit: "Edit", glob: "Glob", grep: "Grep", bash: "Bash", pwsh: "Bash", str_replace_editor: "Edit" };
function legacyTool(name) {
  if (name === "Wrtie") return "Write";
  if (name === "Update") return "Edit";
  if (names[name]) return names[name];
  if (/^mcp__/.test(name) && !name.startsWith("mcp__plugin_linktool-plugin_")) return name.replace(/^mcp__([^_]+(?:-[^_]+)*)__/, "mcp__plugin_linktool-plugin_$1__");
  return name;
}
async function runCommand(command, payload, cwd, signal, timeout, agentName = "") {
  const expanded = expandPaths(command, cwd);
  const isWindows = process.platform === "win32";
  return new Promise((resolve3, reject) => {
    const child = spawn(isWindows ? process.env.ComSpec ?? "cmd.exe" : "/bin/sh", isWindows ? ["/d", "/s", "/c", expanded] : ["-c", expanded], { cwd, windowsHide: true, windowsVerbatimArguments: isWindows, env: childEnvironment(cwd, agentName), stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    let failure;
    const terminate = () => {
      failure ??= new Error("Hook cancelled or timed out");
      if (isWindows && child.pid) {
        const killer = spawn("taskkill.exe", ["/pid", String(child.pid), "/t", "/f"], { windowsHide: true, stdio: "ignore" });
        killer.on("error", () => child.kill());
      } else child.kill("SIGTERM");
    };
    const timer = setTimeout(terminate, timeout);
    timer.unref();
    signal.addEventListener("abort", terminate, { once: true });
    child.stdout.on("data", (b) => {
      stdout += b.toString("utf8");
      if (stdout.length > 2e6) terminate();
    });
    child.stderr.on("data", (b) => {
      stderr = (stderr + b.toString("utf8")).slice(-16e3);
    });
    child.stdin.on("error", () => {
    });
    child.on("error", (e) => {
      failure = e;
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", terminate);
      if (failure) reject(failure);
      else resolve3({ code: code ?? 1, stdout, stderr });
    });
    child.stdin.end(JSON.stringify(payload));
    if (signal.aborted) terminate();
  });
}
var HookBridge = class {
  constructor(ctx, config, identity, currentSkill = () => void 0) {
    this.ctx = ctx;
    this.config = config;
    this.identity = identity;
    this.currentSkill = currentSkill;
    this.bindings = readJson(join3(packageRoot2, "config/hooks.json")).hooks;
  }
  bindings;
  async run(event, exec, result, agent, signal = new AbortController().signal) {
    const owner = agent ?? exec?.agent;
    const benchmarkRoutes = globalThis[Symbol.for("linktool.benchmark.architectures")];
    if (owner && benchmarkRoutes?.get(owner.session.id) === "code") return { contexts: [] };
    const name = exec ? legacyTool(exec.name) : "auto";
    const payload = { session_id: owner?.session.id ?? "", transcript_path: "", cwd: workspace(owner), hook_event_name: event, agent_name: this.identity(owner), agent: this.identity(owner), tool_name: name, tool_use_id: exec?.callId ?? "", tool_input: exec ? mapArguments(mcpTarget(exec.name, this.config), exec.arguments, owner, this.currentSkill(owner)) : {}, ...result ? { tool_response: { content: result.content, isError: result.isError, ..."value" in result ? { structuredContent: result.value } : {}, ..."error" in result ? { error: result.error } : {} } } : {} };
    if (result) payload.tool_input.tool_response = payload.tool_response;
    const merged = { contexts: [] };
    if (!this.config.hooksEnabled) return merged;
    for (const [bindingIndex, binding] of (this.bindings[event] ?? []).entries()) {
      if (binding.matcher && binding.matcher !== "*" && !new RegExp(`^(?:${binding.matcher})$`).test(name)) continue;
      for (const [hookIndex, hook] of binding.hooks.entries()) {
        const hookId = event + ":" + bindingIndex + ":" + hookIndex;
        if (benchmarkPolicy(owner).hooks?.includes(hookId)) continue;
        const observer = globalThis[Symbol.for("linktool.benchmark.observe")];
        const hookStart = performance.now();
        if (hook.type !== "command" || hook.async) throw new Error(`Unsupported hook execution type in ${event}`);
        const run = await runCommand(hook.command, payload, workspace(owner), signal, (hook.timeout ?? this.config.hookTimeoutMs / 1e3) * 1e3, this.identity(owner));
        observer?.(owner?.session.id ?? "", "hook/end", { hook_id: hookId, event, session_id: owner?.session.id, duration_ms: performance.now() - hookStart, exit_code: run.code });
        let output = {};
        if (run.stdout.trim().startsWith("{")) {
          try {
            output = JSON.parse(run.stdout);
          } catch {
            this.ctx.logger.warn(`LinkTool ${event}: non-JSON hook stdout`);
          }
        }
        const specific = output.hookSpecificOutput;
        if (specific?.updatedInput !== void 0) throw new Error(`LinkTool ${event}: updatedInput requires a dedicated input adapter`);
        if (run.code === 2 || output.decision === "block" || specific?.permissionDecision === "deny" || output.continue === false) {
          merged.deny = specific?.permissionDecisionReason ?? output.reason ?? output.stopReason ?? run.stderr.trim() ?? "Hook denied operation";
          if (event === "PreToolUse") return merged;
        } else if (run.code !== 0) {
          this.ctx.logger.warn(`LinkTool ${event}: hook exited ${run.code}: ${run.stderr}`);
          merged.contexts.push(`LinkTool ${event} hook execution failed (exit ${run.code}): ${run.stderr}`);
        }
        const context = specific?.additionalContext ?? output.additionalContext;
        if (context) merged.contexts.push(context);
      }
    }
    return merged;
  }
  install() {
    this.ctx.on("tools/pre-execute", async (exec, next) => {
      if (!this.identity(exec.agent)) return next();
      const result = await this.run("PreToolUse", exec, void 0, void 0, exec.signal);
      if (result.deny) return { kind: "deny", reason: result.deny };
      if (result.contexts.length) exec.agent?.inject(this.message(result.contexts.join("\n")));
      return next();
    });
    this.ctx.on("tools/post-execute", async (exec, result, next) => {
      if (!this.identity(exec.agent)) return next();
      const hook = await this.run("PostToolUse", exec, result, void 0, exec.signal);
      const contexts = hook.contexts.map((text) => this.message(text));
      if (hook.deny) return { kind: "block", feedback: [{ type: "text", text: hook.deny }], additionalContexts: contexts };
      const downstream = await next();
      return { ...downstream, additionalContexts: [...contexts, ...downstream.additionalContexts ?? []] };
    });
    const pending = /* @__PURE__ */ new Set();
    this.ctx.on("session/event", (session, event) => {
      if (event.type === "compaction/end" && !event.data.error) pending.add(session.id);
    });
    this.ctx.on("agent/pre-step", async ({ agent, signal }, next) => {
      const decision = await next();
      if (!pending.has(agent.session.id) || !this.identity(agent) || decision.kind !== "enter") return decision;
      const hook = await this.run("PostCompact", void 0, void 0, agent, signal);
      pending.delete(agent.session.id);
      return { ...decision, messages: [...decision.messages, ...hook.contexts.map((text) => this.message(text))] };
    });
    this.ctx.on("agent/created", async ({ agent, source, signal }) => {
      if (source === "compact" && this.identity(agent)) {
        pending.delete(agent.session.id);
        const hook = await this.run("PostCompact", void 0, void 0, agent, signal);
        for (const text of hook.contexts) agent.inject(this.message(text));
      }
      return void 0;
    });
  }
  message(text) {
    return createUserMessage({ content: [{ type: "text", text }], source: { kind: "linktool-hook", form: "instructions" } });
  }
};
export {
  HookBridge,
  legacyTool,
  runCommand
};
//# sourceMappingURL=hooks.js.map
