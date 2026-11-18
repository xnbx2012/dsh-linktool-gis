import { spawnSync } from 'node:child_process';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
// -f 用裸文件名（cwd=仓库根）：GNU tar 会把 `-f C:\...` 的盘符当远程主机名
//（"Cannot connect to C: resolve failed"），System32 bsdtar 无此问题但 PATH 里
// 通常是 Git Bash 的 GNU tar，两种环境都要能跑。
const result = spawnSync('tar', ['-czf', 'resources-full.tar.gz', '-C', join(root, 'resources'), 'plugin'], { cwd: root, stdio: 'inherit', windowsHide: true });
if(result.error) throw result.error;
if(result.status !== 0) throw new Error('资源归档失败，请确认系统 tar 命令可用');
console.log('已归档完整源资源，包括 npm 默认忽略的原始 .venv 文件。');
