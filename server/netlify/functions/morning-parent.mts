import { watchdog } from '../../lib/watchdog.mts';
export default async () => {
  console.log('parent_schedule', await watchdog('parent', Netlify.env.get('MAHBRUS_GITHUB_TOKEN')));
};
// Both UTC offsets; the Warsaw window check handles daylight saving time.
export const config = { schedule: '0,10,20,30,40,50 4,5,16,17 * * *' };
