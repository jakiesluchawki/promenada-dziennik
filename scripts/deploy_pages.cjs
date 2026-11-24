const {setTimeout: sleep} = require('node:timers/promises');

const deployments = '/repos/{owner}/{repo}/pages/deployments';
const terminalErrors = new Set([
  'deployment_failed', 'deployment_perms_error', 'deployment_content_failed',
  'deployment_cancelled', 'deployment_lost',
]);

// The upload returns an immutable ID before Actions' artifact list necessarily contains it.
module.exports = async function deployPages({github, context, core}, artifactId, wait = sleep) {
  if (!/^[1-9]\d*$/.test(artifactId) || !Number.isSafeInteger(Number(artifactId))) {
    throw new Error('The Pages upload did not return a valid artifact ID.');
  }
  const repo = context.repo;
  const oidc = await core.getIDToken();
  let created;
  try {
    ({data: created} = await github.request('POST ' + deployments, {
      ...repo, artifact_id: Number(artifactId), pages_build_version: context.sha, oidc_token: oidc,
    }));
  } catch (error) {
    // Do not log the request body, which contains the job's OIDC credential.
    throw new Error('Could not create the Pages deployment for artifact ' + artifactId +
      ' (' + (error.status || 'network error') + ').');
  }

  const deploymentId = created.id || created.status_url?.split('/').pop() || context.sha;
  const params = {...repo, deploymentId};
  const endpoint = deployments + '/{deploymentId}';
  core.info('Publishing artifact ' + artifactId + ' with Pages deployment ' + deploymentId);
  let active = true;
  async function cancel() {
    if (!active) return;
    active = false;
    try { await github.request('POST ' + endpoint + '/cancel', params); }
    catch (error) { core.warning('Could not cancel the Pages deployment (' + (error.status || 'network error') + ').'); }
  }
  const onSignal = () => { cancel().finally(() => process.exit(1)); };
  process.once('SIGINT', onSignal);
  process.once('SIGTERM', onSignal);
  const deadline = Date.now() + 600_000;
  try {
    for (let poll = 0; poll < 120 && Date.now() < deadline; poll++) {
      await wait(5_000);
      let state;
      try {
        const {data} = await github.request('GET ' + endpoint, params);
        state = data.status;
      } catch (error) {
        if (!error.status || error.status === 404 || error.status === 429 || error.status >= 500) continue;
        throw new Error('Could not check the Pages deployment (' + error.status + ').');
      }
      if (state === 'succeed') {
        active = false;
        core.setOutput('page_url', created.page_url);
        return;
      }
      if (terminalErrors.has(state)) {
        active = false;
        throw new Error('Pages reported ' + state + '.');
      }
    }
    throw new Error('Timed out waiting for the Pages deployment.');
  } finally {
    process.removeListener('SIGINT', onSignal);
    process.removeListener('SIGTERM', onSignal);
    await cancel();
  }
};
