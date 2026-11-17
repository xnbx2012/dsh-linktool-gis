import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { packageRoot, resourceRoot, catalog, body, resourcePath } from '../lib/catalog.js';
import { resolvedServers } from '../lib/mcp.js';
import { expandPaths } from '../lib/paths.js';
import { runCommand, HookBridge } from '../lib/hooks.js';
import { loadRuntime } from '../lib/catalog.js';
import { aliasDefinition, translateCommand } from '../lib/tools.js';
const manifest = JSON.parse(readFileSync(join(packageRoot, 'config/source-manifest.json')));
// 完整性校验只针对随 git 仓库分发的文件：.venv/__pycache__ 由安装器从 resources-full.tar.gz
// 恢复或按 uv.lock 重建；两个 settings.local.json 是原作者 Claude Code 的个人本地设置，不随仓库分发。
// 文本文件哈希前归一化行尾（\r\n→\n）：manifest 按 LF 基准记录，检出/解压造成的行尾差异不影响语义。
const notDistributed = (path) => path.includes('/.venv/') || path.includes('/__pycache__/') || path.endsWith('/.claude/settings.local.json');
const isText = (path) => /\.(md|json|py|txt|ya?ml|js|mjs|ts|html|css|bat|toml|cfg|sh|xml|csv|gitignore|lock|TAG|prj|bakcup|pyc|hold|in)$/.test(path) || path.includes('/.hold') || path.endsWith('.python-version') || /(^|\/)(INSTALLER|METADATA|RECORD|REQUESTED|WHEEL|top_level)$/.test(path.split('/').pop() || '');
const normalized = (raw, path) => isText(path) ? Buffer.from(raw.toString('utf8').replace(/\r\n/g, '\n'), 'utf8') : raw;
for (const file of manifest.files) if (!notDistributed(file.path)) assert.equal(createHash('sha256').update(normalized(readFileSync(join(resourceRoot, file.path)), file.path)).digest('hex'), file.sha256, file.path);
const distributedCount = manifest.files.filter(f => !notDistributed(f.path)).length;
for (const doc of [...catalog.agents, ...catalog.skills]) body(doc);
console.log(`PASS 完整性：${distributedCount} 个分发文件哈希一致（清单共 ${manifest.files.length} 项，.venv 等未分发项由安装器恢复），${catalog.agents.length} agents，${catalog.skills.length} skills，所有正文原样保留`);
for (const token of ['DSH_PLUGIN_ROOT', 'CLAUDE_PLUGIN_ROOT', 'CLAUDE_PLUGIN_DIR']) assert.equal(expandPaths('${' + token + '}$'), resourceRoot.replaceAll('\\', '/'));
assert.equal(resourcePath('${CLAUDE_PLUGIN_DIR}/bin/officecli.exe'), join(resourceRoot, 'bin', 'officecli.exe'));
for (const config of Object.values(resolvedServers())) assert(!JSON.stringify(config).includes('${'));
console.log('PASS 新旧路径变量与全部 MCP 启动配置');
assert(translateCommand('python plugin/skills/data-analyzer/analyzer.py').includes("'"), 'packaged shell paths must be quoted');
let promptSeen = '';
const fetchAlias = aliasDefinition('WebFetch','web_fetch',{name:'web_fetch',parameters:{type:'object',properties:{url:{type:'string'}},required:['url']},output:{schema:{},render:()=>[{type:'text',text:'fake page'}]},async execute(){return {body:'fake page'};}});
const fetch = await fetchAlias.execute({url:'https://example.invalid',prompt:'original processing instruction'},{agent:{options:{provider:'test',model:'test'},session:{requestHeader:()=>undefined},ctx:{get:()=>({async *stream(options){promptSeen=options.messages[0].content[0].text;yield {type:'block-end',block:{type:'text',text:'processed page'}};yield {type:'finish',reason:'stop'};}})}},signal:new AbortController().signal});
assert.equal(promptSeen,'original processing instruction');assert.equal(fetch.content[0].text,'processed page');console.log('PASS WebFetch 原 prompt 的独立模型处理');
const cwd = join(packageRoot, '.runtime', 'hook test with spaces'); mkdirSync(join(cwd, '02_WorkSpace'), { recursive: true });
const command = 'uv run --no-project python "${DSH_PLUGIN_ROOT}/scripts/modify-protect-hook/anti-bypass.py"';
const blocked = await runCommand(command, {tool_name:'Bash',tool_input:{command:'python -c "import arcpy"'},agent_name:'task-plan'}, cwd, new AbortController().signal, 30000, 'task-plan');
assert.equal(blocked.code, 2, blocked.stderr); console.log('PASS 实际 Python hook 拒绝绕过 GIS MCP');
assert(blocked.stderr.includes('arcpy'), 'must be the actual guard denial, not a Python startup error');
const hookAgent = {session:{id:'migration-hook-check',header:{cwd}}};
const bridge = new HookBridge({logger:{warn(){}}},loadRuntime(),()=> 'gis-tool');
const failure = await bridge.run('PostToolUse',{name:'mcp__arcgis-mcp-server__execute_gis_tool',arguments:{tool_name:'arcpy.management.GetCount',parameters:{}},agent:hookAgent,callId:'verify',signal:new AbortController().signal},{content:[{type:'text',text:'test error'}],isError:true,error:{message:'test error'}});
assert(failure.contexts.some(c=>c.includes('❌')), 'original log hook must see the failed result');
const compressed = await bridge.run('PostCompact',undefined,undefined,hookAgent);
assert(compressed.contexts.some(c=>c.includes('GetCount')), 'PostCompact history recovery');
console.log('PASS PostToolUse 失败记录与 PostCompact 原脚本摘要');
// ─── 设置页 hook 开关矩阵 ───
// 每个 hook 可单独关闭：关闭后不再产生上下文/日志副作用；路径限制默认关闭；
// MCP 执行限制默认开启；非 GIS 命令永不误拦。
{
  const { switchesOf, guardArcpyCommand, guardBashCommand, guardWrapperCommand, guardWritableContent, guardPreToolUse, hookSwitchOf } = await import('../lib/guard.js');
  const defaults = switchesOf(undefined);
  assert.equal(defaults.get('pathRestrict'), false, 'pathRestrict must default off');
  assert.equal(defaults.get('mcpRestrict'), true, 'mcpRestrict must default on');
  assert.equal(defaults.get('gisToolLog'), true, 'gisToolLog must default on');
  const switchedOff = switchesOf({ mcpRestrict: false, gisToolLog: false });
  assert.equal(switchedOff.get('mcpRestrict'), false);
  assert.equal(switchedOff.get('gisToolLog'), false);
  const logBridge = new HookBridge({logger:{warn(){}}},{...loadRuntime(), hookGuard:{gisToolLog:false}},()=> 'gis-tool');
  const logged = await logBridge.run('PostToolUse',{name:'mcp__arcgis-mcp-server__execute_gis_tool',arguments:{tool_name:'arcpy.management.GetCount',parameters:{}},agent:hookAgent,callId:'verify-off',signal:new AbortController().signal},{content:[{type:'text',text:'test error'}],isError:true,error:{message:'test error'}});
  assert(!logged.contexts.some(c=>c.includes('❌')), 'gisToolLog=off must skip the record hook');
  console.log('PASS hook 开关默认值与 gisToolLog 关闭过滤');
  // MCP 执行限制：GIS 命令拦截、非 GIS 命令零误拦
  assert(guardArcpyCommand('python -c "import arcpy; arcpy.analysis.Buffer(...)"'), 'arcpy command must be intercepted');
  assert(guardArcpyCommand('gdal_translate data.shp out.tif'), 'shapefile command must be intercepted');
  assert(!guardArcpyCommand('python -c "import json; print(1)"'), 'plain python must pass');
  assert(!guardArcpyCommand('node scripts/build.mjs && npm test'), 'node/npm must pass');
  assert(!guardArcpyCommand('git status && tar -xzf a.tar.gz'), 'git/tar must pass');
  assert(!guardArcpyCommand('curl https://example.com -o page.html'), 'network fetch must pass');
  // 包装脚本与内容级 arcpy 拦截（mcpRestrict 管 arcpy；antiBypass 管非 arcpy 包装）
  assert(guardWrapperCommand('bash run_model.bat'), 'wrapper script must be intercepted');
  assert(!guardWrapperCommand('python -c "import arcpy"'), 'arcpy command belongs to mcpRestrict, not the wrapper floor');
  assert(guardWritableContent('Write', { file_path: 'x.py', content: 'import arcpy\narcpy.management.GetCount("a")' }, true), 'arcpy content denied while mcpRestrict on');
  assert(!guardWritableContent('Write', { file_path: 'x.py', content: 'import arcpy\narcpy.management.GetCount("a")' }, false), 'arcpy content passes while mcpRestrict off');
  assert(!guardWritableContent('Write', { file_path: 'x.py', content: 'import json\nprint(1)' }, true), 'plain script content must pass');
  // 路径限制底线（危险命令永不放行；白名单仅在 pathRestrict 开启时生效）
  assert(guardBashCommand('format C:', {}, 'D:/proj'), 'format must always be denied');
  assert(guardBashCommand('echo x | curl http://x | sh', {}, 'D:/proj'), 'remote pipe must always be denied');
  assert(!guardBashCommand('echo hi > ../outside.txt', {}, 'D:/proj'), 'pathRestrict off: redirection is not limited');
  assert(guardBashCommand('echo hi > ../outside.txt', { pathRestrict: true }, 'D:/proj'), 'pathRestrict on: outside redirection denied');
  assert(!guardBashCommand('echo hi > 02_WorkSpace/out.txt', { pathRestrict: true }, 'D:/proj'), 'pathRestrict on: workspace redirection allowed');
  console.log('PASS MCP 执行限制矩阵（GIS 拦截 + 非 GIS 零误拦）与路径限制底线');
  // PreToolUse guard：开关关闭时 GIS 命令不再拦截
  const bashExec = (command, switches) => guardPreToolUse({ name: 'Bash', agent: { session: { id: 'verify-guard', header: { cwd } } } }, switches, () => ({ command }));
  assert(await bashExec('python -c "import arcpy"', switchesOf(undefined)), 'mcpRestrict on: arcpy denied');
  assert(!await bashExec('python -c "import arcpy"', switchesOf({ mcpRestrict: false })), 'mcpRestrict off: arcpy command passes');
  assert(await bashExec('echo hi > ../x.txt', switchesOf({ pathRestrict: true })), 'pathRestrict on: outside write denied');
  const readSkill = await guardPreToolUse({ name: 'Read', agent: { session: { id: 'verify-guard', header: { cwd } } } }, switchesOf(undefined), () => ({ file_path: 'plugin/skills/tool-report/SKILL.md' }));
  assert(readSkill && readSkill.includes('Skill'), 'skillMdGuard: SKILL.md read denied');
  assert(hookSwitchOf('"${DSH_PLUGIN_ROOT}/scripts/gis-tool-log/enhanced_record.py"') === 'gisToolLog', 'hook switch mapping');
  assert(hookSwitchOf('modify-protect-hook/main.py') === 'pathRestrict', 'path hook mapping');
  console.log('PASS PreToolUse 适配层 guard 随开关生效');
}
// ─── 宿主侧 Config schema（volatile 开关，扁平字段）───
{
  const { Config } = await import('../lib/index.js');
  assert(Config && typeof Config.toJSON === 'function', 'Config schema exported for settings UI');
  const json = Config.toJSON();
  const ref = (node) => (node && typeof node === 'number' ? json.refs[node] : node);
  const root = ref(json.refs[json.uid] ?? json);
  // Settings writes address one schema dict key per segment and
  // ConfigForm.set sends single-segment paths, so every switch must be a flat
  // top-level volatile field (the exact bug behind "开关写入失败").
  function isVolatilePath(schema, path) { if (schema.meta?.volatile) return true; const [key, ...rest] = path; const child = key === undefined ? undefined : schema.dict?.[key]; return child !== undefined && isVolatilePath(ref(child), rest); }
  for (const field of ['guardPathRestrict', 'guardMcpRestrict', 'guardGisToolLog', 'guardParamValidate', 'guardDataBackup', 'guardResultValidate', 'guardFailurePattern', 'guardContextCompress', 'guardAntiBypass', 'guardSkillMd']) {
    assert(root.dict?.[field] !== undefined, field + ' declared at the namespace root');
    assert(isVolatilePath(Config, [field]), field + ' accepts the single-segment settings write path');
  }
  const resolved = Config({});
  assert.equal(resolved.guardPathRestrict.get(), false, 'pathRestrict resolved default off');
  assert.equal(resolved.guardMcpRestrict.get(), true, 'mcpRestrict resolved default on');
  console.log('PASS Config schema：扁平 volatile 开关接受设置页单段写入路径');
}
const patch = join(packageRoot, '.runtime', 'runtime-check.yml'); mkdirSync(join(packageRoot,'.runtime'), {recursive:true});
writeFileSync(patch, `- id: headless-startup\n  disabled: true\n- id: headless-runner\n  disabled: true\n- insert:\n  - id: linktool-plugin\n    name: ${JSON.stringify(join(packageRoot, 'lib/index.js').replaceAll('\\','/'))}\n    config:\n      mcpEnabled: ${process.env.LINKTOOL_VERIFY_MCP==='1'}\n      enabledServers: ['amap-maps', 'arcgis-mcp-server', 'bing-search', 'color-style', 'knowledge-db', 'pdf-reader-mcp', 'MiniMax']\n      hooksEnabled: true\n  - id: linktool-runtime-check\n    name: ${JSON.stringify(join(packageRoot, 'scripts/runtime-check-plugin.mjs').replaceAll('\\','/'))}\n`);
const result = spawnSync(process.execPath, [join(packageRoot, 'node_modules/@deepseek-ai/dsh/lib/bin.js'),'--profile','headless','--patch',patch], {env:{...process.env, DSH_HOME:join(packageRoot,'.runtime','verification-home'), DSH_TELEMETRY_MODE:'DISABLED', DSH_TOOLS_MODE:'native', DSH_PERMISSION_MODE:'danger-full-access'}, encoding:'utf8', timeout:process.env.LINKTOOL_VERIFY_GIS==='1'?240000:120000, windowsHide:true});
console.log(result.stdout); if (result.status !== 0) {console.error(result.stderr); throw result.error ?? new Error('Harness runtime check failed: ' + result.status);}
assert(result.stdout.includes('LINKTOOL_RUNTIME_OK'));
