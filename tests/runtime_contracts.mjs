import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { runTask } from '../runtime/loop.mjs';

async function scenario(run) {
  const folder = await mkdtemp(path.join(tmpdir(), 'ocu-delivery-'));
  const helper = path.join(folder, 'decider');
  const decision = { operation: 'TYPE_TEXT', index: '2', secure: true,
    text: 'synthetic-secret', risk: 0, confidence: 1, label: 'Password' };
  await writeFile(helper, `#!/usr/bin/env node
const readline = require('node:readline');
let step = 0;
readline.createInterface({input:process.stdin}).on('line', () => {
  console.log(JSON.stringify(++step === 1 ? ${JSON.stringify(decision)} : {operation:'DONE',risk:0}));
});
`, { mode: 0o700 });
  try { await run(helper); } finally { await rm(folder, { recursive: true }); }
}

test('an error after executor dispatch never becomes a safe refusal or a second write', async () => {
  await scenario(async (python) => {
    let writes = 0;
    const sky = {
      get_app_state: async () => ({ text: '1 text field Password' }),
      set_value: async () => { writes++; throw new Error('reply lost after dispatch'); },
    };
    const result = await runTask({ sky, app: 'Scratch', goal: 'Edit password', python,
      dryRun: false, emit: () => {} });
    assert.equal(result.status, 'blocked');
    assert.equal(writes, 1);
    assert.equal(result.history[0].disposition.delivery, 'delivery_uncertain');
    assert.equal(result.history[0].disposition.retry, 'unsafe');
    assert.ok(!JSON.stringify(result).includes('synthetic-secret'));
  });
});

test('post-dispatch observation failure retains unverified delivery without leaking text', async () => {
  await scenario(async (python) => {
    let reads = 0, writes = 0;
    const sky = {
      get_app_state: async () => {
        if (reads++) throw new Error('app stopped answering');
        return { text: '1 text field Password' };
      },
      set_value: async () => { writes++; },
    };
    const result = await runTask({ sky, app: 'Scratch', goal: 'Edit password', python,
      dryRun: false, emit: () => {} });
    assert.equal(result.status, 'blocked');
    assert.equal(writes, 1);
    assert.equal(result.history[0].disposition.delivery, 'delivered_unverified');
    assert.ok(!JSON.stringify(result).includes('synthetic-secret'));
  });
});
