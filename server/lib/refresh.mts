import { createHash, timingSafeEqual } from 'node:crypto';
export type Settings = { githubToken?: string; parentHash?: string; studentHash?: string };
type Run = { id: number; status: string; conclusion: string | null; created_at: string; path: string; head_branch: string };
function reply(state: string, message: string, status = 200, run: string | null = null) {
  return Response.json({ state, message, run }, { status, headers: { 'Cache-Control': 'no-store' } });
}
function matches(token: string, expected?: string) {
  if (!expected || !/^[a-f0-9]{64}$/.test(expected)) return false;
  return timingSafeEqual(createHash('sha256').update(token).digest(), Buffer.from(expected, 'hex'));
}
export async function handle(req: Request, env: Settings, fetcher: typeof fetch = fetch, now = Date.now()) {
  if (!['GET', 'POST'].includes(req.method)) return reply('error', 'Niedozwolona metoda.', 405);
  const auth = req.headers.get('Authorization') || '';
  if (!/^Bearer [A-Za-z0-9_-]{43}$/.test(auth)) return reply('error', 'Brak dostępu.', 401);
  const token = auth.slice(7);
  const workflow = matches(token, env.parentHash) ? 'update.yml' : matches(token, env.studentHash) ? 'update-student.yml' : null;
  if (!workflow) return reply('error', 'Brak dostępu.', 401);
  if (!env.githubToken) return reply('error', 'Odczyt nie jest jeszcze skonfigurowany.', 503);
  const root = 'https://api.github.com/repos/jakiesluchawki/promenada-dziennik/actions';
  async function github(path: string, method = 'GET', body?: object) {
    const response = await fetcher(root + path, { method, redirect: 'error', signal: AbortSignal.timeout(15000),
      headers: { Authorization: `Bearer ${env.githubToken}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new Error('GitHub unavailable');
    return response.status === 204 ? null : await response.json();
  }
  try {
    const query = new URL(req.url).searchParams.get('run');
    if (query && !/^(after:)?\d{1,20}$/.test(query)) return reply('error', 'Nieprawidłowy odczyt.', 400);
    const result = await github(`/workflows/${workflow}/runs?branch=main&per_page=30`);
    const runs = (result.workflow_runs as Run[]).filter(r => r.path === `.github/workflows/${workflow}` && r.head_branch === 'main');
    if (req.method === 'GET' && query) {
      const run = query.startsWith('after:') ? runs.find(r => r.id > Number(query.slice(6))) : runs.find(r => String(r.id) === query);
      if (!run) return reply('queued', 'Oczekiwanie na uruchomienie odczytu…', 200, query);
      if (run.status !== 'completed') return reply('running', 'Pobieranie i publikowanie raportu…', 200, String(run.id));
      return run.conclusion === 'success' ? reply('complete', 'Raport jest gotowy.', 200, String(run.id)) : reply('failed', 'Odczyt nie zakończył się poprawnie. Poprzedni raport pozostaje dostępny.', 200, String(run.id));
    }
    const active = runs.find(r => r.status !== 'completed');
    if (active) return reply('running', 'Odczyt już trwa…', 200, String(active.id));
    const latest = runs[0];
    const remaining = latest ? 300000 - (now - Date.parse(latest.created_at)) : 0;
    if (remaining > 0) return reply('cooldown', `Kolejny odczyt za około ${Math.ceil(remaining / 60000)} min. Wczytaj dostępny raport.`, 200, latest ? String(latest.id) : null);
    if (req.method === 'GET') return reply('idle', 'Możesz uruchomić nowy odczyt.');
    // Neither workflow, ref nor inputs are accepted from the client.
    await github(`/workflows/${workflow}/dispatches`, 'POST', { ref: 'main' });
    return reply('queued', 'Odczyt zlecony. Czekam na GitHub Actions…', 202, 'after:' + (latest?.id || 0));
  } catch { return reply('error', 'Serwer odświeżania jest chwilowo niedostępny. Spróbuj później.', 503); }
}
