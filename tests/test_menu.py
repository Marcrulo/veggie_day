import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import message  # noqa: E402
import notify  # noqa: E402
import veggie_menu  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def load(name):
    return veggie_menu.parse((FIXTURES / name).read_text(encoding="utf-8"))


class TestParse(unittest.TestCase):
    def test_week_header(self):
        week = load("week36.html")
        self.assertEqual(week.week_number, "Week 36")
        self.assertEqual(week.label, "31. August - 4. September 2026")
        self.assertEqual(week.monday, date(2026, 8, 31))

    def test_only_weekdays_with_content(self):
        week = load("week36.html")
        self.assertEqual([d.name for d in week.days], ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        self.assertTrue(all(len(d.dishes) == 2 for d in week.days))

    def test_dates_follow_the_weekday(self):
        week = load("week36.html")
        self.assertEqual(week.days[4].date, date(2026, 9, 4))

    def test_tags_are_detected(self):
        week = load("week36.html")
        self.assertEqual([d.name for d in week.days_with("FISH DAY")], ["Friday"])
        self.assertEqual([d.name for d in week.days_with("VEGAN")], ["Monday"])
        self.assertEqual([d.name for d in week.days_with("VEGETARIAN")], ["Monday"])

    def test_tag_prefix_is_stripped_from_title(self):
        monday = load("week36.html").days[0]
        self.assertTrue(monday.dishes[0].title.startswith("Risotto with mushrooms"))

    def test_mixed_case_mentions_are_not_tags(self):
        """'Vegan Chili sin carne' is a dish name, not a themed day."""
        week = load("week35.html")
        wednesday = week.days[2]
        self.assertEqual(wednesday.dishes[1].title, "Vegan Chili sin carne")
        self.assertEqual(wednesday.dishes[1].tags, [])
        self.assertEqual([d.name for d in week.days_with("VEGETARIAN")], [])

    def test_shorter_week(self):
        week = load("week35.html")
        self.assertEqual([d.name for d in week.days], ["Monday", "Tuesday", "Wednesday", "Thursday"])

    def test_new_year_rollover(self):
        self.assertEqual(veggie_menu._parse_monday("28. December - 1. January 2027"), date(2026, 12, 28))

    def test_no_menu_parses_empty(self):
        week = veggie_menu.parse("<html><body>nothing here</body></html>")
        self.assertEqual(week.days, [])


class TestMessage(unittest.TestCase):
    def test_headlines(self):
        self.assertEqual(
            message.headline_lines(load("week35.html")),
            ["VEGGIE day on Wednesday"],
        )

    def test_a_day_with_both_veggie_tags_counts_once(self):
        week = load("week36.html")  # Monday is VEGETARIAN and VEGAN
        self.assertEqual(message.headline_lines(week), ["VEGGIE day on Monday"])

    def test_veggie_days_are_joined(self):
        week = load("week36.html")
        week.days[2].dishes[0].tags = ["VEGETARIAN"]
        self.assertEqual(message.headline_lines(week)[0], "VEGGIE day on Monday and Wednesday")
        week.days[3].dishes[0].tags = ["VEGAN"]
        self.assertEqual(
            message.headline_lines(week)[0], "VEGGIE day on Monday, Wednesday and Thursday"
        )

    def test_join_helper(self):
        self.assertEqual(message._join([]), "")
        self.assertEqual(message._join(["Mon"]), "Mon")
        self.assertEqual(message._join(["Mon", "Fri"]), "Mon and Fri")
        self.assertEqual(message._join(["Mon", "Wed", "Fri"]), "Mon, Wed and Fri")

    def test_subject_starts_with_the_emoji(self):
        self.assertTrue(message.subject(load("week36.html")).startswith("🥦🚨 "))

    def test_subject_format(self):
        self.assertEqual(
            message.subject(load("week36.html")),
            "🥦🚨 Week 36: VEGGIE day on Monday",
        )
        self.assertEqual(
            message.subject(load("week35.html")),
            "🥦🚨 Week 35: VEGGIE day on Wednesday",
        )

    def test_fiskedag_is_not_announced_but_stays_in_the_menu(self):
        week = load("week36.html")  # FISH DAY on Friday
        self.assertNotIn("FISH DAY", message.subject(week))
        self.assertIn("[FISH DAY]", message.body(week))
        self.assertIn("FISH DAY", message.html_body(week))

    def test_week_with_only_fiskedag_has_no_veggie_headline(self):
        week = load("week36.html")
        for dish in week.days[0].dishes:
            dish.tags = []
        self.assertEqual(message.headline_lines(week), [])
        self.assertEqual(message.subject(week), "🥦🚨 Week 36: no VEGGIE day")

    def test_body_is_just_the_menu(self):
        """The announcements live in the subject now, not above the menu."""
        body = message.body(load("week36.html"))
        self.assertNotIn("VEGGIE day on Monday", body)
        self.assertIn("[VEGAN]", body)

    def test_body_lists_every_day(self):
        body = message.body(load("week36.html"))
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            self.assertIn(day, body)
        self.assertIn("[FISH DAY]", body)


class TestWeekSelection(unittest.TestCase):
    def test_next_monday_from_each_weekday(self):
        # Sunday 2026-08-30 -> the very next day; Monday 2026-08-31 -> a week on.
        self.assertEqual(veggie_menu.next_monday(date(2026, 8, 30)), date(2026, 8, 31))
        self.assertEqual(veggie_menu.next_monday(date(2026, 8, 31)), date(2026, 9, 7))
        self.assertEqual(veggie_menu.next_monday(date(2026, 8, 29)), date(2026, 8, 31))
        self.assertEqual(veggie_menu.next_monday(date(2026, 9, 2)), date(2026, 9, 7))

    def test_picks_the_tab_holding_next_monday(self):
        pages = {0: (FIXTURES / "week35.html").read_text(encoding="utf-8"),
                 1: (FIXTURES / "week36.html").read_text(encoding="utf-8")}
        asked = []

        def fake_fetch(active_week=1, url=None, timeout=30):
            asked.append(active_week)
            return pages[active_week]

        original = veggie_menu.fetch
        veggie_menu.fetch = fake_fetch
        try:
            week = veggie_menu.get_upcoming_week(today=date(2026, 8, 30))
            self.assertEqual(week.week_number, "Week 36")
            week = veggie_menu.get_upcoming_week(today=date(2026, 8, 23))
            self.assertEqual(week.week_number, "Week 35")
            with self.assertRaises(LookupError):
                veggie_menu.get_upcoming_week(today=date(2027, 1, 1))
        finally:
            veggie_menu.fetch = original
        self.assertIn(0, asked, "should fall back to the other tab")


class TestFetchRetry(unittest.TestCase):
    """The canteen site occasionally stops answering for a minute or two."""

    def fake_urlopen(self, outcomes):
        import io
        import urllib.error
        from contextlib import contextmanager

        calls = []

        @contextmanager
        def urlopen(request, timeout=None):
            calls.append(request.full_url)
            outcome = outcomes[len(calls) - 1]
            if outcome is None:
                raise urllib.error.URLError("timed out")
            response = io.BytesIO(outcome.encode())
            response.headers = type("H", (), {"get_content_charset": lambda self: "utf-8"})()
            yield response

        return urlopen, calls

    def run_fetch(self, outcomes, **kwargs):
        urlopen, calls = self.fake_urlopen(outcomes)
        sleeps = []
        originals = veggie_menu.urllib.request.urlopen, veggie_menu.time.sleep
        veggie_menu.urllib.request.urlopen = urlopen
        veggie_menu.time.sleep = sleeps.append
        try:
            return veggie_menu.fetch(**kwargs), calls, sleeps
        finally:
            veggie_menu.urllib.request.urlopen, veggie_menu.time.sleep = originals

    def test_retries_after_a_timeout(self):
        page, calls, sleeps = self.run_fetch([None, None, "<html>ok</html>"])
        self.assertEqual(page, "<html>ok</html>")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(sleeps), 2)

    def test_gives_up_after_the_last_attempt(self):
        import urllib.error

        with self.assertRaises(urllib.error.URLError):
            self.run_fetch([None] * 10, attempts=3)


class TestHtml(unittest.TestCase):
    def test_html_is_balanced_and_complete(self):
        html = message.html_body(load("week36.html"))
        self.assertNotIn("{", html, "unrendered format placeholder")
        self.assertEqual(html.count("<table"), html.count("</table>"))
        self.assertIn("Week 36", html)
        self.assertNotIn("on <strong>Monday", html)
        self.assertIn("FISH DAY", html)
        self.assertIn("Risotto", html)

    def test_html_escapes_dish_text(self):
        week = load("week36.html")
        week.days[0].dishes[0].title = 'Fish & <chips> "with" dip'
        html = message.html_body(week)
        self.assertIn("Fish &amp; &lt;chips&gt;", html)
        self.assertNotIn("<chips>", html)


class TestRecipients(unittest.TestCase):
    def test_repo_list_is_readable(self):
        self.assertTrue(notify.recipients(), "recipients.txt has no addresses")

    def test_comments_and_blanks_and_dupes_are_ignored(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write(
                "# a comment\n\n"
                "a@x.dk\n"
                "  b@y.dk  # trailing comment\n"
                "a@x.dk\n"
            )
        self.assertEqual(notify.recipients(handle.name), ["a@x.dk", "b@y.dk"])


class TestLive(unittest.TestCase):
    """Hits the real site. Skipped unless LIVE=1."""

    def setUp(self):
        import os

        if os.environ.get("LIVE") != "1":
            self.skipTest("set LIVE=1 to run")

    def test_fetch_next_week(self):
        week = veggie_menu.get_week(active_week=1)
        self.assertTrue(week.days, "no days parsed from the live page")
        self.assertTrue(week.week_number.startswith("Week"))


if __name__ == "__main__":
    unittest.main()
