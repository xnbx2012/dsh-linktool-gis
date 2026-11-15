import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';
import { catalog, body } from '../lib/catalog.js';
import { resourceRoot } from '../lib/catalog.js';
export const name = 'linktool-runtime-check';
export const inject = ['llm', 'agents', 'tools', 'subagents', 'workflowEngine'];
export function apply(ctx) {
  console.log('RUNTIME check mounted');
  const calls = [];
  class Fake extends LlmAdapter {
    async *stream(options) {
      calls.push(options);
      const block = { type: 'text', text: '{"status":"success","checked":true}' };
      yield { type: 'block-start', index: 0, blockType: 'text' };
      yield { type: 'block-end', index: 0, block };
      yield { type: 'finish', reason: 'stop' };
    }
  }
  ctx.llm.registerAdapter(['linktool-test'], new Fake());
  setTimeout(async () => {
    console.log('RUNTIME ready');
    let handle;
    try {
      const cwd = join(process.cwd(), '.runtime', 'test project with spaces'); mkdirSync(join(cwd, '02_WorkSpace'), { recursive: true });
      handle = await ctx.agents.create({ sessionId: randomUUID(), meta: { cwd }, agentOptions: { provider: 'linktool-test', model: 'test' } });
      const agent = handle.agent;
      if(process.env.LINKTOOL_VERIFY_MCP==='1') {
        const prefixes=['arcgis-mcp-server','pdf-reader-mcp','color-style','knowledge-db','MiniMax','amap-maps','bing-search'];
        for(let i=0;i<200 && !prefixes.every(prefix=>ctx.tools.schemas().some(s=>s.name.startsWith('mcp__'+prefix+'__')));i++) await new Promise(r=>setTimeout(r,300));
        for(const prefix of ['arcgis-mcp-server','pdf-reader-mcp','color-style','knowledge-db','MiniMax','amap-maps','bing-search']) assert(ctx.tools.schemas().some(s=>s.name.startsWith('mcp__'+prefix+'__')),prefix+' native registration');
        console.log('RUNTIME PASS 7 native MCP registrations');
      }
// 0.2.1-rc.5: startActivation 取代了 subagents.start；activation 结果通过 .result/.dispose 使用。
const startLinktool = (name, request) => ctx.subagents.startActivation({ provider: name, label: request.label ?? name, delivery: 'caller', signal: request.signal, request });
if (process.env.LINKTOOL_VERIFY_GIS === '1') {
        const locate = spawnSync('python',['-c','import sys;sys.path.insert(0,sys.argv[1]);from find_arcpy import find_py_interpreter;print(find_py_interpreter() or "")',join(resourceRoot,'scripts/shared')],{encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
        const python = locate.stdout.trim(); assert(python,'ArcGIS Pro Python required');
        const create = spawnSync(python,['-c','import arcpy,os,sys;root=sys.argv[1];gdb=os.path.join(root,"migration_smoke.gdb");arcpy.env.overwriteOutput=True;arcpy.management.CreateFileGDB(root,"migration_smoke.gdb") if not arcpy.Exists(gdb) else None;fc=arcpy.management.CreateFeatureclass(gdb,"migration_point","POINT",spatial_reference=4326)[0];cursor=arcpy.da.InsertCursor(fc,["SHAPE@XY"]);cursor.insertRow([(0,0)]);del cursor;print(fc)',join(cwd,'02_WorkSpace')],{encoding:'utf8',windowsHide:true,timeout:90000});
        assert.equal(create.status,0,create.stderr);const feature=create.stdout.trim();
        const run=await startLinktool('linktool:gis-tool',{parent:agent,signal:new AbortController().signal,prompt:[{type:'text',text:'integration fixture role'}]});await run.result;
        const result=await ctx.tools.execute({callId:randomUUID(),name:'mcp__arcgis-mcp-server__execute_gis_tool',arguments:{tool_name:'arcpy.management.GetCount',parameters:{in_rows:feature}},agent:run.localAgent,signal:new AbortController().signal});
        assert(!result.isError,JSON.stringify(result));assert(JSON.stringify(result).includes('1'),JSON.stringify(result));assert.equal(JSON.parse(readFileSync(join(cwd,'02_WorkSpace','gis-tool-logs.json'),'utf8')).at(-1).status,'success','successful ArcPy result must be logged as success');await run.dispose();
        console.log('RUNTIME PASS actual ArcPy GetCount through GIS agent + enabled hooks');
      }

      agent.followup(createUserMessage({content:[{type:'text',text:'PARENT_HISTORY_SENTINEL'}],source:{kind:'user'}})); await agent.whenIdle();
      for (const record of catalog.agents) {
        const before = calls.length;
        const run = await startLinktool('linktool:' + record.name, { parent: agent, signal: new AbortController().signal, prompt: [{ type: 'text', text: 'explicit input only' }] });
        const result = await run.result;
        assert.equal(result.stopReason, 'completed', record.name + ': ' + JSON.stringify(result));
        assert.equal(calls.length, before + 1);
        const captured = JSON.stringify(calls.at(-1));
        const system = calls.at(-1).messages.filter(m=>m.role==='system').flatMap(m=>m.content).map(b=>b.text??'').join('\n');
        assert(system.includes(body(record)), 'exact original role body');
        for(const name of record.skills) assert(system.includes(body(catalog.skills.find(s=>s.name===name))), 'full preload '+name);
        assert(!captured.includes('PARENT_HISTORY_SENTINEL'), 'no inherited parent history');
        assert(captured.includes(body(record).slice(0, 80).replaceAll('\n', '\\n').replaceAll('\r', '\\r').replaceAll('"', '\\"')) || captured.includes(record.name), 'role prompt');
        const names = calls.at(-1).tools.map(t => t.name);
        assert(names.every(n=>n.length<=64), 'DeepSeek tool name limit');
        if(process.env.LINKTOOL_VERIFY_MCP==='1' && record.name==='gis-tool') assert(names.includes('mcp__arcgis-mcp-server__execute_gis_tool'));
        if(record.name==='report'||record.name==='task-plan'||record.name==='data-retrieval') assert(!names.includes('mcp__arcgis-mcp-server__execute_gis_tool'));
        if (record.name === 'report') assert(!names.includes('Agent'));
        if (record.name === 'question-classify') assert(names.includes('Agent'));
        console.log('RUNTIME PASS agent ' + record.name + ', tools=' + names.length);
        await run.dispose();
      }
      const execute = (name, args) => ctx.tools.execute({ callId: randomUUID(), name, arguments: args, agent, signal: new AbortController().signal });
      const before = calls.length;
      const fork = await execute('Skill', { skill: 'data-retrieval', args: 'fork input sentinel' });
      assert(!fork.isError, JSON.stringify(fork)); assert.equal(calls.length, before + 1);
      console.log('RUNTIME PASS fork Skill');
      const inline = await execute('Skill', { skill: 'data-analyzer', args: '' }); assert(!inline.isError, JSON.stringify(inline));
      console.log('RUNTIME PASS inline Skill');
      const read = await execute('Read',{file_path:'plugin/skills/tool-report/formatting-guide.md'}); assert(!read.isError, JSON.stringify(read));
      const shell = await execute('Bash',{command:'officecli --version'}); assert(!shell.isError,JSON.stringify(shell));
      console.log('RUNTIME PASS resource Read + Windows Bash + bundled officecli');
      const path = join(cwd, '02_WorkSpace', 'workflow_script.js');
      writeFileSync(path, 'export const meta = {name:"verify",description:"runtime check"};\nconst value = await agent("workflow sentinel", {agentType:"linktool-plugin:data-retrieval"});\nreturn value;');
      const workflow = await execute('Workflow', { scriptPath: path }); assert(!workflow.isError, JSON.stringify(workflow));
      const callsBeforeResume=calls.length;
      const resumed = await execute('Workflow', { scriptPath: path, resumeFromRunId: workflow.value.runId }); assert(!resumed.isError, JSON.stringify(resumed)); assert.equal(calls.length,callsBeforeResume,'resume must use completed agent cache');
      const rejected = await execute('Workflow', { scriptPath: path, resumeFromRunId: workflow.value.runId }); assert(rejected.isError);
      console.log('RUNTIME PASS Workflow + resume cache + retry limit');
      console.log('LINKTOOL_RUNTIME_OK');
      await handle.dispose();
      process.exit(0);
    } catch (error) { console.error(error); await handle?.dispose(); process.exit(1); }
  }, 1000);
}
