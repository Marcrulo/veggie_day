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
        self.assertEqual(week.week_number, "Uge 36")
        self.assertEqual(week.label, "31. august - 4. september 2026")
        self.assertEqual(week.monday, date(2026, 8, 31))

    def test_only_weekdays_with_content(self):
        week = load("week36.html")
        self.assertEqual([d.name_en for d in week.days], ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])
        self.assertTrue(all(len(d.dishes) == 2 for d in week.days))

    def test_dates_follow_the_weekday(self):
        week = load("week36.html")
        self.assertEqual(week.days[4].date, date(2026, 9, 4))

    def test_tags_are_detected(self):
        week = load("week36.html")
        self.assertEqual([d.name_en for d in week.days_with("FISKEDAG")], ["Friday"])
        self.assertEqual([d.name_en for d in week.days_with("VEGANSK")], ["Monday"])
        self.assertEqual([d.name_en for d in week.days_with("VEGETARISK")], ["Monday"])

    def test_tag_prefix_is_stripped_from_title(self):
        monday = load("week36.html").days[0]
        self.assertTrue(monday.dishes[0].title.startswith("Risotto med svampe"))

    def test_mixed_case_mentions_are_not_tags(self):
        """'Vegansk Chili sin carne' is a dish name, not a themed day."""
        week = load("week35.html")
        wednesday = week.days[2]
        self.assertEqual(wednesday.dishes[1].title, "Vegansk Chili sin carne")
        self.assertEqual(wednesday.dishes[1].tags, [])
        self.assertEqual([d.name_en for d in week.days_with("VEGETARISK")], [])

    def test_shorter_week(self):
        week = load("week35.html")
        self.assertEqual([d.name_en for d in week.days], ["Monday", "Tuesday", "Wednesday", "Thursday"])

    def test_new_year_rollover(self):
        self.assertEqual(veggie_menu._parse_monday("28. december - 1. januar 2027"), date(2026, 12, 28))

    def test_no_menu_parses_empty(self):
        week = veggie_menu.parse("<html><body>nothing here</body></html>")
        self.assertEqual(week.days, [])


class TestMessage(unittest.TestCase):
    def test_headlines(self):
        self.assertEqual(
            message.headlines(load("week35.html")),
            ["VEGANSK on Wednesday", "FISKEDAG on Thursday"],
        )

    def test_subject_mentions_week(self):
        self.assertTrue(message.subject(load("week36.html")).startswith("Uge 36:"))

    def test_body_lists_every_day(self):
        body = message.body(load("week36.html"))
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            self.assertIn(day, body)
        self.assertIn("[FISKEDAG]", body)


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
        self.assertTrue(week.week_number.startswith("Uge"))


if __name__ == "__main__":
    unittest.main()
