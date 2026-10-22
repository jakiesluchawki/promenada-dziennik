import test from 'node:test';
import assert from 'node:assert/strict';
import { watchdog, windowAt, VERIFIED_STEP } from '../lib/watchdog.mts';
import { config as parentSchedule } from '../netlify/functions/morning-parent.mts';
import { config as studentSchedule } from '../netlify/functions/morning-student.mts';
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
  for (const timestamp of ['2026-09-12T05:30:00Z', '2026-12-12T06:30:00Z', '2026-09-12T17:02:00Z', '2026-12-12T18:02:00Z']) assert.ok(windowAt(new Date(timestamp)), timestamp);
  for (const timestamp of ['2026-09-12T04:29:00Z', '2026-09-12T05:36:00Z', '2026-09-12T09:30:00Z', '2026-09-12T17:06:00Z']) assert.equal(windowAt(new Date(timestamp)), null);
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
test('local workflow and branch filtering suppresses duplicates when the upstream branch filter returns no runs', async () => {
  for (const profile of ['parent', 'student'] as const) {
    const path = `.github/workflows/${profile === 'parent' ? 'update.yml' : 'update-student.yml'}`;
    const calls: string[] = [];
    const fetcher = (async (url, options) => {
      assert.equal(options?.method, 'GET');
      const address = String(url); calls.push(address);
      return Response.json(address.includes('/jobs?') ? { jobs: [{ steps: [{ name: VERIFIED_STEP, conclusion: 'success' }] }] } : { workflow_runs: address.includes('branch=') ? [] : [
        run(3, { path, head_branch: 'feature', status: 'in_progress' }),
        run(2, { path: '.github/workflows/unrelated.yml', status: 'in_progress' }), run(1, { path }),
      ] });
    }) as typeof fetch;
    assert.equal((await watchdog(profile, 'fixture', fetcher, now)).state, 'fresh');
    assert.ok(calls.at(-1)?.includes('/runs/1/jobs?'));
  }
});
test('yesterday verified publication cannot satisfy this morning', async () => {
  const f = mock([run(1, { created_at: '2026-09-11T16:00:00Z' })], 'success'); assert.equal((await watchdog('parent', 'fixture', f.fetcher, now)).state, 'dispatched');
});
test('running jobs, cooldown and four attempts bound retries', async () => {
  for (const [runs, expected] of [[ [run(1, { status: 'queued' })], 'running'], [[run(1, { created_at: '2026-09-12T04:39:00Z' })], 'cooldown'], [[run(1), run(2), run(3), run(4)], 'attempts_exhausted']] as const) {
    const f = mock([...runs]); assert.equal((await watchdog('parent', 'fixture', f.fetcher, now)).state, expected); assert.ok(f.calls.every(c => !c.body));
  }
});
test('three failures wait quietly until the delayed recovery, for both profiles', async () => {
  for (const profile of ['parent', 'student'] as const) {
    const path = profile === 'parent' ? '.github/workflows/update.yml' : '.github/workflows/update-student.yml';
    const runs = [0, 10, 20].map((minute, index) => run(index + 1, { path, conclusion: 'failure', created_at: `2026-09-12T04:${30 + minute}:00Z` }));
    const waiting = mock(runs);
    assert.equal((await watchdog(profile, 'fixture', waiting.fetcher, new Date('2026-09-12T05:20:00Z'))).state, 'recovery_wait');
    assert.ok(waiting.calls.every(c => !c.body));
    const recovery = mock(runs);
    const result = await watchdog(profile, 'fixture', recovery.fetcher, new Date('2026-09-12T05:32:00Z'));
    assert.deepEqual(result, { state: 'dispatched', attempt: 4 });
    assert.equal(recovery.calls.filter(c => c.body).length, 1);
    const exhausted = mock([...runs, run(4, { path, conclusion: 'failure', created_at: '2026-09-12T05:30:00Z' })]);
    assert.equal((await watchdog(profile, 'fixture', exhausted.fetcher, new Date('2026-09-12T05:35:00Z'))).state, 'attempts_exhausted');
    assert.ok(exhausted.calls.every(c => !c.body));
  }
});
test('a healthy manual recovery suppresses the extra scheduled read', async () => {
  const f = mock([run(1), run(2), run(3), run(4, { display_title: 'Manual report', created_at: '2026-09-12T05:25:00Z' })], 'success');
  assert.equal((await watchdog('parent', 'fixture', f.fetcher, new Date('2026-09-12T05:30:00Z'))).state, 'fresh');
  assert.ok(f.calls.every(c => !c.body));
});
test('configured UTC schedules include the delayed recovery in summer and winter', () => {
  for (const [config, minute, hour] of [[parentSchedule, 30, 5], [parentSchedule, 30, 6], [parentSchedule, 0, 17], [parentSchedule, 0, 18], [studentSchedule, 32, 5], [studentSchedule, 32, 6], [studentSchedule, 2, 17], [studentSchedule, 2, 18]] as const) {
    const [minutes, hours] = config.schedule.split(' ');
    assert.ok(minutes.split(',').map(Number).includes(minute));
    assert.ok(hours.split(',').map(Number).includes(hour));
  }
});
test('API failure never dispatches blindly', async () => {
  let calls = 0;
  await assert.rejects(watchdog('parent', 'fixture', (async () => { calls++; return new Response(null, { status: 503 }); }) as typeof fetch, now));
  assert.equal(calls, 2);
});
test('a current verification receipt suppresses retries when steps are missing', async () => {
  const calls: { url: string; method?: string }[] = [];
  const fetcher = (async (url, options) => {
    calls.push({ url: String(url), method: options?.method });
    return Response.json(String(url).includes('/jobs?') ? { jobs: [] } : String(url).includes('/artifacts?') ? {
      artifacts: [{ name: 'mahbrus-verified-publication-v1-1', expired: false, size_in_bytes: 250 }],
    } : { workflow_runs: [run(1)] });
  }) as typeof fetch;
  assert.equal((await watchdog('parent', 'fixture', fetcher, now)).state, 'fresh');
  assert.ok(calls.every(call => call.method === 'GET'));
});
