import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client';
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio';
import { resolvedServers } from '../lib/mcp.js';
import { packageRoot } from '../lib/catalog.js';
import { join } from 'node:path';
import { mkdirSync, writeFileSync } from 'node:fs';
const reports = [];
await Promise.all(Object.entries(resolvedServers()).map(async ([name, config]) => {
  const client = new Client({name:'linktool-migration-check',version:'1.0.0'});
  const transport = config.transport === 'stdio' ? new StdioClientTransport({command:config.command,args:config.args,cwd:config.cwd,env:config.env,stderr:'pipe'}) : new StreamableHTTPClientTransport(new URL(config.url), { requestInit:{headers:config.headers} });
  transport.stderr?.on('data', () => {});
  let timer;
  try {
    await Promise.race([(async()=>{await client.connect(transport);return client.listTools();})(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('连接或依赖准备超过 45 秒')),45000);})]);
    const result = await client.listTools(); reports.push({name,ok:true,tools:result.tools.map(t=>t.name)}); console.log(`PASS ${name}: ${result.tools.length} tools`);
  } catch (error) {
    const message=String(error.message).replace(/(?:https?:\/\/)[^\s]+/g,'[endpoint]').slice(0,220); reports.push({name,ok:false,error:message});console.log(`FAIL ${name}: ${message}`);
  } finally {clearTimeout(timer);await client.close().catch(()=>{});}
}));
mkdirSync(join(packageRoot,'.runtime'),{recursive:true});writeFileSync(join(packageRoot,'.runtime','mcp-check.json'),JSON.stringify(reports,null,2));
if(reports.some(r=>!r.ok)) process.exitCode=1;
