"""Turn a parsed week into the email subject and body (plain text + HTML)."""

from __future__ import annotations

from html import escape

from veggie_menu import Week

# VEGANSK and VEGETARISK are announced together as one "VEGGIE day"; fish is
# announced on its own. The badges in the menu below still show the exact tag.
VEGGIE_TAGS = ("VEGANSK", "VEGETARISK")
VEGGIE_LABEL = "VEGGIE day"
FISH_TAG = "FISKEDAG"
FISH_LABEL = "FISKEDAG"

# Badge colours in the HTML mail.
TAG_COLORS = {
    "VEGANSK": ("#e7f4ea", "#1d6b34"),  # background, text
    "VEGETARISK": ("#eef3e2", "#4f6b1d"),
    "FISKEDAG": ("#e5eff7", "#1d4f6b"),
}
DEFAULT_COLORS = ("#eeeeee", "#555555")

MENU_LINK = "https://gn.foodbycoor.dk/lautrupbjerg-7/da/ugemenu"
LOCATION = "Kantinen · Lautrupbjerg 7"

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def _join(names: list[str]) -> str:
    """['Monday'] -> 'Monday'; ['Monday', 'Friday'] -> 'Monday and Friday'."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def headline_lines(week: Week) -> list[str]:
    """The announcements, e.g. ['VEGGIE day on Monday and Wednesday'].

    A day counts once even if it carries both veggie tags.
    """
    lines = []
    veggie = [d.name_en for d in week.days if any(t in VEGGIE_TAGS for t in d.tags)]
    if veggie:
        lines.append(f"{VEGGIE_LABEL} on {_join(veggie)}")
    fish = [d.name_en for d in week.days if FISH_TAG in d.tags]
    if fish:
        lines.append(f"{FISH_LABEL} on {_join(fish)}")
    return lines


def subject(week: Week) -> str:
    """'Week 36: VEGANSK on Monday, FISKEDAG on Friday'."""
    lines = headline_lines(week)
    if not lines:
        return f"Week {week.number}: no veggie or fish day"
    return f"Week {week.number}: " + ", ".join(lines)


def body(week: Week) -> str:
    """Plain-text version, kept as the fallback part of the email."""
    parts = [f"Canteen menu for {week.label} ({week.week_number}).", ""]
    for day in week.days:
        stamp = day.date.strftime("%d/%m") if day.date else ""
        parts.append(f"  {day.name_en} {stamp}".rstrip())
        for dish in day.dishes:
            prefix = f"[{'/'.join(dish.tags)}] " if dish.tags else ""
            parts.append(f"    - {prefix}{dish.title}")
    parts += ["", MENU_LINK]
    return "\n".join(parts)


def _badge(tag: str, small: bool = False) -> str:
    background, color = TAG_COLORS.get(tag, DEFAULT_COLORS)
    padding = "1px 6px" if small else "3px 10px"
    size = "11px" if small else "12px"
    return (
        f'<span style="display:inline-block;background:{background};color:{color};'
        f"font-size:{size};font-weight:700;letter-spacing:.04em;padding:{padding};"
        f'border-radius:4px;white-space:nowrap;">{escape(tag)}</span>'
    )


def html_body(week: Week) -> str:
    """HTML version. Styles are inline because mail clients drop <style> blocks."""
    days = []
    for day in week.days:
        dishes = []
        for dish in day.dishes:
            badges = "".join(_badge(tag, small=True) + " " for tag in dish.tags)
            dishes.append(
                '<div style="font-size:14px;line-height:1.5;color:#3d413a;padding:3px 0;">'
                f"{badges}{escape(dish.title)}</div>"
            )
        stamp = day.date.strftime("%d/%m") if day.date else ""
        highlight = "background:#fbfcfa;" if day.tags else ""
        days.append(
            f'<tr><td style="{highlight}padding:12px 14px;border-top:1px solid #ecefe8;">'
            '<div style="font-size:13px;font-weight:700;color:#1b1c1a;'
            'letter-spacing:.03em;text-transform:uppercase;padding-bottom:4px;">'
            f'{escape(day.name_en)} <span style="color:#a2a79b;font-weight:400;">{stamp}</span>'
            f'</div>{"".join(dishes)}</td></tr>'
        )
    week_table = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%">{"".join(days)}</table>'
    )

    return f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f4f6f1;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
       style="background:#f4f6f1;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
       style="max-width:600px;width:100%;background:#ffffff;border:1px solid #e4e8de;
              border-radius:10px;font-family:{FONT};">

<tr><td style="padding:24px 24px 4px 24px;">
  <div style="font-size:12px;font-weight:700;color:#8a8f85;letter-spacing:.08em;
              text-transform:uppercase;">{escape(LOCATION)}</div>
  <div style="font-size:22px;font-weight:700;color:#1b1c1a;padding-top:6px;">
    {escape(week.label)}</div>
  <div style="font-size:14px;color:#8a8f85;padding-top:2px;">Week {escape(week.number)}</div>
</td></tr>

<tr><td style="padding:14px 10px 8px 10px;">{week_table}</td></tr>

<tr><td style="padding:12px 24px 24px 24px;border-top:1px solid #ecefe8;">
  <a href="{MENU_LINK}" style="font-size:13px;color:#5c7a4a;text-decoration:none;">
    See the full menu on foodbycoor.dk &rarr;</a>
</td></tr>

</table>
</td></tr></table>
</body></html>"""
