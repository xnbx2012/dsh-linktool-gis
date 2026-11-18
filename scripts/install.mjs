import { spawnSync } from 'node:child_process';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const profile = process.argv[2] ?? 'web';
const profileDirectory = join(resolve(process.env.DSH_HOME || join(homedir(), '.dsh')), 'profiles', profile);
if (!/^[a-zA-Z0-9_-]+$/.test(profile)) throw new Error('Profile 名称不合法');
if (profile === 'desktop') throw new Error('desktop 由 Harness 桌面端管理，请使用 web 或自定义 profile');
if (!existsSync(join(root, 'lib/index.js'))) throw new Error('缺少构建产物，请先运行 npm install && npm run build');
if (!existsSync(join(profileDirectory,'package.json'))) {
  const initialize = spawnSync(process.execPath, [join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js'), '--profile', profile, '--from-default-profile', 'web', '--dump-config'], { encoding: 'utf8', windowsHide: true });
  if (initialize.status !== 0) { console.error(initialize.stderr); process.exit(initialize.status ?? 1); }
}
const result = spawnSync(process.execPath, [join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js'), 'plugin', '--profile', profile, 'add', '--force', 'file:' + root], { stdio: 'inherit', windowsHide: true });
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
if (!process.exitCode) {
  const installed = join(profileDirectory, 'node_modules', '@linktool', 'dsh-plugin');
  // pnpm can retain an earlier file: directory enumeration even after --force.
  // Synchronize the package's explicit payload so new docs/scripts are included.
  const manifest = JSON.parse(readFileSync(join(root,'package.json'),'utf8'));
  const sync = (source, destination) => {
    if (source === destination) return;
    try {
      const entries = readdirSync(source,{withFileTypes:true});
      mkdirSync(destination,{recursive:true});
      for (const entry of entries) sync(join(source,entry.name),join(destination,entry.name));
    } catch (error) {
      if(error.code !== 'ENOTDIR') throw error;
      const bytes = readFileSync(source);
      if (existsSync(destination) && bytes.equals(readFileSync(destination))) return;
      mkdirSync(dirname(destination),{recursive:true}); writeFileSync(destination,bytes);
    }
  };
  for (const entry of [...manifest.files,'package.json']) {
    if (entry === 'resources') continue; // restore every source byte from the archive below
    if (existsSync(join(root,entry))) sync(join(root,entry),join(installed,entry));
  }
  const restore = spawnSync(process.execPath, [join(root,'scripts/restore-resources.mjs'),installed], {stdio:'inherit',windowsHide:true});
  if (restore.status !== 0) { process.exitCode = restore.status ?? 1; }
  else console.log(`安装完成。请使用 DSH >=0.2.1-rc.5 启动（如 npx @deepseek-ai/dsh@latest --profile ${profile}）。\n注意：0.2.0-rc.2 等旧版 DSH 无法加载本插件；若 web 端插件管理器"再次安装"报"无法从依赖变更中确定安装了哪一个包"，请先升级 DSH，或改用本脚本/命令行更新。`);
}
