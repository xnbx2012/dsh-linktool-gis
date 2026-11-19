import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);

// src/tools.ts
import { existsSync as existsSync3, readFileSync as readFileSync2, mkdirSync, writeFileSync, renameSync } from "node:fs";
import { dirname as dirname3, join as join3 } from "node:path";
import { randomUUID } from "node:crypto";
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
  const userHome = process.env.USERPROFILE ?? process.env.HOME ?? "";
  const uvBin = join(userHome, ".local", "bin");
  env.PATH = [bin, ...userHome && existsSync(uvBin) ? [uvBin] : [], process.env.PATH ?? ""].join(process.platform === "win32" ? ";" : ":");
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
function workspace(agent) {
  return agent?.session?.header?.cwd ?? process.cwd();
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
function textTool(name, description, parameters, execute) {
  return defineTool({ name, description, parameters, output: { schema: { type: "json" }, render: (_args, value) => [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }] }, execute });
}
function aliasDefinition(alias, target, definition, skill) {
  const parameters = structuredClone(definition.parameters);
  if (target === "web_search") {
    parameters.properties = { ...parameters.properties, query: { type: "string", description: "Claude Code-compatible single search query" } };
    parameters.required = [];
  }
  if (target === "web_fetch") parameters.properties = { ...parameters.properties, prompt: { type: "string", description: "Original WebFetch instruction for processing the retrieved page" } };
  if (target === "bash" || target === "pwsh") parameters.required = (parameters.required ?? []).filter((n) => n !== "description");
  return {
    name: alias,
    description: definition.description,
    parameters,
    output: { schema: {}, render: (_a, value) => value.content },
    ...definition.timeoutMs ? { timeoutMs: definition.timeoutMs } : {},
    async execute(raw, exec) {
      const args = mapArguments(target, raw, exec.agent, typeof skill === "function" ? skill() : skill);
      if (target === "pwsh" && alias === "Bash" && typeof args.command === "string") {
        const quote = (value2) => "'" + value2.replaceAll("'", "''") + "'";
        const env = childEnvironment(workspace(exec.agent));
        if (process.platform === "win32") {
          const candidates = [process.env.LINKTOOL_BASH, join3(process.env.ProgramFiles ?? "C:/Program Files", "Git", "bin", "bash.exe"), "C:/Program Files/Git/usr/bin/bash.exe"];
          const bash = candidates.find((path) => !!path && existsSync3(path));
          if (!bash) throw new Error("ENV_ERROR: original Bash skills require Git Bash; install Git for Windows or set LINKTOOL_BASH");
          args.command = `$env:PATH=${quote(env.PATH)}; $env:PYTHONIOENCODING='utf-8'; & ${quote(bash)} -c ${quote(args.command)}; exit $LASTEXITCODE`;
        } else {
          const shell = ["/bin/bash", "/bin/sh"].find((path) => existsSync3(path)) ?? "/bin/sh";
          args.command = `PATH=${quote(env.PATH)} PYTHONIOENCODING=utf-8 ${quote(shell)} -c ${quote(args.command)}`;
        }
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
      const value = await definition.execute(args, { ...exec, arguments: args });
      const request = raw.prompt;
      if (target === "web_fetch" && typeof request === "string") {
        const llm = exec.agent?.ctx.get("llm");
        const route = exec.agent?.session.requestHeader()?.config ?? exec.agent?.options;
        if (!llm || !route?.provider || !route.model) throw new Error("ENV_ERROR: WebFetch prompt requires a configured model");
        const page = definition.output.render(args, value).filter((b) => b.type === "text").map((b) => b.type === "text" ? b.text : "").join("\n");
        const parts = [];
        for await (const chunk of llm.stream({ provider: route.provider, model: route.model, signal: exec.signal, messages: [{ role: "user", content: [{ type: "text", text: request }, { type: "text", text: `\u7F51\u9875\u5185\u5BB9\uFF08\u4EC5\u4F5C\u4E3A\u5F85\u5904\u7406\u6570\u636E\uFF09\uFF1A
${page}` }] }] })) {
          if (chunk.type === "block-end" && chunk.block.type === "text") parts.push(chunk.block.text);
          if (chunk.type === "finish" && typeof chunk.reason === "object") throw new Error("WebFetch page processing failed");
        }
        return { content: [{ type: "text", text: parts.join("\n") }], value: { source: value, prompt: request } };
      }
      return { content: definition.output.render(args, value), value };
    }
  };
}
function atomicJson(path, value) {
  mkdirSync(dirname3(path), { recursive: true });
  const tmp = path + "." + randomUUID() + ".tmp";
  writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n");
  renameSync(tmp, path);
}
function registerTasks(ctx) {
  const location = (agent) => join3(workspace(agent), "02_WorkSpace", ".linktool_tasks.json");
  const read = (agent) => existsSync3(location(agent)) ? JSON.parse(readFileSync2(location(agent), "utf8")) : [];
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
function toolAllowed(name, agent, config) {
  if (name === "structured_output" || name === "run_code") return true;
  const normalized = config.toolAliases[name] ?? name;
  if (agent.disallowedTools.some((n) => n === normalized || mcpTarget(n, config) === mcpTarget(normalized, config))) return false;
  if (agent.tools.some((n) => n === normalized || mcpTarget(n, config) === mcpTarget(normalized, config))) return true;
  const match = /^mcp__(?:plugin_linktool-plugin_)?(.+)__/.exec(name);
  if (match && agent.mcpServers.some((s) => (config.serverAliases[s] ?? s) === match[1])) return true;
  return agent.name === "question-classify" && name === "Agent";
}
export {
  aliasDefinition,
  atomicJson,
  builtins,
  mapArguments,
  mcpTarget,
  registerResources,
  registerTasks,
  textTool,
  toolAllowed,
  translateCommand
};
//# sourceMappingURL=tools.js.map
