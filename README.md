# LinkTool — DeepSeek Harness 插件

将原 Claude Code GIS 插件迁移为 DeepSeek Harness 的 Cordis 插件。包含 **6 个 Agent、21 个注册 Skill、8 个 MCP 配置、10 个已启用的 hook 命令绑定**，以及完整的源程序、参考资料、二进制和依赖资料。原文件存放在 `resources/plugin`，提示词正文没有改写。

目标版本：**DeepSeek Harness 0.2.0-rc.2**。不要直接在 0.1.x 上加载；两个版本的 Agent、Skill、Workflow 接口不同。

## 0. 凭据说明（公开仓库）

本仓库**不包含任何 API key 或密码**。`config/mcp.json` 与 `resources/plugin/.claude-plugin/plugin.json` 中的凭据均为 `${ENV_VAR}` 占位符，安装后通过环境变量注入（见第 1 节「配置接收方自己的环境」）。未设置对应环境变量时占位符展开为空值，相关 MCP 服务将无法认证。

需要注意的占位符：

| 环境变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY` | Harness 模型账户（Harness 自身配置） |
| `AMAP_MAPS_API_KEY` | 高德地图 MCP |
| `SILICONFLOW_API_KEY` | knowledge-db MCP 嵌入服务 |
| `MINIMAX_API_KEY` / `MINIMAX_API_HOST` | MiniMax MCP |
| `LINKTOOL_MEMORY_URL` / `LINKTOOL_MEMORY_USERNAME` / `LINKTOOL_MEMORY_PASSWORD` | memory MCP（streamable-http） |
| `LINKTOOL_MEMORY_AUTHORIZATION` | memory MCP 的 Authorization 头（可选，替代用户名/密码头） |

`bin/officecli.exe`（32 MB）与 `scripts/knowledge-db-mcp/data.sqlite`（20 MB）按原样入库；其余大件不入库：

- `node_modules/`、`.runtime/`：本机依赖与运行缓存，`npm ci` 与安装器会重建。
- `resources-full.tar.gz`：含源机器 `.venv` 的完整归档，由 `node scripts/archive-resources.mjs` 生成，安装器在安装时恢复。克隆本仓库后请先运行它，再执行安装。
- `**/.venv/`：Python 虚拟环境，各 Python MCP 按 `pyproject.toml`/`uv.lock` 在安装位置重建。

## 1. 对方拿到以后怎么安装

### 运行环境

- Windows 10/11，Node.js 22 或更高版本，npm 能连接 npm 包源。
- Python 3.12 或更高版本，以及 `uv`/`uvx`（推荐通过 uv 管理服务自己的环境）。
- Git for Windows：原 Skill 命令使用 Bash 语法；Windows Harness 默认只有 PowerShell，本插件通过 Git Bash 适配这些命令。
- 系统 `tar` 可用（Windows 10/11 通常自带）。安装脚本用它恢复完整源资源。
- 实际 GIS 运算需要安装并授权 **ArcGIS Pro**，不能用普通 Python 替代 ArcPy。
- Harness 需要配置自己的模型账户/API。MCP 的业务 API 凭据也是接收方自己的配置。

可以用这些命令检查前置环境：

```powershell
node --version
npm --version
python --version
uv --version
tar --version
```

如果 uv 未安装，可按照 [uv 官方 Windows 安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装。Git 从 [Git for Windows](https://gitforwindows.org/) 安装。

### 一条安装命令

克隆本仓库（或解压发布包）后，进入 **dsh 文件夹**，在 PowerShell 执行：

```powershell
node scripts/archive-resources.mjs   # 克隆仓库时需要；发布包内已自带归档
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Profile web
```

这条命令先安装锁定的 Node 依赖，再安装插件。已有依赖时也可运行 `npm run install:plugin -- web`。

安装器使用固定版本的 Harness CLI，将本目录安装到 `web` profile，自动加入 bundle，并恢复 npm/pnpm 默认会忽略的完整源资源。默认所有 hooks 和 8 个 MCP 配置都启用。**接收方不需要旁边另放一个原始 `plugin` 文件夹。**

安装到一个新的独立 profile：

```powershell
npm run install:plugin -- linktool
```

不存在的 profile 会先按 `web` 模板初始化。已有 profile 保留自身应用类型；`desktop` profile 由 Harness 桌面端专门管理，本命令不适用于它。

启动（请在你的 GIS 项目目录运行，工作目录是数据工作空间）：

```powershell
npx @deepseek-ai/dsh@0.2.0-rc.2 --profile web
```

自定义 profile 将末尾 `web` 换成安装时的名称。默认 Web 地址通常为 `http://127.0.0.1:3080`，以启动日志显示的地址为准。

### 配置接收方自己的环境

在启动 Harness 的 PowerShell 中按需设置；以下全部是示例占位值：

```powershell
$env:DEEPSEEK_API_KEY = '接收方自己的模型 API key'
$env:AMAP_MAPS_API_KEY = '接收方自己的高德 key'
$env:SILICONFLOW_API_KEY = '接收方自己的 SiliconFlow key'
$env:MINIMAX_API_KEY = '接收方自己的 MiniMax key'
$env:MINIMAX_API_HOST = '接收方的 MiniMax API 地址'
$env:ARCGIS_PRO_PATH = 'C:\Program Files\ArcGIS\Pro'
```

**环境变量是必需的**：仓库内的 `config/mcp.json` 只含 `${ENV_VAR}` 占位符，未设置时对应凭据为空，相关 MCP 无法认证。

`ARCGIS_PRO_PATH` 指向 **Pro 安装目录**，不是 `python.exe`。插件同时保留原有的自动查找逻辑。

Git 不在默认位置时：

```powershell
$env:LINKTOOL_BASH = 'D:\Git\bin\bash.exe'
```

原 memory MCP 是局域网服务。换成对方能访问的实际服务：

```powershell
$env:LINKTOOL_MEMORY_URL = 'http://实际服务器地址:端口/mcp'
$env:LINKTOOL_MEMORY_USERNAME = '用户名（X-Auth-Username 头）'
$env:LINKTOOL_MEMORY_PASSWORD = '密码（X-Auth-Password 头）'
$env:LINKTOOL_MEMORY_AUTHORIZATION = '或直接提供 Authorization 请求头值'
```

环境变量优先于配置文件中的占位符值。永久配置也可以修改**已安装副本**的 `config/mcp.json`（或本仓库副本后重新安装）；默认位置是 `%USERPROFILE%\.dsh\profiles\web\node_modules\@linktool\dsh-plugin`。设置过 `DSH_HOME` 时，该路径改在其下。修改配置后重启 Harness。

### 准备 GIS 项目目录

```text
你的项目/
├── 01_DataBackup/    输入与备份，hooks 限制为只读
├── 02_WorkSpace/     中间数据、计划、Workflow、日志
└── 03_Result/        最终结果
```

源 hooks 会限制上述目录以外的操作，这是启用后的原始规则。技能参考资料通过插件资源路径读取，Skill 正文用 Skill 工具加载。

## 2. 发给别人怎么发

在开发目录执行：

```powershell
npm run build
npm run release
```

会在旁边生成 `dsh-release/linktool-dsh-3.0.0.zip`，包含顶层 `dsh` 文件夹、中文说明、已编译入口、完整源资源归档、源码、锁文件与安装脚本；不包含开发 `node_modules`、运行缓存或你的 Harness 会话。把 **zip 整体**发给接收方，让对方解压并按第 1 节安装。再次生成前请移走已有 `dsh-release/dsh` 文件夹，防止新旧文件混杂。

**当前仓库版本已将所有凭据替换为 `${ENV_VAR}` 占位符，适合公开发布。** 接收方使用自己的环境变量注入凭据，无需修改提示词；环境变量优先于配置值。若需要生成包含真实凭据的私下分发包，请在本地配置文件中填入凭据后执行 `npm run build` 与 `npm run release`，并注意不要把该包或包含凭据的提交推送到公开仓库。

`resources-full.tar.gz` 用于保存包括原 `.venv` 在内的全部源文件，解决 npm/pnpm 默认忽略虚拟环境的问题。安装器会恢复这个归档。原 `.venv` 包含原机器路径，运行时不会直接使用它；各 Python MCP 按自己的 `pyproject.toml`/`uv.lock` 在安装位置重建环境。

如果改过适配层或资源，请先构建和重建归档，再安装更新：

```powershell
npm run build
node scripts/archive-resources.mjs
npm run install:plugin -- web
```

Harness 的 `file:` 安装是副本，开发目录的修改不会自动进入已安装 profile。

## 3. 如何检查安装

在解压后的 `dsh` 目录运行：

```powershell
npm run doctor
npm run check
npm run verify
npm run check:mcp
```

- `doctor` 检查前置工具和解析后的 MCP 路径；生成本机 `.runtime/resolved-mcp.json`（包含凭据，请不要分发）。
- `check` 检查 TypeScript。
- `verify` 校验 9527 个源文件 SHA-256 和全部提示词；在真实 Harness 中使用本地模拟模型检查 6 个角色、正文预加载、父会话隔离、Skill、启用 hooks 的资源读取/OfficeCLI 执行，以及 Workflow 缓存恢复与重试限制。不消耗模型 API。
- `check:mcp` 真正连接 MCP 并列出工具，需要联网，首次可能下载 Python/npm 依赖；不执行 GIS 运算或收费图片操作。

需要额外验证真实 Harness 中的 MCP 注册与 ArcPy 链路时，可运行下面的扩展检查。ArcPy 检查仅创建并处理 `.runtime` 下的独立测试数据，不处理你的业务数据：

```powershell
$env:LINKTOOL_VERIFY_MCP = '1'
$env:LINKTOOL_VERIFY_GIS = '1'
npm run verify
Remove-Item Env:LINKTOOL_VERIFY_MCP, Env:LINKTOOL_VERIFY_GIS
```

本机检查记录：7 个 MCP 已成功握手（高德、ArcGIS、Bing、color-style、knowledge-db、PDF、MiniMax）；原局域网 memory 服务目前 `fetch failed`。握手通过说明进程和 MCP 接口可用，**不表示 ArcPy 运算、第三方 key 权限及所有业务请求都已实测通过**。

已额外通过真实 ArcPy 冒烟检查：在测试数据库创建 1 个要素，经 `gis-tool` 角色及启用 hooks 的 MCP 执行 GetCount，返回 1；日志正确记录 success。其他 GIS 工具和实际业务项目仍需用你的数据验收。

## 4. 目录与配置

```text
dsh/
├── lib/                    Harness 可加载的 ESM 入口及适配模块
├── src/                    TypeScript 适配源码
├── config/
│   ├── catalog.json        完整 agent/skill 元数据、关联、上下文与正文哈希
│   ├── mcp.json            MCP 执行配置；使用插件解析的 DSH 路径变量
│   ├── hooks.json          已启用的原 hook 绑定及启动适配
│   ├── runtime.json        模型路由、别名、启用开关与技能关联
│   └── source-manifest.json  全部源文件完整性清单
├── resources/plugin/       原插件全部文件（不含 .venv，克隆后运行 scripts/archive-resources.mjs 重建归档）
├── resources-full.tar.gz   原插件完整归档；不入库，由 archive-resources.mjs 生成
├── scripts/                安装、分发、检查及兼容启动脚本
├── cordis.patch.yml        Cordis 插件挂载 patch
├── package.json
├── package-lock.json
├── README.md
└── MIGRATION.md            语义映射、源文件问题与不能等价迁移的部分
```

`${DSH_PLUGIN_ROOT}` / `${DSH_PLUGIN_DIR}` 指向安装副本的 `resources/plugin`，`${DSH_ADAPTER_ROOT}` 指向适配包根目录，`${DSH_PROJECT_DIR}` 指向工作目录。**这些变量由本插件解析，不能把 `config/mcp.json` 当作原生 Harness 配置直接导入。** 交给 `dsh-mcp-client` 的 command/args/cwd/env 已经是实际路径。

提示词内原 `plugin/...`、`${CLAUDE_PLUGIN_ROOT}`、`${CLAUDE_PLUGIN_DIR}` 写法由工具适配层处理；原程序收到兼容环境变量。保留这些字面文本是为了不改原提示词，实际执行不依赖 Claude Code。

## 5. 角色、技能与上下文

| Agent | 原配置预加载的 Skill |
|---|---|
| data-retrieval | data-retrieval |
| gis-data-visualisation | 原配置没有预加载列表，按需调用 |
| gis-tool | param-confirm、tool-execute、tool-retry、result-confirm、visual-check |
| question-classify | question-classify |
| report | tool-report、conclusion-report、officecli |
| task-plan | gis-task-plan、data-doubt-check、task-data-manage、workflow-dsl |

Agent 的预加载列表会注入 Skill 完整正文；**显式调用** `context: fork` Skill 时，则按其 agent 绑定新建独立会话，不复制调用者聊天历史，输入必须通过 `args` 明确传入。其余 Skill 在当前会话加载。`catalog.json` 保留原 `agent`、`context`、工具允许列表及全部其他 frontmatter。

原 `haiku`/`sonnet`/`opus` 是 Claude 型号别名，当前默认继承 Harness 会话模型。若需要分别使用指定模型，在 `config/runtime.json` 的 `modelAliases` 中配置：

```json
{
  "sonnet": { "mode": "route", "provider": "已注册的实际 provider", "model": "实际模型 id" }
}
```

不要照抄占位值；模型必须已在接收方的 Harness 中可用。不能把继承 DeepSeek 模型视为与原 Claude 型号等价。Harness 实际 MCP 函数使用不超过 64 字符的短名称；原长名称只保留为元数据和提示词语义标识，运行提示提供逐项映射。更多限制与源插件缺失组件见 [MIGRATION.md](MIGRATION.md)。
