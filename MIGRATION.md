# 迁移清单与兼容边界

## 完整性

- 原 `plugin` 的 9528 个文件，合计 280808663 字节，复制到 `resources/plugin`。原程序、二进制、参考文件、Python 项目/锁文件以及原虚拟环境均保留。
- 6 个 Agent、21 个有注册元数据的 Skill、6 个 workflows 文件、8 个 MCP 配置；另一个 `scripts/color-style-mcp/SKILL.md` 是普通说明文件，不是可注册 Skill，仍然完整保留。
- 提示词正文及源文件 SHA-256 在 `config/catalog.json` / `config/source-manifest.json` 中记录；`npm run verify` 校验原样保留。
- 源 hooks 文件虽然叫 `hooks.json.bakcup`，按照用户要求全部启用，没有按 backup 禁用。

## Harness 适配

| Claude Code 项目项 | Harness 实现 |
|---|---|
| `.claude-plugin/plugin.json` | npm 插件清单 + `dsh.bundle.patch` + Cordis `apply` |
| `agents/*.md` frontmatter | 完整 catalog + `linktool:<角色>` subagent provider |
| Agent 的 `skills` | 每个角色的系统提示 section 中预加载完整正文 |
| `context: fork` | native spawn；不继承父聊天，使用显式参数和绑定角色 |
| inline Skill | 当前会话 Skill loader，返回原正文与参考资源路径 |
| `tools` / `disallowedTools` | native global tool mask、scoped aliases、不可被放行覆盖的 guard |
| `mcpServers` | 每个角色允许的服务器工具；显式禁用规则仍优先 |
| `allowed-tools` / `allowed_tools` | 保留元数据；激活技能时授予相应工具，角色明确禁止项优先 |
| 项目 memory | 当前项目 `.dsh/agent-memory/<角色>/MEMORY.md`，提供读写工具 |
| `maxTurns` | 角色 model step 次数上限，超限阻止继续步骤 |
| PreToolUse | native tools/pre-execute，原 stdin 格式，退出 2/deny 阻止 |
| PostToolUse | native tools/post-execute，结构化响应、反馈及上下文注入 |
| PostCompact | native compaction 完成事件映射，压缩后下一步骤恢复摘要 |
| Agent / Task* / ToolSearch | 保留原名的工具适配器；任务状态持久化到工作项目 |
| Workflow | native sandboxed Workflow engine，保留 agentType/meta/phases/parallel/pipeline 词汇 |
| Workflow 恢复 | 持久化成功节点缓存，同参数复用；原运行 + 最多一次 resume |
| 项目计划确认 | 实际 userQuestions 询问，计划内容哈希批准后才开始 Workflow |
| 旧资源路径 | 运行前映射为安装副本实际路径；带空格目录按 shell 规则传递 |

原 `.venv` 包含原机器绝对路径，不能作为可移植运行环境；已完整归档并恢复，实际启动重建环境到 `.runtime/mcp/<server>`。Python 服务没有 pyproject 时使用 uv 的无项目临时依赖环境。原 PDF 服务使用 `mcp.server.fastmcp`，执行参数限定 `mcp[cli]>=1.26,<2`，避免升级到不兼容的 MCP Python 2.x。

## 不改正文的源问题兼容处理

1. visualisation 的 `capabilities` YAML 数组未正确缩进；report-generate 的 description 内嵌 `: `。只规范解析输入，原文件字节不改。
2. `Wrtie` 映射到 Write；`Web_Search` 映射到 WebSearch；report 的 `pdf-read-mcp` 映射到已配置的 `pdf-reader-mcp`。
3. question-classify 的正文要求委派 data-retrieval，但 `tools` 未列 Agent。适配器为此角色补充 Agent，以执行原正文约定；原元数据仍完整保留。
4. gis-data-preview/map-image-generate、officecli-docx/officecli-xlsx 缺少角色声明；运行配置记录正文约定的 visualisation/report 所属关系，未把它们擅自加入原预加载列表。
5. 源 protected_dirs.json 中的 `${CLAUDE_CONFIG_DIR}`、`${USER_HOME}`、`${TEMP}` 原规范化函数没有展开；wrapper 按兼容环境变量展开，配置目录映射到 Harness 的 `.dsh`，并保留原 `.claude` 保护项。原文件保护 hook 的 `is_skills_directory` 调用两参数的 `normalize_path`，实际函数只接受一参数，并吞掉 TypeError，导致技能资料总被拦截。`scripts/hook-runner.py` 在加载时兼容该调用；源文件不改。
6. 原日志 hook 仅用文本包含 `error` 判断失败，成功 GIS JSON 中的 `error: null` 也被误判失败。运行时 wrapper 优先解析实际 JSON success 状态，保留真实失败记录；源文件不改。原增强日志 hook 从 `tool_input.tool_response` 读取结果；适配器同时提供这一字段和标准顶层 `tool_response`，避免错误被记作成功。
7. 源 OfficeCLI 检查脚本对 bundled binary 的相对层级定位不正确。执行环境把真正 `resources/plugin/bin` 加入 PATH，原有 PATH 回退找到随包二进制。
8. Windows Harness 默认提供 pwsh，没有 Bash；保留源 Bash 语法，通过 Git Bash 执行，再交给原 Bash guards 检查。
9. DeepSeek 函数名最多 64 字符。原 Claude MCP 长前缀可能超限，不能直接作为 API function 名称注册；实际使用 Harness 短名称，权限及 hook 匹配仍映射到原标识，系统提示附逐项映射表。
10. knowledge-db 的 `.bat` 相当于进入目录运行 uv；适配为直接 uv command/args/cwd，避免 cmd 包装及旧虚拟环境。
11. WebFetch 的原 prompt 参数保留，存在 prompt 时在独立模型请求中处理网页；不是丢弃 prompt 后仅返回原始网页。MCP resource 工具保留“可选 server 列举全部”的调用语义；无资源 capability 时列表为空，不伪造资源。

## 无法自动等价或源内容本来缺失的部分

| 项目 | 当前情况 / 需要接收方处理 |
|---|---|
| Claude 模型别名 | 原别名保留；默认继承 Harness 模型。要使用特定 Claude/其他型号，必须自行配置有效 provider/model。型号能力无法靠文件迁移保证等价。 |
| `permissionMode: acceptEdits` | 保留原元数据，但 Harness 的审批/沙箱权限由会话和 profile 决定，没有同名等价的角色级 Claude 权限模式。具体写入还受原 hooks 和 Harness 原生权限约束。 |
| `permissionMode: plan` | 适配器限制计划文件写入、禁止 task-plan 执行 GIS，Workflow 开始前要求真正的人类批准；不声称与 Claude Code 内建 plan UI/权限机制完全相同。 |
| PostCompact 时序 | 使用 Harness 原生 compaction 事件，在压缩后下一 model step 注入原脚本摘要；不是 Claude Code 同一事件实现。 |
| `plugin/CROSS_AGENT_RULES.md` | 源目录没有这个文件，但多个提示词引用它。未编造缺失正文；现有角色与 DSL 白名单按实际源文件执行。 |
| image-beautify 服务 | beautify-routing 正文引用 beautify_image，但原 MCP 配置没有对应服务。缺失工具不能伪造成可用；需要提供原服务或配置有效实现。 |
| Docx-Mcp_Server | report-generate 引用，但原 MCP 配置没有这个服务器。OfficeCLI 是现有报告链路，不宣称替代缺失服务全部能力。 |
| memory-server | 原 LAN endpoint 在本机连接 `fetch failed`。需要网络/VPN、实际服务和授权；可通过 LINKTOOL_MEMORY_URL / LINKTOOL_MEMORY_AUTHORIZATION 覆盖。 |
| ArcPy 与许可证 | MCP 可启动并列工具，但实际 GIS 运算需要接收方有效 ArcGIS Pro、数据和扩展许可证；不可随插件跨机器自动迁移。 |
| 原机器演示路径 | `new_draw_map.py` 的无 stdin 调试参数、example/backup 脚本，以及 schema 中原项目目录默认值保留。正常 color-style MCP 传入实际 aprx/数据/输出，不使用无输入调试参数；不要直接照搬演示脚本的私人路径。 |
| Workflow 源文档矛盾 | 某些参考示例使用 fs import，DSL 正文同时禁止文件系统/import。本适配按 sandbox 与 DSL 禁止规则拒绝该类脚本，不放宽权限去执行；需要按原 DSL 合法部分生成工作脚本。 |

## 实测范围

2026-10-05，在 Windows / Node 26.5 / Harness 0.2.0-rc.2：

- 全文件 SHA-256 与全部提示词正文一致。
- TypeScript 检查、ESM 构建通过。
- 真实 Harness 中通过模拟模型验证：6 个角色、完整原正文预加载、父会话历史隔离、report 禁止委派、question-classify 委派能力、fork/inline Skill。
- 启用原 hooks 后，资源 Read 与 Git Bash 调用随包 OfficeCLI 通过；实际 Python 反绕过 hook 拒绝直接 arcpy。
- 实际创建独立测试要素，通过 gis-tool 角色及启用的 hooks 调用 ArcPy GetCount 返回 1。只操作生成的测试数据。
- native Workflow 执行、恢复缓存不重新请求模型、第三次执行拒绝通过。
- 7 个 MCP 初始化和 listTools 通过，且真实 Harness 注册及各角色可见工具列表通过；memory-server 不可连接。
- 安装器在独立测试 profile 成功安装，bundle 能被 Harness 组成配置加载。

尚未使用付费真实模型执行完整 GIS 项目，也未对所有第三方业务 API、ArcPy 地理处理与 Web 交付全流程作验证。因此这里给出的“通过”针对上述实际检查范围。
