import { handle } from '../../lib/refresh.mts';
declare const Netlify: { env: { get(name: string): string | undefined } };
export default async (req: Request) => handle(req, {
  githubToken: Netlify.env.get('MAHBRUS_GITHUB_TOKEN'),
  parentHash: Netlify.env.get('MAHBRUS_PARENT_REFRESH_HASH'),
  studentHash: Netlify.env.get('MAHBRUS_STUDENT_REFRESH_HASH'),
});
export const config = { path: '/api/refresh' };
