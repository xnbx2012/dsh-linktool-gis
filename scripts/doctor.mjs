import { spawnSync } from 'node:child_process';
import { existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { packageRoot, resourceRoot, catalog } from '../lib/catalog.js';
import { resolvedServers } from '../lib/mcp.js';
import { childEnvironment } from '../lib/paths.js';
const problems = [];
const env = childEnvironment(process.cwd());
// Windows 上命令名是 python，Linux/macOS 发行版通常只有 python3。
const pythonCommand = process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3');
for (const command of ['uv', 'uvx', pythonCommand]) {
  const result = spawnSync(command, ['--version'], { env, encoding: 'utf8', windowsHide: true });
  console.log(`${command}: ${result.status === 0 ? result.stdout.trim() : '不可用'}`);
  // python 只是部分脚本的入口，缺失不阻塞插件运行；uv/uvx 才是 MCP 启动的硬依赖。
  if (result.status !== 0 && command !== pythonCommand) problems.push(command + ' 未安装或未加入 PATH');
  else if (result.status !== 0) console.log(`  （${command} 缺失不影响 MCP 启动；仅影响需要 python 命令的脚本）`);
}
if (process.platform === 'win32') {
  const bash = process.env.LINKTOOL_BASH ?? join(process.env.ProgramFiles ?? 'C:/Program Files', 'Git/bin/bash.exe');
  console.log('Git Bash: ' + (existsSync(bash) ? '已找到' : '未找到'));
  if (!existsSync(bash)) problems.push('安装 Git for Windows，或设置 LINKTOOL_BASH');
}
const servers = resolvedServers();
for (const [name, server] of Object.entries(servers)) {
  if (JSON.stringify(server).includes('${')) problems.push(name + ': 未解析配置变量');
  console.log(`MCP ${name}: ${server.transport}; ${(server.args ?? []).filter(a => String(a).endsWith('.py')).join(' ') || server.command || '(HTTP 配置已解析)'}`);
}
mkdirSync(join(packageRoot, '.runtime'), { recursive: true });
writeFileSync(join(packageRoot, '.runtime', 'resolved-mcp.json'), JSON.stringify(servers, null, 2));
console.log(`已生成本机解析配置 .runtime/resolved-mcp.json（含凭据，请勿分发）。Agents=${catalog.agents.length}，Skills=${catalog.skills.length}`);
console.log('ArcGIS/ArcPy、服务凭据、LAN memory 服务仍需在接收方机器上配置；doctor 不执行收费 API 或 GIS 操作。');
const probe = spawnSync(pythonCommand, ['-c', 'import sys;sys.path.insert(0,sys.argv[1]);from find_arcpy import find_py_interpreter;print(find_py_interpreter() or "NOT_FOUND")', join(resourceRoot,'scripts/shared')], {env,encoding:'utf8',windowsHide:true,timeout:15000});
console.log('ArcGIS Pro Python: ' + (probe.status===0 ? probe.stdout.trim() : '定位失败'));
// arcpy 引擎是 Windows 专属（ArcGIS Pro 不提供 Linux/macOS 版本），非 Windows 上不算问题。
if (process.platform === 'win32' && probe.stdout?.trim()==='NOT_FOUND') problems.push('GIS 业务需要 ArcGIS Pro；请安装/授权并设置 ARCGIS_PRO_PATH');
else if (process.platform !== 'win32') console.log('ArcGIS Pro Python: 非 Windows 平台无需 arcpy 引擎（Windows 专属）');
if (problems.length) { console.error(problems.join('\n')); process.exitCode = 1; }
