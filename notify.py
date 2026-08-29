"""Fetch the canteen menu and email the veggie/fish days to the mailing list.

Run locally to preview:
    python notify.py --dry-run

Send (needs the SMTP_* / MAIL_* environment variables):
    python notify.py
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage

import message
import veggie_menu


def recipients() -> list[str]:
    """MAIL_TO is a comma or newline separated list of addresses."""
    raw = os.environ.get("MAIL_TO", "")
    return [addr.strip() for addr in raw.replace("\n", ",").split(",") if addr.strip()]


def send(subject: str, text: str, to: list[str]) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("MAIL_FROM") or user

    mail = EmailMessage()
    mail["Subject"] = subject
    mail["From"] = sender
    # Recipients go in Bcc so the list is not exposed to everyone.
    mail["To"] = os.environ.get("MAIL_TO_HEADER", sender)
    mail["Bcc"] = ", ".join(to)
    mail.set_content(text)

    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if port != 465:
            server.starttls()
        if user:
            server.login(user, password)
        server.send_message(mail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--week",
        type=int,
        default=1,
        help="0 = current week, 1 = next week (default, for the Sunday run)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the email instead of sending")
    parser.add_argument("--json", action="store_true", help="dump the parsed menu as JSON and exit")
    parser.add_argument(
        "--skip-if-empty",
        action="store_true",
        help="send nothing if the week has no VEGANSK/VEGETARISK/FISKEDAG",
    )
    parser.add_argument("--file", help="parse a saved HTML file instead of fetching (for testing)")
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            week = veggie_menu.parse(handle.read())
    else:
        week = veggie_menu.get_week(active_week=args.week)

    if not week.days:
        print("No menu found on the page - the site layout may have changed.", file=sys.stderr)
        return 1

    # Sanity check for the scheduled run: the site's "next week" tab should point
    # at a week that has not started yet. If this ever warns, the tab numbering
    # rolled over and --week needs adjusting.
    if week.monday and week.monday <= date.today() and not args.file:
        print(
            f"Warning: week {week.week_number} starts {week.monday}, which is not in the future.",
            file=sys.stderr,
        )

    if args.json:
        print(
            json.dumps(
                {
                    "label": week.label,
                    "week_number": week.week_number,
                    "monday": week.monday.isoformat() if week.monday else None,
                    "headlines": message.headlines(week),
                    "days": [
                        {
                            "day": day.name_en,
                            "day_da": day.name_da,
                            "date": day.date.isoformat() if day.date else None,
                            "tags": day.tags,
                            "dishes": [{"title": d.title, "tags": d.tags} for d in day.dishes],
                        }
                        for day in week.days
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    subject = message.subject(week)
    text = message.body(week)

    if args.skip_if_empty and not message.headlines(week):
        print("Nothing tagged this week; skipping.")
        return 0

    if args.dry_run:
        print(f"Subject: {subject}\n\n{text}")
        return 0

    to = recipients()
    if not to:
        print("MAIL_TO is empty - nothing to send to.", file=sys.stderr)
        return 1

    send(subject, text, to)
    print(f"Sent '{subject}' to {len(to)} recipient(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
