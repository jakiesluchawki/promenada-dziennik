import sys, pathlib, unittest
from datetime import datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from schedule_due import needs_collection, slot_start
from verify_publication import validate_fresh

def dt(s): return datetime.fromisoformat(s)
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
