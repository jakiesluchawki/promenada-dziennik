"""Historical source recovery uses synthetic content and no live credentials."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import publisher
from report_errors import ReportError
from report_sources import reconcile_sources

SOURCE_ID = 'demo:announcement:synthetic-source'


def source():
    return {
        'id': SOURCE_ID, 'child': 'demo', 'kind': 'announcement',
        'title': 'Synthetic announcement', 'text': 'Original synthetic body',
        'sender': 'Synthetic school', 'date': '2026-10-01', 'attachments': [],
    }


def account(announcements=None):
    return {
        'child': 'demo', 'status': 'ok', 'checked_at': '2026-10-02T16:00:00+00:00',
        'messages': [], 'announcements': announcements or [], 'sections': {},
    }


class HistoricalSources(unittest.TestCase):
    def setUp(self):
        self.previous = {'collected_at': '2026-10-02T16:00:00+00:00', 'accounts': {'demo': account([source()])}}
        self.current = {'collected_at': '2026-10-03T16:00:00+00:00', 'accounts': {'demo': account()}}
        self.digest = {'actions': [{
            'child': 'demo', 'source_id': SOURCE_ID, 'title': 'Synthetic task',
            'text': 'Original synthetic task', 'date': '2026-10-10',
        }], 'observations': []}

    def recover(self):
        return reconcile_sources(self.previous, self.current, self.digest)

    def assert_failure(self, code):
        with self.assertRaises(ReportError) as raised:
            self.recover()
        self.assertEqual(raised.exception.code, code)

    def test_only_referenced_same_account_source_is_restored(self):
        other = dict(source(), id='demo:announcement:unrelated', title='Unrelated synthetic notice')
        self.previous['accounts']['demo']['announcements'].append(other)
        previous, current, digest = copy.deepcopy((self.previous, self.current, self.digest))
        result = self.recover()
        restored = result['accounts']['demo']['announcements']
        self.assertEqual(len(restored), 1)
        for key in ('id', 'child', 'kind', 'text', 'sender', 'date', 'attachments'):
            self.assertEqual(restored[0][key], source()[key])
        self.assertTrue(restored[0]['archived'])
        self.assertEqual(restored[0]['title'], 'Archiwum · Synthetic announcement')
        self.assertEqual(restored[0]['original_title'], source()['title'])
        self.assertEqual(restored[0]['last_seen_at'], previous['accounts']['demo']['checked_at'])
        self.assertEqual((self.previous, self.current, self.digest), (previous, current, digest))

    def test_current_source_wins(self):
        self.current['accounts']['demo']['announcements'] = [dict(source(), text='Current content wins')]
        self.assertEqual(self.recover(), self.current)

    def test_second_refresh_is_idempotent_and_last_seen_is_not_advanced(self):
        first = self.recover()
        first['accounts']['demo']['checked_at'] = '2026-10-03T16:00:00+00:00'
        second = reconcile_sources(first, self.current, self.digest)
        self.assertEqual(second['accounts']['demo']['announcements'], first['accounts']['demo']['announcements'])
        self.assertEqual(second['accounts']['demo']['announcements'][0]['last_seen_at'], '2026-10-02T16:00:00+00:00')

    def test_reappearing_live_source_replaces_archive(self):
        archived = self.recover()
        self.current['accounts']['demo']['announcements'] = [source()]
        result = reconcile_sources(archived, self.current, self.digest)
        self.assertEqual(result, self.current)
        self.assertNotIn('archived', result['accounts']['demo']['announcements'][0])

    def test_two_actions_do_not_duplicate_their_source(self):
        self.digest['actions'].append(dict(self.digest['actions'][0], title='Second task'))
        self.assertEqual(len(self.recover()['accounts']['demo']['announcements']), 1)

    def test_source_less_actions_are_unchanged(self):
        self.digest['actions'] = [{'child': 'demo', 'title': 'No linked source'}]
        self.assertEqual(self.recover(), self.current)

    def test_unknown_source_is_not_invented(self):
        self.previous['accounts']['demo']['announcements'] = []
        self.assert_failure('digest_unknown_source')

    def test_unhealthy_current_account_is_not_repaired_as_fresh(self):
        self.current['accounts']['demo']['status'] = 'error'
        self.assert_failure('digest_unknown_source')

    def test_removed_account_is_not_reintroduced(self):
        self.current['accounts'] = {}
        self.assert_failure('digest_source_scope')

    def test_source_from_another_child_is_rejected(self):
        self.previous['accounts']['demo']['announcements'][0]['child'] = 'other'
        self.assert_failure('digest_source_scope')

    def test_source_only_present_in_other_account_is_rejected(self):
        self.current['accounts']['other'] = account([source()])
        self.assert_failure('digest_source_scope')

    def test_source_duplicated_across_accounts_is_rejected(self):
        self.current['accounts']['demo']['announcements'] = [source()]
        self.current['accounts']['other'] = account([source()])
        self.assert_failure('digest_source_scope')

    def test_current_source_child_mismatch_is_rejected(self):
        self.current['accounts']['demo']['announcements'] = [dict(source(), child='other')]
        self.assert_failure('digest_source_scope')

    def test_mis_scoped_id_or_kind_is_rejected(self):
        for field, value in [('id', 'other:announcement:synthetic-source'), ('kind', 'message')]:
            with self.subTest(field=field):
                self.setUp()
                item = self.previous['accounts']['demo']['announcements'][0]
                item[field] = value
                self.digest['actions'][0]['source_id'] = item['id']
                self.assert_failure('digest_source_scope')

    def test_ambiguous_prior_source_is_rejected(self):
        self.previous['accounts']['demo']['announcements'].append(source())
        self.assert_failure('digest_unknown_source')

    def test_current_duplicate_source_is_rejected(self):
        self.current['accounts']['demo']['announcements'] = [source(), source()]
        self.assert_failure('digest_source_scope')

    def test_unknown_archived_title_is_not_fabricated(self):
        self.previous['accounts']['demo']['announcements'][0]['archived'] = True
        self.assert_failure('digest_unknown_source')

    def test_action_identity_and_completion_revision_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(publisher, 'BASE', pathlib.Path(temporary)), patch.object(publisher, 'secret', return_value=json.dumps({'demo': {}})), patch.dict('os.environ', {'PARENT_REFRESH_CONFIG': ''}):
            def build(report):
                (publisher.BASE / 'snapshot.json').write_text(json.dumps(report))
                (publisher.BASE / 'digest.json').write_text(json.dumps(self.digest))
                return publisher.load_report()
            before = build(self.previous)
            after = build(self.recover())
            self.assertEqual(before['digest']['actions'], after['digest']['actions'])
            self.assertNotEqual(before['accounts']['demo']['announcements'][0]['revision'], after['accounts']['demo']['announcements'][0]['revision'])


if __name__ == '__main__':
    unittest.main()
