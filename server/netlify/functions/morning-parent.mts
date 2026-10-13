import { watchdog } from '../../lib/watchdog.mts';
export default async () => {
  console.log('parent_schedule', await watchdog('parent', Netlify.env.get('MAHBRUS_GITHUB_TOKEN')));
};
// Both UTC offsets, including the +60 minute recovery in winter.
// The Warsaw window and attempt offsets prevent extra collection when healthy.
export const config = { schedule: '0,10,20,30,40,50 4,5,6,16,17,18 * * *' };
