import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

// src/index.ts
import { AsyncLocalStorage } from "node:async_hooks";
import { existsSync as existsSync6, readFileSync as readFileSync4, writeFileSync as writeFileSync2, mkdirSync as mkdirSync2 } from "node:fs";
import { join as join7, dirname as dirname5 } from "node:path";
import { createHash as createHash2 } from "node:crypto";
import { renderSkillContent } from "@deepseek-ai/dsh-skill";

// src/mcp.ts
import { existsSync as existsSync3 } from "node:fs";
import { dirname as dirname3, join as join3 } from "node:path";

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
  return value.replace(/\$\{([A-Z_]+)\}\$?/g, (token, name2) => {
    const replacement = replacements[name2] ?? (strict ? process.env[name2] : void 0);
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
import { createHash } from "node:crypto";
import { BUNDLED_SKILL_RANK } from "@deepseek-ai/dsh-skill";
var packageRoot2 = resolve2(dirname2(fileURLToPath2(import.meta.url)), "..");
var resourceRoot2 = join2(packageRoot2, "resources", "plugin");
var catalog = JSON.parse(readFileSync(join2(packageRoot2, "config", "catalog.json"), "utf8"));
var readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
function loadRuntime() {
  return readJson(join2(packageRoot2, "config", "runtime.json"));
}
function body(doc) {
  const text = readFileSync(join2(resourceRoot2, doc.path), "utf8").replace(/^\uFEFF/, "");
  const match = /^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/.exec(text);
  const content = match ? text.slice(match[0].length) : text;
  if (createHash("sha256").update(content).digest("hex") !== doc.bodySha256) throw new Error(`Prompt integrity mismatch: ${doc.path}. Rebuild the catalog deliberately after source changes.`);
  return content;
}
function agentName(name2) {
  return name2.replace(/^@/, "").replace(/^linktool-plugin:/, "").replace(/^linktool:/, "");
}
function getAgent(name2) {
  const doc = catalog.agents.find((a) => a.name === agentName(name2));
  if (!doc) throw new Error(`Unknown LinkTool agent: ${name2}`);
  return doc;
}
function getSkill(name2) {
  const doc = catalog.skills.find((s) => s.name === name2.replace(/^linktool-plugin:/, ""));
  if (!doc) throw new Error(`Unknown LinkTool skill: ${name2}`);
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
    if (inside(local, resourceRoot2) && existsSync2(local)) return local;
  }
  return resolve2(workspace(agent), path);
}
function benchmarkPolicy(agent) {
  return agent ? globalThis[Symbol.for("linktool.benchmark.policies")]?.get(agent.session.id) ?? {} : {};
}

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
    args = ["run", "python", join3(cwd, "main.py")];
  }
  const script = args.find((a) => a.endsWith(".py") && existsSync3(a));
  if (script && existsSync3(join3(dirname3(script), "pyproject.toml")) && command === "uv" && args[0] === "run") {
    cwd = dirname3(script);
    args = ["run", "--project", cwd, ...args.slice(1)];
  } else if (command === "uv" && args[0] === "run") args = ["run", "--no-project", ...args.slice(1)];
  return { ...common, transport: "stdio", command, args, cwd, env: { ...childEnvironment(projectDir), ...env, UV_PROJECT_ENVIRONMENT: join3(packageRoot2, ".runtime", "mcp", server) } };
}
function resolvedServers(projectDir = process.cwd()) {
  const original = readJson(join3(packageRoot2, "config/mcp.json"));
  return Object.fromEntries(Object.entries(original).map(([name2, config]) => [name2, resolveMcp(name2, config, projectDir)]));
}

// src/index.ts
import * as McpClient from "@deepseek-ai/dsh-mcp-client";

// src/hooks.ts
import { spawn } from "node:child_process";
import { join as join5 } from "node:path";
import { createUserMessage } from "@deepseek-ai/dsh-llm";

// src/tools.ts
import { existsSync as existsSync4, readFileSync as readFileSync2, mkdirSync, writeFileSync, renameSync } from "node:fs";
import { dirname as dirname4, join as join4 } from "node:path";
import { randomUUID } from "node:crypto";
import { defineTool } from "@deepseek-ai/dsh-tools";
var builtins = { Read: "read", Write: "write", Edit: "edit", Update: "edit", Glob: "glob", Grep: "grep", Bash: "bash", WebFetch: "web_fetch", WebSearch: "web_search", Web_Search: "web_search", ListMcpResourcesTool: "list_mcp_resources", ReadMcpResourceTool: "read_mcp_resource", Wrtie: "write", AskUserQuestion: "ask_user_question" };
function mcpTarget(name2, config) {
  const match = /^mcp__(?:plugin_linktool-plugin_)?(.+)__(.+)$/.exec(name2);
  if (!match) return builtins[config.toolAliases[name2] ?? name2] ?? name2;
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
function textTool(name2, description, parameters, execute) {
  return defineTool({ name: name2, description, parameters, output: { schema: { type: "json" }, render: (_args, value) => [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }] }, execute });
}
function aliasDefinition(alias, target, definition2, skill) {
  const parameters = structuredClone(definition2.parameters);
  if (target === "web_search") {
    parameters.properties = { ...parameters.properties, query: { type: "string", description: "Claude Code-compatible single search query" } };
    parameters.required = [];
  }
  if (target === "web_fetch") parameters.properties = { ...parameters.properties, prompt: { type: "string", description: "Original WebFetch instruction for processing the retrieved page" } };
  if (target === "bash" || target === "pwsh") parameters.required = (parameters.required ?? []).filter((n) => n !== "description");
  return {
    name: alias,
    description: definition2.description,
    parameters,
    output: { schema: {}, render: (_a, value) => value.content },
    ...definition2.timeoutMs ? { timeoutMs: definition2.timeoutMs } : {},
    async execute(raw, exec) {
      const args = mapArguments(target, raw, exec.agent, typeof skill === "function" ? skill() : skill);
      if (target === "pwsh" && alias === "Bash" && typeof args.command === "string") {
        const candidates = [process.env.LINKTOOL_BASH, join4(process.env.ProgramFiles ?? "C:/Program Files", "Git", "bin", "bash.exe"), "C:/Program Files/Git/usr/bin/bash.exe"];
        const bash = candidates.find((path) => !!path && existsSync4(path));
        if (!bash) throw new Error("ENV_ERROR: original Bash skills require Git Bash; install Git for Windows or set LINKTOOL_BASH");
        const quote = (value2) => "'" + value2.replaceAll("'", "''") + "'";
        const env = childEnvironment(workspace(exec.agent));
        args.command = `$env:PATH=${quote(env.PATH)}; $env:PYTHONIOENCODING='utf-8'; & ${quote(bash)} -c ${quote(args.command)}; exit $LASTEXITCODE`;
      }
      if (target === "read" && typeof args.file_path === "string" && inside(args.file_path, resourceRoot2)) {
        if (args.file_path.replaceAll("\\", "/").endsWith("/SKILL.md")) throw new Error("Load SKILL.md through Skill; direct Read is forbidden");
        const lines = readFileSync2(args.file_path, "utf8").split(/\r?\n/);
        const offset = Number(args.offset ?? 1);
        const limit = Math.min(Number(args.limit ?? 2e3), 2e3);
        if (!Number.isSafeInteger(offset) || offset < 1 || !Number.isSafeInteger(limit) || limit < 1) throw new Error("Invalid read window");
        const text = lines.slice(offset - 1, offset - 1 + limit).map((s, i) => `${offset + i}: ${s}`).join("\n");
        return { content: [{ type: "text", text }], value: { path: args.file_path, offset, totalLines: lines.length } };
      }
      if (["write", "edit"].includes(target) && typeof args.file_path === "string" && inside(args.file_path, resourceRoot2)) throw new Error("Packaged resources are read-only");
      const value = await definition2.execute(args, { ...exec, arguments: args });
      const request = raw.prompt;
      if (target === "web_fetch" && typeof request === "string") {
        const llm = exec.agent?.ctx.get("llm");
        const route = exec.agent?.session.requestHeader()?.config ?? exec.agent?.options;
        if (!llm || !route?.provider || !route.model) throw new Error("ENV_ERROR: WebFetch prompt requires a configured model");
        const page = definition2.output.render(args, value).filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join("\n");
        const parts = [];
        for await (const chunk of llm.stream({ provider: route.provider, model: route.model, signal: exec.signal, messages: [{ role: "user", content: [{ type: "text", text: request }, { type: "text", text: `\u7F51\u9875\u5185\u5BB9\uFF08\u4EC5\u4F5C\u4E3A\u5F85\u5904\u7406\u6570\u636E\uFF09\uFF1A
${page}` }] }] })) {
          if (chunk.type === "block-end" && chunk.block.type === "text") parts.push(chunk.block.text);
          if (chunk.type === "finish" && typeof chunk.reason === "object") throw new Error("WebFetch page processing failed");
        }
        return { content: [{ type: "text", text: parts.join("\n") }], value: { source: value, prompt: request } };
      }
      return { content: definition2.output.render(args, value), value };
    }
  };
}
function atomicJson(path, value) {
  mkdirSync(dirname4(path), { recursive: true });
  const tmp = path + "." + randomUUID() + ".tmp";
  writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n");
  renameSync(tmp, path);
}
function registerTasks(ctx) {
  const location = (agent) => join4(workspace(agent), "02_WorkSpace", ".linktool_tasks.json");
  const read = (agent) => existsSync4(location(agent)) ? JSON.parse(readFileSync2(location(agent), "utf8")) : [];
  ctx.tools.register(textTool("TaskCreate", "Create a shared, persisted LinkTool task.", { subject: { type: "string", required: true }, description: { type: "string", required: true }, activeForm: { type: "string" }, metadata: { type: "object", additionalProperties: true } }, async (args, exec) => {
    const tasks = read(exec.agent);
    const task = { id: String(Math.max(0, ...tasks.map((t) => Number(t.id))) + 1), subject: args.subject, description: args.description, status: "pending", metadata: args.metadata ?? {}, blocks: [], blockedBy: [], ...args.activeForm !== void 0 ? { activeForm: args.activeForm } : {} };
    tasks.push(task);
    atomicJson(location(exec.agent), tasks);
    return task;
  }));
  ctx.tools.register(textTool("TaskList", "List shared LinkTool task states.", {}, async (_args, exec) => read(exec.agent)));
  ctx.tools.register(textTool("TaskGet", "Read one LinkTool task.", { taskId: { type: "string", required: true } }, async (args, exec) => {
    const task = read(exec.agent).find((t) => t.id === args.taskId);
    if (!task) throw new Error("Task not found");
    return task;
  }));
  ctx.tools.register(textTool("TaskUpdate", "Update a task; completed requires evidence. Dependencies must be completed first.", { taskId: { type: "string", required: true }, status: { type: "string", enum: ["pending", "in_progress", "completed", "deleted"] }, subject: { type: "string" }, description: { type: "string" }, activeForm: { type: "string" }, owner: { type: "string" }, metadata: { type: "object", additionalProperties: true }, evidence: { type: "json" }, addBlocks: { type: "array", items: { type: "string" } }, addBlockedBy: { type: "array", items: { type: "string" } } }, async (args, exec) => {
    const tasks = read(exec.agent);
    const task = tasks.find((t) => t.id === args.taskId);
    if (!task) throw new Error("Task not found");
    if (args.status === "completed") {
      if (!args.evidence && !args.metadata?.evidence && !task.metadata.evidence) throw new Error("Completion requires evidence");
      if (task.blockedBy.some((id) => tasks.find((t) => t.id === id)?.status !== "completed")) throw new Error("Task has incomplete dependencies");
    }
    for (const key of ["status", "subject", "description", "owner", "evidence", "activeForm"]) if (args[key] !== void 0) task[key] = args[key];
    Object.assign(task.metadata, args.metadata ?? {});
    task.blocks = [.../* @__PURE__ */ new Set([...task.blocks, ...args.addBlocks ?? []])];
    task.blockedBy = [.../* @__PURE__ */ new Set([...task.blockedBy, ...args.addBlockedBy ?? []])];
    for (const other of tasks) {
      if (task.blocks.includes(other.id) && !other.blockedBy.includes(task.id)) other.blockedBy.push(task.id);
      if (task.blockedBy.includes(other.id) && !other.blocks.includes(task.id)) other.blocks.push(task.id);
    }
    atomicJson(location(exec.agent), tasks.filter((t) => t.status !== "deleted"));
    return task;
  }));
  ctx.tools.register(textTool("TaskStop", "Stop a dsh background job by its task or job id.", { task_id: { type: "string" }, shell_id: { type: "string" } }, async (args, exec) => {
    const tool = ctx.tools.get("job_kill", exec.agent);
    if (!tool) throw new Error("ENV_ERROR: job_kill is unavailable");
    const mapped = { job_id: args.task_id ?? args.shell_id };
    const value = await tool.execute(mapped, { ...exec, arguments: mapped });
    return tool.output.render(mapped, value);
  }));
}
function registerResources(ctx, config) {
  ctx.tools.register(textTool("ListMcpResourcesTool", "List resources from one server or every configured server. A server with no resource capability has an empty resource list.", { server: { type: "string" }, cursor: { type: "string" } }, async (args, exec) => {
    const native = ctx.tools.get("list_mcp_resources", exec.agent);
    if (!native) return { resources: [] };
    const resources = [];
    const responses = [];
    for (const server of args.server ? [config.serverAliases[args.server] ?? args.server] : config.enabledServers) {
      const mapped = { server, ...args.cursor ? { cursor: args.cursor } : {} };
      try {
        const value = await native.execute(mapped, { ...exec, arguments: mapped });
        if (args.server) return value;
        resources.push(...value.resources ?? []);
        responses.push({ server, result: value });
      } catch (error) {
        if (args.server) throw error;
      }
    }
    return { resources, responses };
  }));
  ctx.tools.register(textTool("ReadMcpResourceTool", "Read one configured MCP resource using its exact server and URI.", { server: { type: "string", required: true }, uri: { type: "string", required: true } }, async (args, exec) => {
    const native = ctx.tools.get("read_mcp_resource", exec.agent);
    if (!native) throw new Error("This server does not advertise MCP resources");
    const mapped = { ...args, server: config.serverAliases[args.server] ?? args.server };
    return native.execute(mapped, { ...exec, arguments: mapped });
  }));
}
function toolAllowed(name2, agent, config) {
  if (name2 === "structured_output" || name2 === "run_code") return true;
  const normalized = config.toolAliases[name2] ?? name2;
  if (agent.disallowedTools.some((n) => n === normalized || mcpTarget(n, config) === mcpTarget(normalized, config))) return false;
  if (agent.tools.some((n) => n === normalized || mcpTarget(n, config) === mcpTarget(normalized, config))) return true;
  const match = /^mcp__(?:plugin_linktool-plugin_)?(.+)__/.exec(name2);
  if (match && agent.mcpServers.some((s) => (config.serverAliases[s] ?? s) === match[1])) return true;
  return agent.name === "question-classify" && name2 === "Agent";
}

// src/hooks.ts
var names = { read: "Read", read_image: "Read", write: "Write", edit: "Edit", glob: "Glob", grep: "Grep", bash: "Bash", pwsh: "Bash", str_replace_editor: "Edit" };
function legacyTool(name2) {
  if (name2 === "Wrtie") return "Write";
  if (name2 === "Update") return "Edit";
  if (names[name2]) return names[name2];
  if (/^mcp__/.test(name2) && !name2.startsWith("mcp__plugin_linktool-plugin_")) return name2.replace(/^mcp__([^_]+(?:-[^_]+)*)__/, "mcp__plugin_linktool-plugin_$1__");
  return name2;
}
async function runCommand(command, payload, cwd, signal, timeout, agentName2 = "") {
  const expanded = expandPaths(command, cwd);
  const isWindows = process.platform === "win32";
  return new Promise((resolve4, reject) => {
    const child = spawn(isWindows ? process.env.ComSpec ?? "cmd.exe" : "/bin/sh", isWindows ? ["/d", "/s", "/c", expanded] : ["-c", expanded], { cwd, windowsHide: true, windowsVerbatimArguments: isWindows, env: childEnvironment(cwd, agentName2), stdio: ["pipe", "pipe", "pipe"] });
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
      else resolve4({ code: code ?? 1, stdout, stderr });
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
    this.bindings = readJson(join5(packageRoot2, "config/hooks.json")).hooks;
  }
  bindings;
  async run(event, exec, result, agent, signal = new AbortController().signal) {
    const owner = agent ?? exec?.agent;
    const benchmarkRoutes = globalThis[Symbol.for("linktool.benchmark.architectures")];
    if (owner && benchmarkRoutes?.get(owner.session.id) === "code") return { contexts: [] };
    const name2 = exec ? legacyTool(exec.name) : "auto";
    const payload = { session_id: owner?.session.id ?? "", transcript_path: "", cwd: workspace(owner), hook_event_name: event, agent_name: this.identity(owner), agent: this.identity(owner), tool_name: name2, tool_use_id: exec?.callId ?? "", tool_input: exec ? mapArguments(mcpTarget(exec.name, this.config), exec.arguments, owner, this.currentSkill(owner)) : {}, ...result ? { tool_response: { content: result.content, isError: result.isError, ..."value" in result ? { structuredContent: result.value } : {}, ..."error" in result ? { error: result.error } : {} } } : {} };
    if (result) payload.tool_input.tool_response = payload.tool_response;
    const merged = { contexts: [] };
    if (!this.config.hooksEnabled) return merged;
    for (const [bindingIndex, binding] of (this.bindings[event] ?? []).entries()) {
      if (binding.matcher && binding.matcher !== "*" && !new RegExp(`^(?:${binding.matcher})$`).test(name2)) continue;
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

// src/workflow.ts
import { readFileSync as readFileSync3, existsSync as existsSync5 } from "node:fs";
import { join as join6, resolve as resolve3 } from "node:path";
import { randomUUID as randomUUID2 } from "node:crypto";
import ts from "typescript";
function splitWorkflow(source) {
  const ast = ts.createSourceFile("workflow.js", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const declaration = ast.statements.find((s) => ts.isVariableStatement(s) && s.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword) && s.declarationList.declarations.some((d) => ts.isIdentifier(d.name) && d.name.text === "meta"));
  if (!declaration || !ts.isVariableStatement(declaration) || declaration.declarationList.declarations.length !== 1) throw new Error("Workflow requires a single literal export const meta = {...}");
  if ((declaration.declarationList.flags & ts.NodeFlags.Const) === 0) throw new Error("Workflow meta must be const");
  const initializer = declaration.declarationList.declarations[0]?.initializer;
  function literal(node) {
    if (!node) throw new Error("Missing Workflow meta initializer");
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (ts.isNumericLiteral(node)) return Number(node.text);
    if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
    if (node.kind === ts.SyntaxKind.NullKeyword) return null;
    if (ts.isArrayLiteralExpression(node)) return node.elements.map(literal);
    if (ts.isObjectLiteralExpression(node)) return Object.fromEntries(node.properties.map((p) => {
      if (!ts.isPropertyAssignment(p) || !p.name || !(ts.isIdentifier(p.name) || ts.isStringLiteral(p.name))) throw new Error("Workflow meta accepts only literal property assignments");
      if (["__proto__", "constructor", "prototype"].includes(p.name.text)) throw new Error("Unsafe Workflow meta property");
      return [p.name.text, literal(p.initializer)];
    }));
    throw new Error("Workflow meta must be literal JSON data");
  }
  const meta = literal(initializer);
  if (!meta || typeof meta.name !== "string" || typeof meta.description !== "string") throw new Error("Workflow meta requires name and description");
  const script = source.slice(0, declaration.getFullStart()) + source.slice(declaration.end);
  if (ast.statements.some((s) => ts.isImportDeclaration(s) || ts.isExportDeclaration(s))) throw new Error("Workflow imports and exports other than meta are forbidden");
  return { meta, script };
}
function checkpointPath(agent, id) {
  if (!/^wf_[a-f0-9-]{36}$/.test(id)) throw new Error("Invalid Workflow runId");
  return join6(workspace(agent), "02_WorkSpace", ".linktool_workflow", id + ".json");
}
function workflowShim(script, checkpoint) {
  const snapshot = JSON.stringify({ id: checkpoint.id, cache: checkpoint.cache, path: checkpointPath({ session: { header: { cwd: checkpoint.cwd } } }, checkpoint.id) });
  return `return await (async (__nativeAgent) => {
  const __checkpoint = ${snapshot};
  const __cache = __checkpoint.cache;
  const agent = async (prompt, options = {}) => {
    const allowed = ['agentType', 'label', 'phase', 'schema', 'provider', 'model'];
    for (const key of Object.keys(options)) if (!allowed.includes(key)) throw new Error('Unsupported agent option: ' + key);
    const opts = { ...options };
    if (!opts.agentType) throw new Error('LinkTool Workflow agent() requires agentType');
    const key = JSON.stringify([prompt, opts]);
    if (Object.prototype.hasOwnProperty.call(__cache, key)) { log('Cache hit: ' + (opts.label || opts.agentType)); return __cache[key]; }
    const envelope = { linktoolWorkflow: 1, prompt, options: opts, runId: __checkpoint.id, cacheKey: key, checkpointPath: __checkpoint.path };
    const result = await __nativeAgent(JSON.stringify(envelope), { label: opts.label || opts.agentType, ...(opts.phase ? { phase: opts.phase } : {}) });
    if (result === null) return null;
    const value = JSON.parse(result);
    if (value && ['success', 'skipped', 'completed'].includes(value.status)) __cache[key] = value;
    return value;
  };
  ${script}
})(agent);`;
}
function unwrapResult(run) {
  return { ...run, async dispose() {
    await run.dispose();
  }, result: run.result.then((result) => {
    let value = result.structured;
    if (value === void 0) {
      const text = result.output.filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join("\n");
      try {
        value = JSON.parse(text.replace(/^```(?:json)?\s*/, "").replace(/\s*```$/, ""));
      } catch {
        value = text;
      }
    }
    return { ...result, output: [{ type: "text", text: JSON.stringify(value) }] };
  }) };
}
function registerWorkflow(ctx, dispatch, authorize = async () => {
}) {
  ctx.subagents.registerProvider({ name: "linktool-workflow", capabilities: { agentOptions: true, outputSchema: true, depthLimit: true, toolFilter: true, persona: true }, inheritsParentContext: false, async start(request) {
    const text = request.prompt.filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join("");
    const envelope = JSON.parse(text);
    if (envelope.linktoolWorkflow !== 1 || typeof envelope.prompt !== "string") throw new Error("Invalid LinkTool Workflow envelope");
    const expectedPath = checkpointPath(request.parent, envelope.runId);
    if (resolve3(envelope.checkpointPath) !== expectedPath) throw new Error("Invalid checkpoint path");
    const agent = getAgent(String(envelope.options.agentType));
    if (agent.name === "question-classify") throw new Error("question-classify is not in the original Workflow agent whitelist");
    const run = unwrapResult(await dispatch(agent.name, { ...request, prompt: [{ type: "text", text: envelope.prompt }], ...envelope.options.schema ? { outputSchema: envelope.options.schema } : {}, ...envelope.options.provider || envelope.options.model ? { agentOptions: { ...request.agentOptions, ...envelope.options.provider ? { provider: String(envelope.options.provider) } : {}, ...envelope.options.model ? { model: String(envelope.options.model) } : {} } } : {} }));
    return { ...run, async dispose() {
      await run.dispose();
    }, result: run.result.then((result) => {
      if (result.stopReason === "completed") {
        const value = JSON.parse(result.output.filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join(""));
        if (value && ["success", "skipped", "completed"].includes(value.status)) {
          const state = JSON.parse(readFileSync3(expectedPath, "utf8"));
          state.cache[envelope.cacheKey] = value;
          atomicJson(expectedPath, state);
        }
      }
      return result;
    }) };
  } });
  ctx.tools.register(textTool("Workflow", "Run the unchanged Claude Code GIS Workflow DSL on the native sandboxed dsh engine. Supports scriptPath, agentType, phases, parallel, pipeline and one resume.", { scriptPath: { type: "string", required: true }, args: { type: "object", additionalProperties: true }, resumeFromRunId: { type: "string" } }, async (args, exec) => {
    if (!exec.agent) throw new Error("Workflow requires an agent");
    const cwd = workspace(exec.agent);
    const scriptPath = resolve3(cwd, args.scriptPath);
    if (!inside(scriptPath, cwd)) throw new Error("Workflow scriptPath must be inside the workspace");
    await authorize(exec);
    const source = readFileSync3(scriptPath, "utf8");
    const parsed = splitWorkflow(source);
    if (benchmarkPolicy(exec.agent).workflows?.includes(parsed.meta.name) || benchmarkPolicy(exec.agent).workflows?.includes(args.scriptPath)) throw new Error("Benchmark ablation: named Workflow removed");
    const id = args.resumeFromRunId ?? "wf_" + randomUUID2();
    const path = checkpointPath(exec.agent, id);
    let checkpoint;
    if (args.resumeFromRunId) {
      if (!existsSync5(path)) throw new Error("Unknown Workflow runId; cannot silently restart");
      checkpoint = JSON.parse(readFileSync3(path, "utf8"));
      if (checkpoint.cwd !== cwd || checkpoint.scriptPath !== scriptPath) throw new Error("Resume must use the original workspace and scriptPath");
      if (checkpoint.attempts >= 2 + (benchmarkPolicy(exec.agent).resume_generation ?? 0)) throw new Error("WORKFLOW_RETRY_EXHAUSTED: controller continuation allowance exhausted");
      checkpoint.attempts += 1;
    } else checkpoint = { version: 1, id, scriptPath, cwd, attempts: 1, cache: {}, status: "running" };
    checkpoint.status = "running";
    atomicJson(path, checkpoint);
    const engine = exec.agent.ctx.get("workflowEngine") ?? ctx.get("workflowEngine");
    if (!engine) throw new Error("ENV_ERROR: native workflowEngine is unavailable");
    let run;
    try {
      run = engine.start({ script: workflowShim(parsed.script, checkpoint), meta: parsed.meta, args: args.args ?? {}, subagentProvider: "linktool-workflow", parent: exec.agent, signal: exec.signal });
      const result = await run.result;
      const current = JSON.parse(readFileSync3(path, "utf8"));
      current.status = result.stopReason;
      atomicJson(path, current);
      const progressPath = join6(cwd, "02_WorkSpace", ".workflow_runs.json");
      const progress = existsSync5(progressPath) ? JSON.parse(readFileSync3(progressPath, "utf8")) : [];
      progress.push({ runId: id, engineRunId: run.id, name: parsed.meta.name, status: result.stopReason, attempts: current.attempts });
      atomicJson(progressPath, progress.slice(-10));
      if (result.stopReason !== "completed") throw new Error(JSON.stringify({ status: "failed", runId: id, error: result.error }));
      return { runId: id, engineRunId: run.id, status: "completed", result: result.value, agentsStarted: result.agentsStarted };
    } catch (error) {
      const current = JSON.parse(readFileSync3(path, "utf8"));
      current.status = "error";
      atomicJson(path, current);
      throw error;
    } finally {
      await run?.dispose();
    }
  }));
}

// src/index.ts
var name = "linktool-plugin";
var inject = ["tools", "skills", "systemPrompt", "subagents", "agents"];
function apply(ctx, overrides = {}) {
  const config = { ...loadRuntime(), ...overrides };
  const pending = new AsyncLocalStorage();
  const states = /* @__PURE__ */ new WeakMap();
  const live = /* @__PURE__ */ new Set();
  const initializedRoots = /* @__PURE__ */ new WeakSet();
  const rootSkills = /* @__PURE__ */ new WeakMap();
  const identity = (agent) => agent ? states.get(agent)?.agent.name ?? "main" : "";
  const hooks = new HookBridge(ctx, config, identity, (agent) => agent ? states.get(agent)?.activeSkill ?? rootSkills.get(agent) : void 0);
  registerTasks(ctx);
  registerResources(ctx, config);
  const refs = /* @__PURE__ */ new Set();
  for (const doc of [...catalog.agents, ...catalog.skills]) for (const match of body(doc).matchAll(/mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_]+/g)) refs.add(match[0]);
  for (const agent of catalog.agents) for (const tool of agent.tools) if (tool.startsWith("mcp__")) refs.add(tool);
  for (const skill of catalog.skills) for (const tool of skill.allowedTools) if (tool.startsWith("mcp__")) refs.add(tool);
  const skillGrants = (name2, state) => (state.activeSkill?.allowedTools ?? []).some((allowed2) => {
    if (allowed2 === name2 || mcpTarget(allowed2, config) === mcpTarget(name2, config)) return true;
    return name2.startsWith(`mcp__${config.serverAliases[allowed2] ?? allowed2}__`) || name2.startsWith(`mcp__plugin_linktool-plugin_${config.serverAliases[allowed2] ?? allowed2}__`) || allowed2 === "officecli" && ["Bash", "Read"].includes(name2);
  });
  const allowed = (name2, state) => {
    const target = mcpTarget(name2, config);
    if (state.agent.disallowedTools.some((n) => n === name2 || mcpTarget(n, config) === target)) return false;
    if (target.endsWith("__execute_gis_tool") && ["task-plan", "report", "data-retrieval"].includes(state.agent.name)) return false;
    return toolAllowed(name2, state.agent, config) || skillGrants(name2, state) || name2 === "skill" && state.agent.tools.includes("Skill") || name2 === "linktool_memory" && state.agent.metadata.memory === "project";
  };
  function refresh(agent) {
    const state = states.get(agent);
    if (!state || state.preparingAliases) return;
    state.preparingAliases = true;
    try {
      state.releaseRestriction?.();
      state.releaseRestriction = void 0;
      for (const dispose of state.registrations.values()) dispose();
      state.registrations.clear();
      const scoped = agent.ctx;
      const wanted = new Set([...state.agent.tools, ...Object.keys(builtins).filter((n) => allowed(n, state)), ...refs].filter((n) => allowed(n, state)));
      for (const schema of ctx.tools.schemas(agent)) if (schema.name.startsWith("mcp__") && allowed(schema.name, state)) wanted.add(schema.name);
      for (const alias of wanted) {
        if (["ListMcpResourcesTool", "ReadMcpResourceTool"].includes(alias)) continue;
        if (alias.startsWith("mcp__plugin_linktool-plugin_")) continue;
        if (state.registrations.has(alias) || ["Skill", "skill", "Agent", "Workflow", "ToolSearch", "linktool_memory"].includes(alias) || alias.startsWith("Task")) continue;
        let target = mcpTarget(alias, config);
        if (target === "bash" && !ctx.tools.get("bash", agent)) target = "pwsh";
        const tool = ctx.tools.get(target, agent);
        if (!tool || alias === target) continue;
        state.registrations.set(alias, scoped.get("tools").register(aliasDefinition(alias, target, tool, () => state.activeSkill)));
      }
      const globalAllowed = ctx.tools.schemas().map((t) => t.name).filter((n) => allowed(n, state));
      state.releaseRestriction = scoped.get("tools").restrict({ allow: globalAllowed });
    } finally {
      state.preparingAliases = false;
    }
  }
  async function dispatch(name2, request, skill, carryContext = false) {
    const record = getAgent(name2);
    if (benchmarkPolicy(request.parent).agents?.includes(record.name)) throw new Error(`Benchmark ablation: agent ${record.name} removed`);
    const options = { ...request.agentOptions };
    const alias = record.metadata.model ? config.modelAliases[String(record.metadata.model)] : void 0;
    if (alias?.mode === "route") Object.assign(options, { provider: alias.provider, model: alias.model, ...alias.reasoningEffort ? { reasoningEffort: alias.reasoningEffort } : {} });
    const provider = request.parent.ctx.get("subagents").getProvider(carryContext ? "fork" : "spawn");
    if (!provider) throw new Error(`ENV_ERROR: native ${carryContext ? "fork" : "spawn"} provider unavailable`);
    const state = { agent: record, parent: request.parent, activeSkill: skill, skillArgs: skill ? request.prompt.filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join("\n") : void 0, steps: 0, registrations: /* @__PURE__ */ new Map() };
    return pending.run(state, () => provider.start({ ...request, agentOptions: options, maxDepth: config.maxAgentDepth }));
  }
  function start(name2, request) {
    return ctx.subagents.start("linktool:" + agentName(name2), request);
  }
  for (const record of catalog.agents) ctx.subagents.registerProvider({ name: "linktool:" + record.name, capabilities: { agentOptions: true, outputSchema: true, depthLimit: true, toolFilter: true, persona: true }, inheritsParentContext: false, start: (request) => dispatch(record.name, request) });
  registerWorkflow(ctx, dispatch, async (exec) => {
    if (!exec.agent) throw new Error("Workflow requires a caller");
    if (benchmarkPolicy(exec.agent).workflow) throw new Error("Benchmark ablation: Workflow removed");
    const state = states.get(exec.agent);
    if (state?.agent.metadata.permissionMode !== "plan") return;
    const planPath = join7(workspace(exec.agent), "02_WorkSpace", "task_plan.md");
    if (!existsSync6(planPath)) throw new Error("PLAN_REQUIRED: Write task_plan.md before executing the Workflow");
    const plan = readFileSync4(planPath, "utf8");
    const digest = createHash2("sha256").update(plan).digest("hex");
    const approvalPath = join7(workspace(exec.agent), ".dsh", "linktool-plan-approval.json");
    if (existsSync6(approvalPath) && readJson(approvalPath).digest === digest) {
      state.approved = true;
      return;
    }
    if (process.env.LINKTOOL_BENCH_AUTO_APPROVE === "1" && process.env.LINKTOOL_BENCH_RUN_ID) {
      atomicJson(approvalPath, { digest, approvedBy: "benchmark-controller", runId: process.env.LINKTOOL_BENCH_RUN_ID });
      state.approved = true;
      return;
    }
    const benchmarkAuthorizations = globalThis[Symbol.for("linktool.benchmark.authorization")];
    const benchmarkRun = benchmarkAuthorizations?.get(exec.agent.session.id);
    if (benchmarkRun) {
      atomicJson(approvalPath, { digest, approvedBy: "native-benchmark-controller", runId: benchmarkRun });
      state.approved = true;
      return;
    }
    let root = exec.agent;
    while (states.get(root)?.parent) root = states.get(root).parent;
    const questions = root.ctx.get("userQuestions");
    if (!questions) throw new Error("APPROVAL_REQUIRED: user question service is unavailable; plan remains unapproved");
    const result = await questions.ask({ agent: root, signal: exec.signal, questions: [{ id: "linktool-plan", header: "GIS \u4EFB\u52A1\u8BA1\u5212", question: "\u6279\u51C6\u4EE5\u4E0B GIS \u4EFB\u52A1\u8BA1\u5212\u5E76\u6267\u884C\u5B8C\u6574 Workflow\uFF1F", detail: plan, options: [{ label: "\u6279\u51C6\u6267\u884C", description: "\u6267\u884C\u8BA1\u5212\u4E2D\u7684 GIS \u64CD\u4F5C\u5E76\u751F\u6210\u4EA4\u4ED8\u7269\u3002" }, { label: "\u6682\u4E0D\u6267\u884C", description: "\u4FDD\u6301\u89C4\u5212\u72B6\u6001\u5E76\u8FD4\u56DE\u4FEE\u6539\u610F\u89C1\u3002" }] }] });
    if (!result.answers.find((a) => a.id === "linktool-plan")?.selected.includes("\u6279\u51C6\u6267\u884C")) throw new Error("PLAN_NOT_APPROVED: execution was not approved");
    atomicJson(approvalPath, { digest, approvedBy: root.session.id });
    state.approved = true;
  });
  const agentTool = textTool("Agent", "Delegate to a registered LinkTool agent. Choose subagent_type from the original linktool-plugin:<agent> names. Named agents start with no parent conversation; prompt must contain all required inputs.", { subagent_type: { type: "string", required: true, enum: catalog.agents.map((a) => "linktool-plugin:" + a.name) }, prompt: { type: "string", required: true }, description: { type: "string" } }, async (args, exec) => {
    if (!exec.agent) throw new Error("Agent requires a live caller");
    const state = states.get(exec.agent);
    if (state?.agent.disallowedTools.includes("Agent") || state?.agent.name === "task-plan") throw new Error("This agent cannot directly delegate; use its Workflow contract");
    const run = await start(args.subagent_type, { parent: exec.agent, prompt: [{ type: "text", text: args.prompt }], label: args.description, signal: exec.signal });
    try {
      const result = await run.result;
      if (result.stopReason !== "completed") throw new Error(`LinkTool agent stopped: ${result.stopReason}${result.diagnostic ? ": " + result.diagnostic : ""}`);
      return result.structured ?? result.output;
    } finally {
      await run.dispose();
    }
  });
  ctx.tools.register(agentTool);
  ctx.tools.register({ ...agentTool, name: "linktool_agent" });
  async function invokeSkill(name2, args, agent, signal) {
    const skill = getSkill(name2);
    const state = states.get(agent);
    if (benchmarkPolicy(agent).skills?.includes(skill.name)) throw new Error(`Benchmark ablation: skill ${skill.name} removed`);
    if (!skill.invocation.modelInvocable || !skillAllowed(skill, state?.agent, config)) throw new Error(`Skill ${name2} is unavailable to ${identity(agent)}`);
    if (skill.context !== "fork") {
      if (state) {
        state.activeSkill = skill;
        state.skillArgs = args;
        atomicJson(join7(workspace(agent), ".dsh", "linktool-agents", agent.session.id + ".json"), { agent: state.agent.name, skill: skill.name, skillArgs: args });
        refresh(agent);
      } else rootSkills.set(agent, skill);
      return renderSkillContent({ ...definition(skill), content: body(skill).replaceAll("$ARGUMENTS", args) });
    }
    const record = skill.agent ? getAgent(skill.agent) : state?.agent;
    if (!record) throw new Error(`Fork skill ${name2} has no agent binding`);
    const providerName = `linktool-skill:${skill.name}`;
    const run = await ctx.subagents.start(providerName, { parent: agent, prompt: [{ type: "text", text: args || `\u6267\u884C\u6280\u80FD ${skill.name}\u3002\u8C03\u7528\u8005\u5FC5\u987B\u901A\u8FC7 args \u663E\u5F0F\u4F20\u5165\u6240\u9700\u8F93\u5165\uFF1B\u6CA1\u6709\u8F93\u5165\u65F6\u8FD4\u56DE\u9700\u8981\u8865\u5145\u7684\u4FE1\u606F\u3002` }], label: skill.name, signal });
    try {
      const result = await run.result;
      if (result.stopReason !== "completed") throw new Error(`Fork skill stopped: ${result.stopReason}`);
      return result.structured ?? result.output;
    } finally {
      await run.dispose();
    }
  }
  for (const skill of catalog.skills.filter((s) => s.context === "fork")) ctx.subagents.registerProvider({ name: "linktool-skill:" + skill.name, capabilities: { agentOptions: true, outputSchema: true, depthLimit: true, toolFilter: true, persona: true }, inheritsParentContext: false, async start(request) {
    if (benchmarkPolicy(request.parent).skills?.includes(skill.name)) throw new Error("Benchmark ablation: fork skill removed");
    const caller = states.get(request.parent)?.agent;
    if (!skillAllowed(skill, caller, config)) throw new Error("Skill agent binding denied");
    const record = skill.agent ? getAgent(skill.agent) : caller;
    if (!record) throw new Error("Fork skill has no named agent");
    return dispatch(record.name, request, skill);
  } });
  const skillTool = textTool("Skill", "Load a LinkTool skill. Inline skills use the current conversation; context:fork skills execute with their declared agent in an independent conversation. Pass the task and all required data in args.", { skill: { type: "string", required: true }, args: { type: "string" } }, async (args, exec) => {
    if (!exec.agent) throw new Error("Skill requires an agent");
    return invokeSkill(args.skill, args.args ?? "", exec.agent, exec.signal);
  });
  ctx.tools.register(skillTool);
  ctx.skills.registerProvider(() => skillProvider(void 0, config));
  ctx.on("agent/created", async ({ agent }) => {
    let state = pending.getStore();
    const parent = state?.parent ?? ctx.agents.currentInitiator();
    const policyMap = globalThis[Symbol.for("linktool.benchmark.policies")];
    if (parent && policyMap?.has(parent.session.id)) policyMap.set(agent.session.id, policyMap.get(parent.session.id));
    const roleMap = globalThis[Symbol.for("linktool.benchmark.roles")] ??= /* @__PURE__ */ new Map();
    const removal = benchmarkPolicy(agent);
    agent.ctx.get("tools").guard((exec) => {
      const target = mcpTarget(exec.name, config);
      if (removal.tools?.includes(exec.name) || removal.tools?.includes(target) || removal.mcp?.some((n) => target.startsWith(`mcp__${config.serverAliases[n] ?? n}__`))) return "Benchmark ablation: tool/MCP removed";
      if (removal.workflow && /workflow/i.test(exec.name)) return "Benchmark ablation: Workflow removed";
      return void 0;
    });
    const rolePath = join7(workspace(agent), ".dsh", "linktool-agents", agent.session.id + ".json");
    if (!state && existsSync6(rolePath)) {
      const saved = readJson(rolePath);
      state = { agent: getAgent(saved.agent), activeSkill: saved.skill ? getSkill(saved.skill) : void 0, skillArgs: saved.skillArgs, steps: 0, registrations: /* @__PURE__ */ new Map() };
    }
    roleMap.set(agent.session.id, state?.agent.name ?? "main");
    const observer = globalThis[Symbol.for("linktool.benchmark.observe")];
    observer?.(agent.session.id, "agent/role", { session_id: agent.session.id, agent_label: state?.agent.name ?? "main" });
    if (!state) {
      if (initializedRoots.has(agent)) return void 0;
      initializedRoots.add(agent);
      for (const alias of [...Object.keys(builtins), ...refs]) {
        if (["ListMcpResourcesTool", "ReadMcpResourceTool"].includes(alias)) continue;
        if (alias.startsWith("mcp__plugin_linktool-plugin_")) continue;
        let target = mcpTarget(alias, config);
        if (target === "bash" && !ctx.tools.get("bash", agent)) target = "pwsh";
        const tool = ctx.tools.get(target, agent);
        if (tool && alias !== target) agent.ctx.get("tools").register(aliasDefinition(alias, target, tool, () => rootSkills.get(agent)));
      }
      agent.ctx.get("tools").register(skillTool);
      agent.ctx.get("tools").register(textTool("skill", "LinkTool-aware skill loader: preserves context:fork execution and inline skill loading.", { name: { type: "string", required: true }, args: { type: "string" } }, async (args, exec) => {
        if (!exec.agent) throw new Error("Missing agent");
        if (catalog.skills.some((s) => s.name === args.name)) return invokeSkill(args.name, args.args ?? "", exec.agent, exec.signal);
        const other = await exec.agent.ctx.get("skills").get(args.name, { cwd: workspace(exec.agent), scope: exec.agent, signal: exec.signal });
        if (!other || !other.invocation.modelInvocable) throw new Error("Skill unavailable");
        return renderSkillContent(other);
      }));
      return void 0;
    }
    if (states.has(agent)) return void 0;
    states.set(agent, state);
    live.add(agent);
    const current = state;
    atomicJson(rolePath, { agent: current.agent.name, ...current.activeSkill ? { skill: current.activeSkill.name, skillArgs: current.skillArgs ?? "" } : {} });
    const scoped = agent.ctx;
    scoped.get("systemPrompt").section({ name: "deployment:persona-prefix", order: 0, text: body(state.agent), interpolate: false });
    for (const skillName of state.agent.skills.filter((n) => !removal.skills?.includes(n))) {
      const skill = getSkill(skillName);
      scoped.get("systemPrompt").section({ name: "linktool:preload:" + skill.name, order: 50, text: body(skill), interpolate: false });
    }
    if (state.activeSkill) {
      const input = pending.getStore()?.activeSkill;
      scoped.get("systemPrompt").section({ name: "linktool:active-skill", order: 51, text: body(input ?? current.activeSkill).replaceAll("$ARGUMENTS", current.skillArgs ?? ""), interpolate: false });
    }
    scoped.get("systemPrompt").section({ name: "linktool:runtime", order: 60, interpolate: false, text: `\u8FC1\u79FB\u8FD0\u884C\u65F6\u4FE1\u606F\uFF08\u539F\u59CB\u89D2\u8272\u4E0E\u6280\u80FD\u6B63\u6587\u672A\u4FEE\u6539\uFF09\uFF1A
Agent \u6807\u8BC6\uFF1Alinktool-plugin:${state.agent.name}
\u5DE5\u4F5C\u76EE\u5F55\uFF1A${workspace(agent)}
\u63D2\u4EF6\u8D44\u6E90\u6839\u76EE\u5F55\uFF1A${resourceRoot2}
\u539F\u59CB plugin/ \u8DEF\u5F84\u7531\u5DE5\u5177\u9002\u914D\u5C42\u89E3\u6790\u81F3\u63D2\u4EF6\u8D44\u6E90\uFF1BSkill \u5185 ./scripts/ \u76F8\u5BF9\u4E8E\u6280\u80FD\u76EE\u5F55\u89E3\u6790\u3002
\u663E\u5F0F\u8C03\u7528\u72EC\u7ACB\u4E0A\u4E0B\u6587 Skill \u65F6\uFF0Cargs \u5FC5\u987B\u4F20\u5165\u5B8C\u6574\u4EFB\u52A1\u548C\u8F93\u5165\uFF1B\u4E0D\u8981\u8BA4\u4E3A\u72EC\u7ACB\u4E0A\u4E0B\u6587\u4F1A\u590D\u5236\u5F53\u524D\u804A\u5929\u5386\u53F2\u3002
Agent \u7684 skills \u5217\u8868\u5DF2\u6309\u539F\u914D\u7F6E\u9884\u52A0\u8F7D\u5B8C\u6574\u6B63\u6587\uFF1B\u5176\u4ED6\u6280\u80FD\u6309\u9700\u52A0\u8F7D\u3002
\u4EC5\u4F7F\u7528\u5F53\u524D\u5DE5\u5177\u6E05\u5355\uFF1B\u6CA1\u6709\u66B4\u9732\u7684\u5DE5\u5177\u4E0D\u5F97\u901A\u8FC7\u5176\u4ED6\u9014\u5F84\u7ED5\u8FC7\u3002${state.agent.metadata.model ? `
\u539F\u6A21\u578B\u522B\u540D\uFF1A${state.agent.metadata.model}\uFF1B\u5F53\u524D\u8DEF\u7531\uFF1A${JSON.stringify(config.modelAliases[String(state.agent.metadata.model)] ?? { mode: "inherit" })}\u3002` : ""}` });
    scoped.get("skills").registerProvider(() => skillProvider(state.agent, config));
    scoped.get("systemPrompt").section({ name: "linktool:skill-catalog", order: 61, interpolate: false, text: catalog.skills.filter((s) => !removal.skills?.includes(s.name) && skillAllowed(s, state.agent, config) && s.invocation.modelInvocable).map((s) => `Skill ${s.name} (context=${s.context}, agent=${s.agent ?? "current"}): ${String(s.metadata.description ?? "")}`).join("\n") });
    scoped.get("systemPrompt").section({ name: "linktool:mcp-names", order: 62, interpolate: false, text: `\u539F\u6B63\u6587\u7684 MCP \u540D\u79F0\u4F5C\u4E3A\u8BED\u4E49\u6807\u8BC6\u4FDD\u7559\u3002\u6267\u884C\u65F6\u5FC5\u987B\u4F7F\u7528\u5B9E\u9645 Harness \u77ED\u5DE5\u5177\u540D\uFF08DeepSeek \u51FD\u6570\u540D\u79F0\u6700\u591A 64 \u5B57\u7B26\uFF09\uFF0C\u4EC5\u8C03\u7528\u5F53\u524D\u5DE5\u5177\u6E05\u5355\u5B58\u5728\u7684\u9879\u76EE\uFF1A
${[...refs].filter((n) => allowed(n, current)).map((n) => `${n} \u2192 ${mcpTarget(n, config)}`).join("\n")}` });
    if (state.agent.tools.includes("Skill")) {
      scoped.get("tools").register(skillTool);
      scoped.get("tools").register(textTool("skill", "LinkTool scoped skill loader; context and agent binding are enforced.", { name: { type: "string", required: true }, args: { type: "string" } }, async (args, exec) => {
        if (!exec.agent) throw new Error("Missing agent");
        return invokeSkill(args.name, args.args ?? "", exec.agent, exec.signal);
      }));
    }
    if (state.agent.tools.includes("ToolSearch")) scoped.get("tools").register(textTool("ToolSearch", "Inspect actual registered tool schemas; unavailable servers are not presented as working tools.", { query: { type: "string", required: true }, max_results: { type: "integer" } }, async (args, exec) => ctx.tools.schemas(exec.agent).filter((t) => t.name.includes(args.query) || t.description?.includes(args.query)).slice(0, args.max_results ?? 10)));
    if (state.agent.metadata.memory === "project") {
      const path = join7(workspace(agent), ".dsh", "agent-memory", state.agent.name, "MEMORY.md");
      scoped.get("systemPrompt").section({ name: "linktool:project-memory", order: 55, interpolate: false, text: () => existsSync6(path) ? readFileSync4(path, "utf8") : "" });
      scoped.get("tools").register(textTool("linktool_memory", "Read or replace this agent project memory. Shared by this agent in the current project only.", { content: { type: "string" } }, async (args) => {
        if (args.content !== void 0) {
          mkdirSync2(dirname5(path), { recursive: true });
          writeFileSync2(path, args.content);
        }
        return existsSync6(path) ? readFileSync4(path, "utf8") : "";
      }));
    }
    scoped.get("tools").guard((exec) => {
      if (!allowed(exec.name, current)) return `Tool ${exec.name} denied by LinkTool agent ${current.agent.name}`;
      const args = mapArguments(mcpTarget(exec.name, config), exec.arguments, exec.agent, current.activeSkill);
      if (current.agent.metadata.permissionMode === "plan" && !current.approved) {
        if (exec.name.endsWith("__execute_gis_tool")) return "Agent is in planning mode";
        if (["Write", "write", "Edit", "edit", "Update"].includes(exec.name) && typeof args.file_path === "string" && !/[/\\]02_WorkSpace[/\\](task_plan\.md|workflow_script\.js)$/.test(args.file_path)) return "Planning mode only permits task_plan.md and workflow_script.js";
      }
      for (const field of ["file_path", "path"]) if (typeof args[field] === "string" && ["Write", "write", "Edit", "edit", "Update"].includes(exec.name) && inside(args[field], resourceRoot2)) return "Packaged plugin resources are read-only";
      return void 0;
    });
    scoped.on("agent/pre-step", async ({ step }, next) => {
      const decision = await next();
      if (decision.kind !== "enter") return decision;
      if (typeof current.agent.metadata.maxTurns === "number" && ++current.steps > current.agent.metadata.maxTurns) return { kind: "reject" };
      return decision;
    });
    refresh(agent);
    return void 0;
  });
  ctx.on("agent/disposed", ({ agent }) => {
    live.delete(agent);
  });
  let refreshing = false;
  ctx.on("tools/change", () => {
    if (refreshing) return;
    refreshing = true;
    try {
      for (const agent of live) refresh(agent);
    } finally {
      refreshing = false;
    }
  });
  hooks.install();
  ctx.on("agent/pre-step", async ({ agent, messages, signal }, next) => {
    const forkMessages = messages.filter((m) => {
      if (m.source.kind !== "skill-invocation") return false;
      const invokedName = m.source.name;
      return catalog.skills.some((s) => s.name === invokedName && s.context === "fork");
    });
    if (!forkMessages.length) return next();
    const outputs = [];
    for (const message of forkMessages) {
      if (message.source.kind !== "skill-invocation") continue;
      const args = messages.filter((m) => m.source.kind !== "skill-invocation").flatMap((m) => m.content).filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join("\n");
      outputs.push(hooks.message(JSON.stringify(await invokeSkill(message.source.name, args, agent, signal))));
    }
    const downstream = await next();
    if (downstream.kind !== "enter") return downstream;
    return { ...downstream, messages: [...downstream.messages.filter((m) => !forkMessages.some((f) => f.id === m.id)), ...outputs] };
  });
  ctx.systemPrompt.section({ name: "linktool:entry", order: 100, interpolate: false, text: `LinkTool GIS \u4E13\u7528\u63D2\u4EF6\u5DF2\u52A0\u8F7D\u3002GIS \u8BF7\u6C42\u4F7F\u7528 Agent \u5DE5\u5177\u59D4\u6D3E linktool-plugin:question-classify\uFF1B\u660E\u786E\u6307\u5B9A\u7684\u89D2\u8272\u53EF\u76F4\u63A5\u59D4\u6D3E\u3002\u89D2\u8272\u5217\u8868\uFF1A
${catalog.agents.map((a) => `- linktool-plugin:${a.name}: ${String(a.metadata.description ?? "")}`).join("\n")}
\u5B8C\u6574\u590D\u6742\u4EFB\u52A1\u7531 task-plan \u901A\u8FC7\u8FC1\u79FB\u540E\u7684 Workflow \u5DE5\u5177\u6267\u884C\u3002\u63D0\u793A\u8BCD\u4E2D\u539F\u59CB\u5DE5\u5177\u540D\u4ECD\u53EF\u7531\u76F8\u5E94 Agent \u4F7F\u7528\u3002` });
  ctx.systemPrompt.section({ name: "linktool:mcp-names", order: 101, interpolate: false, text: `\u5B9E\u9645 MCP \u8C03\u7528\u4F7F\u7528 Harness \u77ED\u5DE5\u5177\u540D\uFF1B\u539F\u63D0\u793A\u8BCD\u540D\u79F0\u6620\u5C04\u5982\u4E0B\uFF0C\u4EC5\u8C03\u7528\u5F53\u524D\u5DF2\u6CE8\u518C\u7684\u5DE5\u5177\uFF1A
${[...refs].map((n) => `${n} \u2192 ${mcpTarget(n, config)}`).join("\n")}` });
  if (config.mcpEnabled) {
    for (const [server, resolved] of Object.entries(resolvedServers())) {
      if (config.enabledServers.includes(server)) ctx.plugin(McpClient, resolved);
    }
  }
}
export {
  apply,
  inject,
  name
};
//# sourceMappingURL=index.js.map
