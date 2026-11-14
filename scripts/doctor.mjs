import { spawnSync } from 'node:child_process';
import { existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { packageRoot, resourceRoot, catalog } from '../lib/catalog.js';
import { resolvedServers } from '../lib/mcp.js';
import { childEnvironment } from '../lib/paths.js';
const problems = [];
const env = childEnvironment(process.cwd());
for (const command of ['uv', 'uvx', 'python']) {
  const result = spawnSync(command, ['--version'], { env, encoding: 'utf8', windowsHide: true });
  console.log(`${command}: ${result.status === 0 ? result.stdout.trim() : '不可用'}`);
  if (result.status !== 0) problems.push(command + ' 未安装或未加入 PATH');
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
const probe = spawnSync('python', ['-c', 'import sys;sys.path.insert(0,sys.argv[1]);from find_arcpy import find_py_interpreter;print(find_py_interpreter() or "NOT_FOUND")', join(resourceRoot,'scripts/shared')], {env,encoding:'utf8',windowsHide:true,timeout:15000});
console.log('ArcGIS Pro Python: ' + (probe.status===0 ? probe.stdout.trim() : '定位失败'));
if(probe.stdout?.trim()==='NOT_FOUND') problems.push('GIS 业务需要 ArcGIS Pro；请安装/授权并设置 ARCGIS_PRO_PATH');
if (problems.length) { console.error(problems.join('\n')); process.exitCode = 1; }
