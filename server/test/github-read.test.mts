import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchGitHub } from '../lib/github-read.mts';

test('a transient metadata error is retried once within the same deadline', async () => {
  const signal = AbortSignal.timeout(2000);
  const options = { method: 'GET', signal, redirect: 'error' as const };
  const calls: RequestInit[] = [];
  const fetcher = (async (_url, init) => {
    calls.push(init!);
    return new Response('', { status: calls.length === 1 ? 502 : 200 });
  }) as typeof fetch;
  assert.equal((await fetchGitHub('https://api.github.com/synthetic', options, fetcher)).status, 200);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(call => call === options && call.signal === signal));
});
test('persistent metadata failures stop after the second response', async () => {
  let calls = 0;
  const fetcher = (async () => { calls++; return new Response('', { status: 503 }); }) as typeof fetch;
  assert.equal((await fetchGitHub('https://api.github.com/synthetic', { method: 'GET' }, fetcher)).status, 503);
  assert.equal(calls, 2);
});
test('dispatch POST and permission/rate-limit failures are not replayed', async () => {
  for (const [method, status] of [['POST', 502], ['GET', 401], ['GET', 403], ['GET', 429]] as const) {
    let calls = 0;
    const fetcher = (async () => { calls++; return new Response('', { status }); }) as typeof fetch;
    assert.equal((await fetchGitHub('https://api.github.com/synthetic', { method }, fetcher)).status, status);
    assert.equal(calls, 1);
  }
});
test('an aborted shared deadline prevents a retry', async () => {
  const controller = new AbortController();
  let calls = 0;
  const fetcher = (async () => { calls++; controller.abort(); return new Response('', { status: 504 }); }) as typeof fetch;
  await fetchGitHub('https://api.github.com/synthetic', { method: 'GET', signal: controller.signal }, fetcher);
  assert.equal(calls, 1);
});
