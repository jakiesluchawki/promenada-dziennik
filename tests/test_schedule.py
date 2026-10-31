import sys, pathlib, unittest
from datetime import datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from schedule_due import collection_plan, needs_collection, slot_start
from verify_publication import validate_fresh

def dt(s): return datetime.fromisoformat(s)

class PartialReportRecovery(unittest.TestCase):
    def setUp(self):
        self.started = '2026-10-31T18:00:39+00:00'
        self.now = dt('2026-10-31T18:03:18+00:00')
        self.report = {'collected_at': self.started, 'accounts': {
            'missing': {'status': 'error', 'checked_at': '2026-10-31T05:30:46+00:00',
                        'error_phase': 'pre_login', 'error_code': 'network_timeout'},
            'done': {'status': 'ok', 'checked_at': '2026-10-31T18:02:10+00:00'},
        }}

    def test_immediate_recovery_reuses_only_reads_from_the_relevant_window(self):
        for scheduled, floor in [(True, slot_start(self.now)), (False, dt(self.started))]:
            with self.subTest(scheduled=scheduled):
                due, reuse_since, _ = collection_plan(self.report, self.now, scheduled=scheduled,
                                                      recovery_since=self.started)
                self.assertTrue(due)
                self.assertEqual(dt(reuse_since), floor)

    def test_an_independent_recent_run_remains_in_cooldown(self):
        for scheduled in [True, False]:
            due, _, reason = collection_plan(self.report, self.now, scheduled=scheduled)
            self.assertFalse(due)
            self.assertIn('cooldown', reason)

    def test_a_later_scheduled_retry_keeps_good_reads_but_a_manual_refresh_reads_both(self):
        later = dt('2026-10-31T21:20:00+00:00')
        due, reuse_since, _ = collection_plan(self.report, later, scheduled=True)
        self.assertTrue(due)
        self.assertEqual(dt(reuse_since), slot_start(later))
        manual_due, manual_floor, _ = collection_plan(self.report, later, scheduled=False)
        self.assertTrue(manual_due)
        self.assertEqual(manual_floor, '')

    def test_recovery_marker_must_match_the_snapshot_and_the_failure_phase(self):
        with self.assertRaises(ValueError):
            collection_plan(self.report, self.now, scheduled=True, recovery_since=self.now.isoformat())
        del self.report['accounts']['missing']['error_phase']
        with self.assertRaises(ValueError):
            collection_plan(self.report, self.now, scheduled=True, recovery_since=self.started)

class Schedule(unittest.TestCase):
    def test_summer_winter_and_boundary(self):
        for now, expected in [('2026-09-12T04:30:00+00:00','2026-09-12T06:30:00+02:00'),('2026-12-12T05:30:00+00:00','2026-12-12T06:30:00+01:00'),('2026-09-12T04:29:00+00:00','2026-09-11T18:00:00+02:00')]:
            self.assertEqual(slot_start(dt(now)), dt(expected))
    def test_each_account_must_be_fresh_and_healthy(self):
        now=dt('2026-09-12T05:00:00+00:00')
        report={'collected_at':'2026-09-12T04:40:00+00:00','accounts':{'one':{'status':'ok'},'two':{'status':'ok'}}}
        self.assertFalse(needs_collection(report, now)); validate_fresh(report, now)
        report['accounts']['two']['checked_at']='2026-09-11T18:00:00+00:00'
        self.assertTrue(needs_collection(report, now))
        with self.assertRaises(ValueError): validate_fresh(report, now)
        report['accounts']['two']={'status':'error'}
        with self.assertRaises(ValueError): validate_fresh(report, now)
    def test_future_or_empty_report_is_not_success(self):
        now=dt('2026-09-12T05:00:00+00:00')
        for accounts in [{},{'one':{'status':'ok','checked_at':'2027-01-01T00:00:00+00:00'}}]:
            with self.assertRaises(ValueError): validate_fresh({'collected_at':now.isoformat(),'accounts':accounts},now)
if __name__=='__main__': unittest.main()
