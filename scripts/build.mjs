import { build } from 'esbuild';
await build({ entryPoints: ['src/index.ts', 'src/catalog.ts', 'src/tools.ts', 'src/hooks.ts', 'src/workflow.ts', 'src/paths.ts', 'src/mcp.ts'], outdir: 'lib', bundle: true, format: 'esm', platform: 'node', target: 'node22', sourcemap: true, external: ['@deepseek-ai/*', 'typescript'], banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);" } });
console.log('Built lib/index.js for dsh 0.2.1-rc.5');
