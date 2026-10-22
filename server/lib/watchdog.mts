// No school data or report passwords: inspect verified steps or their receipt.
import { publicationVerified } from './publication.mts';
import { fetchGitHub } from './github-read.mts';
export { VERIFIED_STEP } from './publication.mts';
// Keep the normal two collection slots. One delayed recovery covers outages
// longer than the original twenty-minute retry window, without frequent polling.
export const ATTEMPT_OFFSETS = [0, 10, 20, 60] as const;
const root = 'https://api.github.com/repos/jakiesluchawki/promenada-dziennik/actions';
type Run = { id: number; run_attempt?: number; status: string; conclusion: string | null; created_at: string; path: string; head_branch: string; display_title: string };
export function windowAt(now: Date) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Warsaw', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now).map(p => [p.type, p.value]));
  const minute = Number(p.hour) * 60 + Number(p.minute);
  const start = minute >= 1080 ? 1080 : 390;
  // Five minutes of scheduling tolerance includes the student's +2 minute stagger.
  if (minute < start || minute > start + ATTEMPT_OFFSETS.at(-1)! + 5) return null;
  return { since: now.getTime() - (minute - start) * 60000 - now.getUTCSeconds() * 1000 - now.getUTCMilliseconds(), key: `${p.year}-${p.month}-${p.day}-${start}`, elapsedMinutes: minute - start };
}
export async function watchdog(profile: 'parent' | 'student', token: string | undefined, fetcher: typeof fetch = fetch, now = new Date()) {
  const slot = windowAt(now);
  if (!slot) return { state: 'outside_window' };
  if (!token?.trim()) throw new Error('Missing dispatch credential');
  const workflow = profile === 'parent' ? 'update.yml' : 'update-student.yml';
  const signal = AbortSignal.timeout(22000); // Entire check fits Netlify's 30s limit.
  const github = async (path: string, body?: object) => {
    const response = await fetchGitHub(root + path, { method: body ? 'POST' : 'GET', signal, redirect: 'error', headers: { Authorization: `Bearer ${token.trim()}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) }, fetcher);
    if (!response.ok) throw new Error(`GitHub status ${response.status}`);
    return response.status === 204 ? null : response.json();
  };
  // Keep branch filtering local; GitHub's query filter can omit real main runs.
  const list = await github(`/workflows/${workflow}/runs?per_page=100`);
  const runs = (list.workflow_runs as Run[]).filter(r => r.path === `.github/workflows/${workflow}` && r.head_branch === 'main');
  if (runs.some(r => r.status !== 'completed')) return { state: 'running' };
  const recent = runs.filter(r => Date.parse(r.created_at) >= slot.since);
  for (const run of recent.filter(r => r.conclusion === 'success').slice(0, 3)) {
    if (await publicationVerified(github, run)) return { state: 'fresh' };
  }
  const attempts = recent.filter(r => r.display_title?.startsWith('Scheduled report')).length;
  if (attempts >= ATTEMPT_OFFSETS.length) return { state: 'attempts_exhausted' };
  if (slot.elapsedMinutes < ATTEMPT_OFFSETS[attempts]) return { state: 'recovery_wait' };
  if (recent.some(r => now.getTime() - Date.parse(r.created_at) < 5 * 60000)) return { state: 'cooldown' };
  await github(`/workflows/${workflow}/dispatches`, { ref: 'main', inputs: { scheduled: 'true' } });
  return { state: 'dispatched', attempt: attempts + 1 };
}
