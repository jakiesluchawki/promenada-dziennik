import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { handle } from '../lib/refresh.mts';
const parent = 'p'.repeat(43), student = 's'.repeat(43);
const hash = (v: string) => createHash('sha256').update(v).digest('hex');
const env = { githubToken: 'server-only-fixture', parentHash: hash(parent), studentHash: hash(student) };
const request = (token: string, method = 'POST', query = '') => new Request('https://mahbrus-refresh.netlify.app/api/refresh' + query, { method, headers: { Authorization: 'Bearer ' + token } });
function fake(runs: object[] = [], failure = false) {
  const calls: { url: string, options: RequestInit | undefined }[] = [];
  const fetcher = (async (url, options) => {
    calls.push({ url: String(url), options });
    if (failure) return new Response('', { status: 403 });
    return options?.method === 'POST' ? new Response(null, { status: 204 }) : String(url).includes('/jobs?') ? Response.json({ jobs: [{ steps: [{ name: 'Verify fresh published report', conclusion: 'success' }] }] }) : Response.json({ workflow_runs: runs });
  }) as typeof fetch;
  return { calls, fetcher };
}
test('unauthorized callers never reach GitHub', async () => {
  const f = fake(); assert.equal((await handle(request('x'.repeat(43)), env, f.fetcher)).status, 401); assert.equal(f.calls.length, 0);
});
test('student can dispatch only student workflow and main', async () => {
  const f = fake(); const res = await handle(request(student, 'POST', '?workflow=update.yml&ref=other'), env, f.fetcher);
  assert.equal(res.status, 202); assert.equal(f.calls.length, 2);
  assert.ok(f.calls.every(c => c.url.includes('/update-student.yml/')));
  assert.deepEqual(JSON.parse(String(f.calls[1].options?.body)), { ref: 'main' });
  assert.ok(!JSON.stringify(await res.json()).includes(env.githubToken));
});
test('parent dispatch remains separate', async () => {
  const f = fake(); await handle(request(parent), env, f.fetcher); assert.ok(f.calls[1].url.endsWith('/update.yml/dispatches'));
});
test('active or recent run prevents another dispatch', async () => {
  for (const status of ['in_progress', 'completed']) {
    const f = fake([{ id: 12, status, conclusion: 'success', created_at: new Date().toISOString(), head_branch: 'main', path: '.github/workflows/update-student.yml' }]);
    const res = await handle(request(student), env, f.fetcher); assert.equal(f.calls.length, 1); assert.ok(['running', 'cooldown'].includes((await res.json()).state));
  }
});
test('failure does not become a false success or disclose GitHub errors', async () => {
  const f = fake([], true); assert.equal((await handle(request(student), env, f.fetcher)).status, 503);
});
test('polling stays scoped and never dispatches', async () => {
  const f = fake([{ id: 25, status: 'completed', conclusion: 'success', created_at: new Date().toISOString(), head_branch: 'main', path: '.github/workflows/update-student.yml' }]);
  assert.equal((await (await handle(request(student, 'GET', '?run=after:20'), env, f.fetcher)).json()).state, 'complete');
  assert.equal(f.calls.length, 2);
});
test('polling finds real main runs despite the upstream branch-filter bug, keeping profile and ref isolation', async () => {
  for (const token of [parent, student]) {
    const workflow = token === parent ? 'update.yml' : 'update-student.yml';
    const other = token === parent ? 'update-student.yml' : 'update.yml';
    const base = { status: 'completed', conclusion: 'success', created_at: new Date().toISOString(), head_branch: 'main', path: `.github/workflows/${workflow}` };
    const calls: string[] = [];
    const fetcher = (async (url, options) => {
      assert.equal(options?.method, 'GET');
      const path = String(url); calls.push(path);
      return Response.json(path.includes('/jobs?') ? { jobs: [{ steps: [{ name: 'Verify fresh published report', conclusion: 'success' }] }] } : { workflow_runs: path.includes('branch=') ? [] : [
        { ...base, id: 27, path: `.github/workflows/${other}` },
        { ...base, id: 26, head_branch: 'feature' }, { ...base, id: 25 },
      ] });
    }) as typeof fetch;
    for (const [id, state] of [[25, 'complete'], [26, 'queued'], [27, 'queued']] as const) {
      assert.equal((await (await handle(request(token, 'GET', `?run=${id}`), env, fetcher)).json()).state, state);
    }
    assert.ok(calls.filter(url => url.includes('/jobs?')).every(url => url.includes('/runs/25/')));
  }
});
test('skipped collection cannot claim a freshly published report', async () => {
  const fetcher = (async (url) => Response.json(String(url).includes('/jobs?') ? { jobs: [{ steps: [{ name: 'Verify fresh published report', conclusion: 'skipped' }] }] } : { workflow_runs: [{ id: 25, status: 'completed', conclusion: 'success', created_at: new Date().toISOString(), head_branch: 'main', path: '.github/workflows/update-student.yml' }] })) as typeof fetch;
  assert.equal((await (await handle(request(student, 'GET', '?run=25'), env, fetcher)).json()).state, 'cooldown');
});
test('a current receipt completes a student refresh when GitHub omits job steps', async () => {
  const calls: string[] = [];
  const fetcher = (async (url, options) => {
    assert.notEqual(options?.method, 'POST');
    const path = String(url); calls.push(path);
    return Response.json(path.includes('/jobs?') ? { jobs: [{ steps: [] }] } : path.includes('/artifacts?') ? {
      artifacts: [{ name: 'mahbrus-verified-publication-v1-1', expired: false, size_in_bytes: 250 }],
    } : { workflow_runs: [{ id: 25, run_attempt: 1, status: 'completed', conclusion: 'success', created_at: new Date().toISOString(), head_branch: 'main', path: '.github/workflows/update-student.yml' }] });
  }) as typeof fetch;
  assert.equal((await (await handle(request(student, 'GET', '?run=25'), env, fetcher)).json()).state, 'complete');
  assert.ok(calls[0].includes('/update-student.yml/'));
  assert.ok(calls.slice(1).every(url => url.includes('/runs/25/')));
});
