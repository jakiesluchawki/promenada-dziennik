// No school data or report passwords: inspect verified publication steps only.
export const VERIFIED_STEP = 'Verify fresh published report';
const root = 'https://api.github.com/repos/jakiesluchawki/promenada-dziennik/actions';
type Run = { id: number; status: string; conclusion: string | null; created_at: string; path: string; head_branch: string; display_title: string };
export function windowAt(now: Date) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Warsaw', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now).map(p => [p.type, p.value]));
  const minute = Number(p.hour) * 60 + Number(p.minute);
  const start = minute >= 1080 ? 1080 : 390;
  // Three checks, ten minutes apart; two minutes of staggering between profiles.
  if (minute < start || minute > start + 25) return null;
  return { since: now.getTime() - (minute - start) * 60000 - now.getUTCSeconds() * 1000 - now.getUTCMilliseconds(), key: `${p.year}-${p.month}-${p.day}-${start}` };
}
export async function watchdog(profile: 'parent' | 'student', token: string | undefined, fetcher: typeof fetch = fetch, now = new Date()) {
  const slot = windowAt(now);
  if (!slot) return { state: 'outside_window' };
  if (!token?.trim()) throw new Error('Missing dispatch credential');
  const workflow = profile === 'parent' ? 'update.yml' : 'update-student.yml';
  const signal = AbortSignal.timeout(22000); // Entire check fits Netlify's 30s limit.
  const github = async (path: string, body?: object) => {
    const response = await fetcher(root + path, { method: body ? 'POST' : 'GET', signal, redirect: 'error', headers: { Authorization: `Bearer ${token.trim()}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new Error(`GitHub status ${response.status}`);
    return response.status === 204 ? null : response.json();
  };
  const list = await github(`/workflows/${workflow}/runs?branch=main&per_page=100`);
  const runs = (list.workflow_runs as Run[]).filter(r => r.path === `.github/workflows/${workflow}` && r.head_branch === 'main');
  if (runs.some(r => r.status !== 'completed')) return { state: 'running' };
  const recent = runs.filter(r => Date.parse(r.created_at) >= slot.since);
  for (const run of recent.filter(r => r.conclusion === 'success').slice(0, 3)) {
    const result = await github(`/runs/${run.id}/jobs?per_page=100`);
    if (result.jobs.some((job: { steps?: { name: string; conclusion: string }[] }) => job.steps?.some(step => step.name === VERIFIED_STEP && step.conclusion === 'success'))) return { state: 'fresh' };
  }
  const attempts = recent.filter(r => r.display_title?.startsWith('Scheduled report')).length;
  if (attempts >= 3) return { state: 'attempts_exhausted' };
  if (recent.some(r => now.getTime() - Date.parse(r.created_at) < 5 * 60000)) return { state: 'cooldown' };
  await github(`/workflows/${workflow}/dispatches`, { ref: 'main', inputs: { scheduled: 'true' } });
  return { state: 'dispatched', attempt: attempts + 1 };
}
