import test from 'node:test';
import assert from 'node:assert/strict';
import { publicationVerified, RECEIPT_PREFIX, VERIFIED_STEP } from '../lib/publication.mts';

test('a verified step needs no receipt lookup', async () => {
  const calls: string[] = [];
  const github = async (path: string) => {
    calls.push(path);
    return { jobs: [{ steps: [{ name: VERIFIED_STEP, conclusion: 'success' }] }] };
  };
  assert.equal(await publicationVerified(github, { id: 25 }), true);
  assert.equal(calls.length, 1);
});
test('a receipt verifies missing steps only for this exact run attempt', async () => {
  const calls: string[] = [];
  const github = async (path: string) => {
    calls.push(path);
    return path.includes('/jobs?') ? { jobs: [{ steps: [] }] } : {
      artifacts: [{ name: RECEIPT_PREFIX + '2', expired: false, size_in_bytes: 250 }],
    };
  };
  assert.equal(await publicationVerified(github, { id: 25, run_attempt: 2 }), true);
  assert.deepEqual(calls, ['/runs/25/jobs?per_page=100&filter=latest', '/runs/25/artifacts?per_page=100']);
  assert.equal(await publicationVerified(github, { id: 25, run_attempt: 1 }), false);
});
test('expired, oversized, unrelated and older-attempt artifacts do not certify publication', async () => {
  for (const artifact of [
    { name: 'github-pages', expired: false, size_in_bytes: 250 },
    { name: RECEIPT_PREFIX + '1', expired: true, size_in_bytes: 250 },
    { name: RECEIPT_PREFIX + '1', expired: false, size_in_bytes: 4097 },
    { name: RECEIPT_PREFIX + '1', expired: false, size_in_bytes: 0 },
    { name: RECEIPT_PREFIX + '2', expired: false, size_in_bytes: 250 },
  ]) {
    const github = async (path: string) => path.includes('/jobs?') ? { jobs: [] } : { artifacts: [artifact] };
    assert.equal(await publicationVerified(github, { id: 25, run_attempt: 1 }), false);
  }
});
test('an explicitly skipped or failed verification cannot be overridden by an artifact', async () => {
  for (const conclusion of ['skipped', 'failure']) {
    let calls = 0;
    const github = async () => {
      calls++;
      return { jobs: [{ steps: [{ name: VERIFIED_STEP, conclusion }] }] };
    };
    assert.equal(await publicationVerified(github, { id: 25 }), false);
    assert.equal(calls, 1);
  }
});
test('absent proof and invalid attempts cannot turn success into verified freshness', async () => {
  const github = async () => ({ jobs: [] });
  for (const run_attempt of [0, -1, 1.5, Infinity]) {
    assert.equal(await publicationVerified(github, { id: 25, run_attempt }), false);
  }
  assert.equal(await publicationVerified(github, { id: 25 }), false);
});
