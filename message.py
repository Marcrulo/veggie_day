"""Turn a parsed week into the email subject and body."""

from __future__ import annotations

from veggie_menu import TAGS, Week

# How each tag is announced. Tweak the wording here.
TAG_LABELS = {
    "VEGANSK": "VEGANSK",
    "VEGETARISK": "VEGETARISK",
    "FISKEDAG": "FISKEDAG",
}

MENU_LINK = "https://gn.foodbycoor.dk/lautrupbjerg-7/da/ugemenu"


def headlines(week: Week) -> list[str]:
    """The one-liners, e.g. 'VEGANSK on Wednesday'."""
    lines = []
    for tag in TAGS:
        for day in week.days_with(tag):
            lines.append(f"{TAG_LABELS[tag]} on {day.name_en}")
    return lines


def subject(week: Week) -> str:
    lines = headlines(week)
    if not lines:
        return f"Canteen menu {week.week_number}: no veggie or fish day"
    return f"{week.week_number}: " + ", ".join(lines)


def body(week: Week) -> str:
    parts = [f"Canteen menu for {week.label} ({week.week_number}).", ""]

    lines = headlines(week)
    if lines:
        parts += [line for line in lines]
    else:
        parts.append("No VEGANSK, VEGETARISK or FISKEDAG marked this week.")
    parts.append("")

    parts.append("Full week:")
    for day in week.days:
        stamp = day.date.strftime("%d/%m") if day.date else ""
        parts.append(f"  {day.name_en} {stamp}".rstrip())
        for dish in day.dishes:
            prefix = f"[{'/'.join(dish.tags)}] " if dish.tags else ""
            parts.append(f"    - {prefix}{dish.title}")
    parts += ["", MENU_LINK]
    return "\n".join(parts)
