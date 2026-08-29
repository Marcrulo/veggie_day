"""Fetch the canteen menu and email the veggie/fish days to the mailing list.

Run locally to preview:
    python notify.py --dry-run

Send (SMTP_PASSWORD is the only thing not in this repo):
    python notify.py
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import message
import veggie_menu

# --- Configuration ---------------------------------------------------------
# Everything here is safe to keep in the repo. The password is not: it comes
# from the SMTP_PASSWORD environment variable (a GitHub Actions secret).
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587  # 587 = STARTTLS, 465 = implicit TLS
SMTP_USER = "mpautomation123@gmail.com"
MAIL_FROM = SMTP_USER  # Gmail rewrites From to the authenticated account anyway

# One address per line; '#' starts a comment. Edit this file to change the list.
RECIPIENTS_FILE = Path(__file__).resolve().parent / "recipients.txt"
# ---------------------------------------------------------------------------


def recipients(path: Path | str = RECIPIENTS_FILE) -> list[str]:
    """Read the mailing list, ignoring blank lines and # comments."""
    addresses = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        address = line.split("#", 1)[0].strip()
        if address and address not in addresses:
            addresses.append(address)
    return addresses


def send(subject: str, text: str, to: list[str], html: str | None = None) -> None:
    host = os.environ.get("SMTP_HOST", SMTP_HOST)
    port = int(os.environ.get("SMTP_PORT", SMTP_PORT))
    user = os.environ.get("SMTP_USER", SMTP_USER)
    sender = os.environ.get("MAIL_FROM", MAIL_FROM) or user
    # Gmail displays app passwords in groups of four ("abcd efgh ijkl mnop");
    # the spaces are presentation only and must not be sent.
    password = "".join(os.environ.get("SMTP_PASSWORD", "").split())
    if user and not password:
        if not sys.stdin.isatty():
            raise SystemExit("SMTP_PASSWORD is not set (add it as a GitHub Actions secret).")
        password = "".join(getpass.getpass(f"SMTP password for {user}: ").split())

    mail = EmailMessage()
    mail["Subject"] = subject
    mail["From"] = sender
    # Recipients go in Bcc so the list is not exposed to everyone.
    mail["To"] = sender
    mail["Bcc"] = ", ".join(to)
    mail.set_content(text)
    if html:
        # multipart/alternative: clients that cannot render HTML show `text`.
        mail.add_alternative(html, subtype="html")

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
        default="auto",
        help="auto (default) picks the tab holding next Monday; or force 0 / 1",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the email instead of sending")
    parser.add_argument("--json", action="store_true", help="dump the parsed menu as JSON and exit")
    parser.add_argument(
        "--skip-if-empty",
        action="store_true",
        help="send nothing if the week has no VEGAN/VEGETARIAN day",
    )
    parser.add_argument(
        "--html-out",
        metavar="PATH",
        help="write the HTML email to a file to preview it in a browser",
    )
    parser.add_argument("--file", help="parse a saved HTML file instead of fetching (for testing)")
    parser.add_argument(
        "--to",
        action="append",
        help="send to this address instead of recipients.txt (repeatable; for testing)",
    )
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            week = veggie_menu.parse(handle.read())
    elif args.week == "auto":
        try:
            week = veggie_menu.get_upcoming_week()
        except LookupError as error:
            print(error, file=sys.stderr)
            return 1
    else:
        week = veggie_menu.get_week(active_week=int(args.week))

    if not week.days:
        print("No menu found on the page - the site layout may have changed.", file=sys.stderr)
        return 1

    # Only reachable when a tab was forced with --week 0/1; --week auto selects
    # by date and fails loudly instead.
    if week.monday and week.monday <= date.today() and not args.file and args.week != "auto":
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
                    "headlines": message.headline_lines(week),
                    "days": [
                        {
                            "day": day.name,
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
    html = message.html_body(week)

    if args.skip_if_empty and not message.headline_lines(week):
        print("Nothing tagged this week; skipping.")
        return 0

    if args.html_out:
        Path(args.html_out).write_text(html, encoding="utf-8")
        print(f"Wrote {args.html_out} - open it in a browser to preview.")
        return 0

    if args.dry_run:
        print(f"Subject: {subject}\n\n{text}")
        return 0

    to = args.to or recipients()
    if not to:
        print(f"{RECIPIENTS_FILE.name} has no addresses - nothing to send.", file=sys.stderr)
        return 1

    send(subject, text, to, html=html)
    print(f"Sent '{subject}' to {len(to)} recipient(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
