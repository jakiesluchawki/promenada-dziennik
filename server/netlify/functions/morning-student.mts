import { watchdog } from '../../lib/watchdog.mts';
export default async () => {
  console.log('student_schedule', await watchdog('student', Netlify.env.get('MAHBRUS_GITHUB_TOKEN')));
};
export const config = { schedule: '2,12,22,32,42,52 4,5,16,17 * * *' };
