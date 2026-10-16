"""Synthetic inbox pages: no live credentials or school content."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from bs4 import BeautifulSoup
import collector

ORIGIN = "https://synergia.librus.pl"


def inbox(number=0, message=1, *, last=False):
    pager = "" if last else f"""
      <li class="jump"><a href="javascript:void(null)" onclick="document.getElementById('numer_strony105').value={number+1}; document.getElementById('numer_strony105').form.submit();">Następna&nbsp;&gt;</a></li>"""
    return BeautifulSoup(f"""
      <form name="formWiadomosci" action="/wiadomosci" method="POST">
        <input type="hidden" name="requestkey" value="synthetic-token">
        <input type="hidden" name="idPojemnika" value="5">
        <input type="hidden" name="filtrUzytkownikow" value="-">
        <input type="hidden" name="sortowanie[105][0]" value="3">
        <input type="hidden" name="numer_strony105" id="numer_strony105" value="{number}">
        <input type="checkbox" name="wiadomosci[]" value="{message}" checked>
        <input type="hidden" name="usun_zaznaczone" value="delete">
        <select name="opcja_zaznaczone_g"><option selected value="read">mark read</option></select>
        <table><tr><td><a href="/wiadomosci/1/5/{message}">Synthetic message</a></td></tr></table>
        {pager}
      </form>""", "html.parser")


def response(page, url=ORIGIN + "/wiadomosci"):
    result = Mock(url=url, text=str(page))
    result.raise_for_status = Mock()
    return result


class MailboxPagination(unittest.TestCase):
    def test_form_pager_preserves_navigation_context_without_message_actions(self):
        session, visited = Mock(), set()
        following = inbox(1, 2, last=True)
        with patch.object(collector, "request", return_value=response(following)) as request:
            result = collector.next_mailbox_page(session, inbox(), 1, visited)
        args, kwargs = request.call_args
        self.assertEqual(args, (session, "POST", ORIGIN + "/wiadomosci"))
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(dict(kwargs["data"]), {
            "requestkey": "synthetic-token", "idPojemnika": "5", "filtrUzytkownikow": "-",
            "sortowanie[105][0]": "3", "numer_strony105": "1",
        })
        self.assertIn("/wiadomosci/1/5/2", str(result))
        self.assertEqual(visited, {(ORIGIN + "/wiadomosci", "numer_strony105", 1)})

    def test_normal_inbox_link_is_still_supported(self):
        page = inbox()
        page.select_one("li a")["href"] = "/wiadomosci/5?page=1"
        with patch.object(collector, "request", return_value=response(inbox(1, 2))) as request:
            collector.next_mailbox_page(Mock(), page, 1, set())
        self.assertEqual(request.call_args.args[1:], ("GET", ORIGIN + "/wiadomosci/5?page=1"))
        self.assertNotIn("data", request.call_args.kwargs)

    def test_final_page_and_message_subject_are_not_navigation(self):
        page = inbox(last=True)
        page.select_one("table a").string = "Dalej omawiamy lekturę"
        with patch.object(collector, "request") as request:
            self.assertIsNone(collector.next_mailbox_page(Mock(), page, 1, set()))
        request.assert_not_called()

    def test_unrecognised_script_is_not_executed_or_requested(self):
        page = inbox()
        page.select_one("li a")["onclick"] += "window.location='https://example.invalid';"
        with patch.object(collector, "request") as request, self.assertRaisesRegex(RuntimeError, "Unsupported mailbox pagination"):
            collector.next_mailbox_page(Mock(), page, 1, set())
        request.assert_not_called()

    def test_modified_forms_and_nonsequential_pages_fail_before_request(self):
        mutations = [
            lambda p: p.form.__setitem__("action", "https://example.invalid/wiadomosci"),
            lambda p: p.form.__setitem__("method", "GET"),
            lambda p: p.form.__setitem__("name", "differentForm"),
            lambda p: p.select_one("#numer_strony105").__setitem__("value", "3"),
            lambda p: p.select_one("#numer_strony105").__setitem__("type", "text"),
            lambda p: p.select_one("#numer_strony105").__setitem__("name", "delete"),
            lambda p: p.select_one("#numer_strony105").decompose(),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                page = inbox()
                mutate(page)
                with patch.object(collector, "request") as request, self.assertRaises(RuntimeError):
                    collector.next_mailbox_page(Mock(), page, 1, set())
                request.assert_not_called()

    def test_foreign_http_and_nonmailbox_links_are_rejected(self):
        for href in ["https://example.invalid/wiadomosci", "http://synergia.librus.pl/wiadomosci",
                     "https://user@synergia.librus.pl/wiadomosci", "/wiadomosci/usun/123"]:
            with self.subTest(href=href):
                page = inbox()
                page.select_one("li a")["href"] = href
                with patch.object(collector, "request") as request, self.assertRaises(RuntimeError):
                    collector.next_mailbox_page(Mock(), page, 1, set())
                request.assert_not_called()

    def test_page_limit_and_repeated_navigation_stop_before_request(self):
        for count, visited in [(20, set()), (2, {(ORIGIN + "/wiadomosci", "numer_strony105", 1)})]:
            with self.subTest(count=count), patch.object(collector, "request") as request, self.assertRaises(RuntimeError):
                collector.next_mailbox_page(Mock(), inbox(), count, visited)
            request.assert_not_called()

    def test_server_ignoring_page_number_does_not_claim_success(self):
        with patch.object(collector, "request", return_value=response(inbox())) as request, self.assertRaisesRegex(RuntimeError, "did not advance"):
            collector.next_mailbox_page(Mock(), inbox(), 1, set())
        self.assertEqual(request.call_count, 1)

    def test_expired_session_is_not_accepted_as_next_page(self):
        with patch.object(collector, "request", return_value=response(inbox(), ORIGIN + "/loguj")), self.assertRaisesRegex(RuntimeError, "Session expired"):
            collector.next_mailbox_page(Mock(), inbox(), 1, set())

    def test_empty_or_changed_response_does_not_claim_complete_mailbox(self):
        with patch.object(collector, "request", return_value=response("<div>Unexpected page</div>")), self.assertRaisesRegex(RuntimeError, "returned no messages"):
            collector.next_mailbox_page(Mock(), inbox(), 1, set())

    def test_collector_reads_all_pages_and_keeps_cached_message_bodies(self):
        pages = [inbox(), inbox(1, 2), inbox(2, 3, last=True)]
        previous = {"messages": [{"id": f"demo:message:{n}", "attachment_version": 2, "text": f"cached {n}"} for n in range(1, 4)]}
        with patch.object(collector, "login", return_value=(Mock(), pages[0], "")), \
             patch.object(collector, "request", side_effect=[response(p) for p in pages[1:]]) as request, \
             patch.object(collector, "checked_get", return_value=BeautifulSoup("<div id='body'></div>", "html.parser")), \
             patch.object(collector.time, "sleep"):
            account = collector.collect_account("demo", previous)
        self.assertEqual(account["status"], "ok")
        self.assertEqual([m["text"] for m in account["messages"]], ["cached 1", "cached 2", "cached 3"])
        self.assertEqual([dict(c.kwargs["data"])["numer_strony105"] for c in request.call_args_list], ["1", "2"])
        self.assertEqual(set(account["sections"]), {"timetable", "dates", "homework", "grades", "attendance", "notes", "achievements"})

    def test_pagination_failure_preserves_last_good_timestamp_and_messages(self):
        previous = {"accounts": {"demo": {"status": "ok", "checked_at": "2026-10-15T16:00:00+00:00", "messages": [{"id": "demo:message:1", "text": "cached"}]}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(collector, "BASE", pathlib.Path(directory)), \
             patch.object(collector, "secret", return_value='{"demo":{}}'), \
             patch.object(collector, "collect_account", side_effect=RuntimeError("Mailbox pagination did not advance")), \
             contextlib.redirect_stdout(io.StringIO()):
            path = pathlib.Path(directory) / "snapshot.json"
            path.write_text(json.dumps(previous))
            with self.assertRaises(SystemExit):
                collector.main()
            account = json.loads(path.read_text())["accounts"]["demo"]
        self.assertEqual(account["status"], "error")
        self.assertEqual(account["checked_at"], previous["accounts"]["demo"]["checked_at"])
        self.assertEqual(account["messages"], previous["accounts"]["demo"]["messages"])
        self.assertEqual(account["error"], "Mailbox pagination did not advance")


if __name__ == "__main__":
    unittest.main()
