const {test} = require('node:test');
const assert = require('node:assert/strict');
const deploy = require('../scripts/deploy_pages.cjs');

const id = '14895992168';
const wait = async () => {};
function fixture(responses) {
  const calls = [], outputs = {};
  const github = {request: async (route, params) => {
    calls.push({route, params});
    const value = responses.shift();
    if (value instanceof Error) throw value;
    return {data: value};
  }};
  const core = {getIDToken: async () => 'test-job-token', info() {}, warning() {},
    setOutput: (key, value) => { outputs[key] = value; }};
  const context = {sha: 'test-build', repo: {owner: 'example', repo: 'reports'}};
  return {args: {github, context, core}, calls, outputs};
}
const accepted = {id: 'pages-123', page_url: 'https://example.github.io/reports/'};
const httpError = status => Object.assign(new Error('private request details'), {status});

test('deploys the returned upload ID without listing artifacts; retries only status reads', async () => {
  const {args, calls, outputs} = fixture([accepted, httpError(404), {status: 'queued'}, httpError(503), {status: 'succeed'}]);
  await deploy(args, id, wait);
  assert.deepEqual(calls[0].params, {...args.context.repo, artifact_id: Number(id),
    pages_build_version: 'test-build', oidc_token: 'test-job-token'});
  assert.equal(calls[0].route, 'POST /repos/{owner}/{repo}/pages/deployments');
  assert.ok(calls.slice(1).every(call => call.route === 'GET /repos/{owner}/{repo}/pages/deployments/{deploymentId}' &&
    call.params.deploymentId === accepted.id));
  assert.equal(outputs.page_url, accepted.page_url);
});

test('fails on a missing ID, an uncertain submission, or a failed deployment', async () => {
  const missing = fixture([]);
  await assert.rejects(deploy(missing.args, '', wait), /artifact ID/);
  assert.equal(missing.calls.length, 0);
  const rejected = fixture([httpError(502)]);
  await assert.rejects(deploy(rejected.args, id, wait), {message: 'Could not create the Pages deployment for artifact ' + id + ' (502).'});
  assert.equal(rejected.calls.length, 1);
  const failed = fixture([accepted, {status: 'deployment_content_failed'}]);
  await assert.rejects(deploy(failed.args, id, wait), /deployment_content_failed/);
  assert.deepEqual(failed.outputs, {});
});

test('cancels only its accepted deployment after the poll budget expires', async () => {
  const {args, calls} = fixture([{...accepted, id: null, status_url: 'https://api.github.com/repos/example/reports/pages/deployments/from-url'},
    ...Array(120).fill({status: 'deployment_in_progress'}), {}]);
  await assert.rejects(deploy(args, id, wait), /Timed out/);
  assert.equal(calls.at(-1).route, 'POST /repos/{owner}/{repo}/pages/deployments/{deploymentId}/cancel');
  assert.equal(calls.at(-1).params.deploymentId, 'from-url');
});
