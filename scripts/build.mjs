import { build } from 'esbuild';
import { readFileSync, writeFileSync } from 'node:fs';
await build({ entryPoints: ['src/index.ts', 'src/catalog.ts', 'src/tools.ts', 'src/hooks.ts', 'src/workflow.ts', 'src/paths.ts', 'src/mcp.ts', 'src/guard.ts'], outdir: 'lib', bundle: true, format: 'esm', platform: 'node', target: 'node22', sourcemap: true, external: ['@deepseek-ai/*', 'typescript'], banner: { js: "import { createRequire as __createRequire } from 'node:module'; const require = __createRequire(import.meta.url);" } });
// Browser bundle: classic-script CJS factory under window.__ModuleLoader__, with
// every platform seed word kept external (react, cordis, slots, primitives, store).
await build({ entryPoints: ['client/settings-page.tsx'], outfile: 'lib/client.js', bundle: true, format: 'cjs', platform: 'browser', target: 'es2022', jsx: 'automatic', sourcemap: true, external: ['react', 'react/jsx-runtime', 'react-dom', '@deepseek-ai/*'], logLevel: 'silent' });
const body = readFileSync('lib/client.js', 'utf8');
// esbuild emits ESM-style imports when external; convert to the module-table require shape.
const lines = body.split('\n');
const imports = lines.filter(l => /^import\s/.test(l));
const rest = lines.filter(l => !/^import\s/.test(l)).join('\n');
const requireLines = imports.map(line => {
  const match = /import\s+(?:(\w+)\s*,\s*)?(?:(\{[^}]*\})|\*\s+as\s+(\w+)|(\w+))?\s*from\s*['"]([^'"]+)['"];?/.exec(line);
  if (!match) throw new Error('client bundle: unsupported import line: ' + line);
  const [, defaultName, named, star, bare, source] = match;
  const specs = [`let __client_import = require(${JSON.stringify(source)});`];
  if (defaultName || star) specs.push(`let ${defaultName ?? star} = __client_import;`);
  if (named) specs.push(`let ${named} = __client_import;`);
  if (bare) specs.push(`let ${bare} = __client_import;`);
  return specs.join('\n');
});
const banner = `window.__ModuleLoader__.load({\n\tid: "@linktool/dsh-plugin",\n\tfactory: (require) => {\n\t\tvar module = { exports: {} };\n\t\tvar exports = module.exports;\n\t\tObject.defineProperty(exports, Symbol.toStringTag, { value: "Module" });\n`;
const footer = `\n\t\treturn { apply: module.exports.apply, inject: module.exports.inject };\n\t}\n});\n//# sourceMappingURL=client.js.map`;
writeFileSync('lib/client.js', banner + (requireLines.length ? requireLines.join('\n') + '\n' : '') + rest + footer);
console.log('Built lib/index.js and lib/client.js for dsh 0.2.1-rc.5');
