"""Scrape the Coor canteen week menu (Lautrupbjerg 7) and pick out the tagged days.

The page is server-rendered, so plain HTML parsing is enough - no browser needed.
Tabs: ?active_week=0 is the current week, ?active_week=1 is next week.
"""

from __future__ import annotations

import html
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta

MENU_URL = "https://gn.foodbycoor.dk/lautrupbjerg-7/en/weekmenu"

# The canteen writes these as an ALL-CAPS prefix on the dish title, e.g.
# "VEGAN        Ratatouille of squash ...". Lower/mixed case mentions
# ("Vegan Chili sin carne") are just dish names, not a themed day.
# Longest first so VEGETARIAN is not shadowed by a shorter alternative.
TAGS = ("VEGETARIAN", "VEGAN", "FISH DAY")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

_HEADER_RE = re.compile(
    r'<h2 class="header-week">\s*(.*?)\s*<span class="week-number">\s*\((.*?)\)',
    re.S,
)
_DAY_BLOCK_RE = re.compile(r'<div class="day">(.*?)(?=<div class="day">|$)', re.S)
_DAY_NAME_RE = re.compile(r"<h2>\s*(.*?)\s*</h2>", re.S)
_TITLE_RE = re.compile(r'<div class="element title[^"]*">\s*(.*?)\s*</div>', re.S)
_DATE_RE = re.compile(r"(\d{1,2})\.\s*([a-zA-Z]+)(?:\s+(\d{4}))?")


@dataclass
class Dish:
    title: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Day:
    name: str
    date: date | None
    dishes: list[Dish] = field(default_factory=list)

    @property
    def tags(self) -> list[str]:
        seen: list[str] = []
        for dish in self.dishes:
            for tag in dish.tags:
                if tag not in seen:
                    seen.append(tag)
        return seen


@dataclass
class Week:
    label: str  # e.g. "31. August - 4. September 2026"
    week_number: str  # e.g. "Week 36", as printed on the page
    monday: date | None
    days: list[Day] = field(default_factory=list)

    @property
    def number(self) -> str:
        """Just the digits, e.g. '36'. Falls back to the ISO week number."""
        digits = re.search(r"\d+", self.week_number)
        if digits:
            return digits.group()
        return str(self.monday.isocalendar()[1]) if self.monday else "?"

    def days_with(self, tag: str) -> list[Day]:
        return [d for d in self.days if tag in d.tags]


def fetch(active_week: int = 1, url: str = MENU_URL, timeout: int = 30) -> str:
    """Download the menu page. active_week=0 is this week, 1 is next week."""
    request = urllib.request.Request(
        f"{url}?active_week={active_week}",
        headers={"User-Agent": "veggie-day/1.0 (canteen menu notifier)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _split_tags(title: str) -> tuple[str, list[str]]:
    """Strip leading ALL-CAPS tags off a dish title."""
    tags: list[str] = []
    while True:
        match = re.match(r"(%s)\b[\s:.-]*" % "|".join(TAGS), title)
        if not match:
            break
        tags.append(match.group(1))
        title = title[match.end():]
    return title.strip(), tags


def _parse_monday(label: str) -> date | None:
    """Turn '31. August - 4. September 2026' into the Monday of that week."""
    matches = _DATE_RE.findall(label)
    if not matches:
        return None
    year = next((int(y) for _, _, y in reversed(matches) if y), None)
    if year is None:
        return None
    day, month_name, _ = matches[0]
    month = MONTHS.get(month_name.lower())
    if month is None:
        return None
    start = date(year, month, int(day))
    # The year is only printed once, at the end of the range. Across new year
    # ("28. December - 1. January 2027") the start belongs to the year before.
    end_day, end_month_name, _ = matches[-1]
    end_month = MONTHS.get(end_month_name.lower())
    if end_month is not None and start > date(year, end_month, int(end_day)):
        start = start.replace(year=year - 1)
    return start - timedelta(days=start.weekday())


def parse(page_html: str) -> Week:
    """Parse the currently selected week out of the menu page HTML."""
    header = _HEADER_RE.search(page_html)
    label = _clean(header.group(1)) if header else ""
    week_number = _clean(header.group(2)) if header else ""
    monday = _parse_monday(label)

    # Only look inside the week grid; Saturday/Sunday show up as empty day divs
    # and the surrounding page has plenty of other markup.
    start = page_html.find('class="two-week-content-container"')
    grid = page_html[start:] if start != -1 else page_html
    end = grid.find('<div class="actions">')
    if end != -1:
        grid = grid[:end]

    days: list[Day] = []
    for block in _DAY_BLOCK_RE.findall(grid):
        name_match = _DAY_NAME_RE.search(block)
        if not name_match:
            continue
        name = _clean(name_match.group(1))
        if name not in DAY_NAMES:
            continue
        index = DAY_NAMES.index(name)

        dishes = []
        for raw_title in _TITLE_RE.findall(block):
            title, tags = _split_tags(_clean(raw_title))
            if title or tags:
                dishes.append(Dish(title=title, tags=tags))

        days.append(
            Day(
                name=name,
                date=monday + timedelta(days=index) if monday else None,
                dishes=dishes,
            )
        )
    return Week(label=label, week_number=week_number, monday=monday, days=days)


def get_week(active_week: int = 1, url: str = MENU_URL) -> Week:
    return parse(fetch(active_week=active_week, url=url))


def next_monday(today: date | None = None) -> date:
    """The Monday of the coming week. On a Monday, that means seven days out."""
    today = today or date.today()
    return today + timedelta(days=7 - today.weekday())


def get_upcoming_week(url: str = MENU_URL, today: date | None = None) -> Week:
    """Return the week starting on the next Monday, whichever tab holds it.

    Which tab that is depends on the day the job runs, and the site rolls the
    tabs over at some point during the week - so ask for the date rather than
    assuming a tab number.
    """
    target = next_monday(today)
    tried = []
    for active_week in (1, 0):
        week = get_week(active_week=active_week, url=url)
        tried.append(f"active_week={active_week} -> {week.week_number or '?'} ({week.monday})")
        if week.monday == target:
            return week
    raise LookupError(
        f"No tab holds the week starting {target}. Tabs offered: {'; '.join(tried)}"
    )
