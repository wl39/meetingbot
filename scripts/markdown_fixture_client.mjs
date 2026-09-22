import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import path from 'node:path';

export function markdownFixtures(root) {
  const process = spawn(path.join(root, 'rag/.venv/bin/python'), [path.join(root, 'scripts/markdown_fixture_render.py')], { stdio: ['pipe', 'pipe', 'pipe'] });
  const pending = new Map();
  let serial = 0, errors = '';
  process.stderr.on('data', chunk => { errors += chunk; });
  createInterface({ input: process.stdout }).on('line', line => {
    const response = JSON.parse(line), task = pending.get(response.id);
    pending.delete(response.id);
    if (response.error) task.reject(new Error(response.error)); else task.resolve(response.result);
  });
  process.on('exit', code => { for (const task of pending.values()) task.reject(new Error(`Renderer fixture exited ${code}: ${errors}`)); });
  function send(value) { return new Promise((resolve, reject) => { const id = ++serial; pending.set(id, { resolve, reject }); process.stdin.write(JSON.stringify({ ...value, id }) + '\n'); }); }
  return {
    add: (name, text) => send({ action: 'add', name, text }),
    render: (name, evidence, query) => send({ action: 'read', name, evidence, options: {
      mode: query.get('view') || 'preview',
      page: query.has('page') ? Number(query.get('page')) : null,
      anchor: query.get('anchor'),
      outline_offset: Number(query.get('outline_offset') || 0),
      source_offset: query.has('source_offset') ? Number(query.get('source_offset')) : null,
    } }),
    close: () => process.stdin.end(),
  };
}
