#!/usr/bin/env node
import fs from 'fs/promises';
import path from 'path';
import yaml from 'js-yaml';

async function main(){
  const cwd = process.cwd();
  const srcAssetsDir = path.resolve(cwd, 'assets', 'edu', 'v1');
  const outDir = path.resolve(cwd, 'src', 'generated', 'assets', 'edu', 'v1');
  await fs.mkdir(outDir, { recursive: true });

  const manifestPath = path.join(srcAssetsDir, 'manifest.yaml');
  const raw = await fs.readFile(manifestPath, 'utf8');
  const manifest = yaml.load(raw);

  // copy files listed in manifest into src/generated/assets/... and build TS manifest
  const imports = [];
  const mappings = [];

  for (const [key, info] of Object.entries(manifest.assets || {})){
    const rel = info.path;
    const srcPath = path.join(srcAssetsDir, rel);
    const destPath = path.join(outDir, rel);
    await fs.mkdir(path.dirname(destPath), { recursive: true });
    await fs.copyFile(srcPath, destPath);
    // create import variable name safe
    const varName = key.replace(/[^a-z0-9_]/gi, '_');
    const importPath = `./${rel.replace(/\\/g, '/')}';`;
    // We'll write imports as: import X from './assets/edu/v1/...'
    imports.push({varName, relPath: `./${path.posix.join('assets','edu','v1', rel)}`});
    mappings.push({key, varName, info});
  }

  // generate TS manifest file under src/generated/assets-manifest.ts
  const manifestTsPath = path.resolve(cwd, 'src', 'generated', 'assets-manifest.ts');
  const lines = [];
  // import assets
  for (const imp of imports){
    lines.push(`import ${imp.varName} from '${imp.relPath}';`);
  }
  lines.push('');
  lines.push('export const assets = {');
  for (const m of mappings){
    lines.push(`  "${m.key}": { file: ${m.varName}, type: "${m.info.type}", format: "${m.info.format}", supported_states: ${JSON.stringify(m.info.supported_states || [])} },`);
  }
  lines.push('};');
  await fs.writeFile(manifestTsPath, lines.join('\n'), 'utf8');

  console.log(`Wrote ${manifestTsPath}`);
}

main().catch((err)=>{console.error(err); process.exit(1);});
