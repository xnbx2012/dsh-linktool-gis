import { spawnSync } from 'node:child_process';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const result = spawnSync('tar', ['-czf', join(root, 'resources-full.tar.gz'), '-C', join(root,'resources'), 'plugin'], {stdio:'inherit', windowsHide:true});
if(result.error) throw result.error;
if(result.status !== 0) throw new Error('资源归档失败，请确认系统 tar 命令可用');
console.log('已归档完整源资源，包括 npm 默认忽略的原始 .venv 文件。');
