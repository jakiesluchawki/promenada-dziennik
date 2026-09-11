import test from 'node:test';
import assert from 'node:assert/strict';
import { watchdog, windowAt, VERIFIED_STEP } from '../lib/watchdog.mts';
const now = new Date('2026-09-12T04:40:00Z');
const run = (id: number, extra = {}) => ({ id, status: 'completed', conclusion: 'success', created_at: '2026-09-12T04:30:00Z', path: '.github/workflows/update.yml', head_branch: 'main', display_title: 'Scheduled report', ...extra });
function mock(runs: object[], step = 'skipped') {
  const calls: { url: string; body?: object }[] = [];
  return { calls, fetcher: (async (url, options) => {
    calls.push({ url: String(url), body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (options?.method === 'POST') return new Response(null, { status: 204 });
    return Response.json(String(url).includes('/jobs?') ? { jobs: [{ steps: [{ name: VERIFIED_STEP, conclusion: step }] }] } : { workflow_runs: runs });
  }) as typeof fetch };
}
test('Warsaw windows follow winter and summer time, including DST transitions', () => {
  for (const timestamp of ['2026-09-12T04:30:00Z', '2026-12-12T05:30:00Z', '2027-03-28T04:30:00Z', '2026-10-25T05:30:00Z', '2026-09-12T16:22:00Z']) assert.ok(windowAt(new Date(timestamp)), timestamp);
  for (const timestamp of ['2026-09-12T04:29:00Z', '2026-09-12T04:56:00Z', '2026-09-12T09:30:00Z', '2026-09-12T17:00:00Z']) assert.equal(windowAt(new Date(timestamp)), null);
});
test('outside window makes no network requests', async () => {
  const f = mock([]); assert.equal((await watchdog('parent', undefined, f.fetcher, new Date('2026-09-12T10:00:00Z'))).state, 'outside_window'); assert.equal(f.calls.length, 0);
});
test('a missing report dispatches only the selected workflow with scheduled guard', async () => {
  const f = mock([]); assert.equal((await watchdog('student', 'fixture', f.fetcher, now)).state, 'dispatched');
  assert.ok(f.calls.every(c => c.url.includes('/update-student.yml/')));
  assert.deepEqual(f.calls.at(-1)?.body, { ref: 'main', inputs: { scheduled: 'true' } });
});
test('workflow success with skipped publication is not proof of freshness', async () => {
  const f = mock([run(1)]); assert.equal((await watchdog('parent', 'fixture', f.fetcher, now)).state, 'dispatched');
});
test('verified fresh publication, including manual, prevents another collection', async () => {
  const f = mock([run(1, { display_title: 'Manual report' })], 'success'); assert.equal((await watchdog('parent', 'fixture', f.fetcher, now)).state, 'fresh'); assert.ok(f.calls.every(c => !c.body));
});
test('yesterday verified publication cannot satisfy this morning', async () => {
  const f = mock([run(1, { created_at: '2026-09-11T16:00:00Z' })], 'success'); assert.equal((await watchdog('parent', 'fixture', f.fetcher, now)).state, 'dispatched');
});
test('running jobs, cooldown and three attempts bound retries', async () => {
  for (const [runs, expected] of [[ [run(1, { status: 'queued' })], 'running'], [[run(1, { created_at: '2026-09-12T04:39:00Z' })], 'cooldown'], [[run(1), run(2), run(3)], 'attempts_exhausted']] as const) {
    const f = mock([...runs]); assert.equal((await watchdog('parent', 'fixture', f.fetcher, now)).state, expected); assert.ok(f.calls.every(c => !c.body));
  }
});
test('API failure never dispatches blindly', async () => {
  let calls = 0;
  await assert.rejects(watchdog('parent', 'fixture', (async () => { calls++; return new Response(null, { status: 503 }); }) as typeof fetch, now));
  assert.equal(calls, 1);
});
