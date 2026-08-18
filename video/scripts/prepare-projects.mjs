#!/usr/bin/env node
import fs from 'fs/promises';
import path from 'path';
import yaml from 'js-yaml';

async function main() {
  const cwd = process.cwd();
  const projectsDir = path.resolve(cwd, 'projects');
  const outDir = path.resolve(cwd, 'src', 'generated');
  await fs.mkdir(outDir, { recursive: true });

  const entries = await fs.readdir(projectsDir);
  const projects = [];

  for (const entry of entries) {
    if (!entry.endsWith('.yaml') && !entry.endsWith('.yml')) continue;
    const filePath = path.join(projectsDir, entry);
    const raw = await fs.readFile(filePath, 'utf8');
    const parsed = yaml.load(raw);

    if (!parsed || typeof parsed !== 'object') {
      console.warn(`Skipping ${entry}: not an object`);
      continue;
    }

    const p = /** @type {any} */ (parsed);

    // Minimal validation
    if (!p.id) throw new Error(`${entry}: missing id`);
    if (!p.kind) throw new Error(`${entry}: missing kind`);
    if (!p.title) throw new Error(`${entry}: missing title`);
    if (typeof p.duration_seconds !== 'number') throw new Error(`${entry}: missing duration_seconds (number)`);
    if (!Array.isArray(p.scenes)) throw new Error(`${entry}: missing scenes (array)`);

    // Normalization
    p.fps = p.fps || 30;

    projects.push(p);
  }

  projects.sort((a, b) => (a.id || '').localeCompare(b.id || ''));

  const outPath = path.join(outDir, 'projects.json');
  await fs.writeFile(outPath, JSON.stringify(projects, null, 2) + '\n', 'utf8');
  console.log(`Wrote ${outPath} (${projects.length} project(s))`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
