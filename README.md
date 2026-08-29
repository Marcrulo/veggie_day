# veggie_day

Scrapes the Coor canteen week menu for **Lautrupbjerg 7** and emails a mailing list
which days are marked `VEGANSK`, `VEGETARISK` or `FISKEDAG`.

Source: <https://gn.foodbycoor.dk/lautrupbjerg-7/da/ugemenu>

Python 3.9+, standard library only — no dependencies to install.

## Quick start

```bash
python notify.py --dry-run                 # next week's email as plain text
python notify.py --html-out preview.html   # the HTML mail, open it in a browser
python notify.py --json                    # parsed menu as JSON
python notify.py --week 0 --dry-run        # force a tab instead of auto-picking
python -m unittest discover -s tests
LIVE=1 python -m unittest tests.test_menu.TestLive   # also hits the real site
```

The subject carries the announcements; the body is just the week's menu, with the
tags marked in place. Only `VEGANSK` and `VEGETARISK` are announced, together as
one **VEGGIE day** (a day tagged both ways is named once), with multiple days
joined: `VEGGIE day on Monday and Wednesday`. `FISKEDAG` is intentionally *not*
in the subject — it still appears as a badge on its dish in the menu.

Example output:

```
Subject: Week 36: VEGGIE day on Monday

Canteen menu for 31. august - 4. september 2026 (Uge 36).

  Monday 31/08
    - [VEGETARISK] Risotto med svampe, løg, hvidvin og parmesan...
```

## How the scraping works

The page is server-rendered, so no browser is needed. The two tabs are
`?active_week=0` and `?active_week=1`, but **which one holds next week depends on
the day you ask** — so nothing assumes a tab number. `get_upcoming_week()` works
out the coming Monday's date, fetches a tab, and checks the date in the heading
against it, trying the other tab if it doesn't match. If neither holds that week
the job fails with both dates in the message rather than mailing the wrong week.
`--week 0` / `--week 1` still force a specific tab for debugging.

Each `<div class="day">` holds a Danish day name and one `element title` div per
dish. Themed days are written as an **ALL-CAPS prefix** on the dish title:

```
VEGANSK        Ratatouille af squash, peberfrugt og tomat
```

So the tag match is case-sensitive and anchored to the start of the title. That
matters: `Vegansk Chili sin carne` and `Vegetarisk biksemad` are just dish names
and are deliberately *not* counted as themed days. There is a test for this.

Dates aren't in the markup per day, only the range in the heading
(`31. august - 4. september 2026`), so dates are derived from that Monday plus
the weekday offset. Saturday and Sunday appear as empty day divs and are skipped;
some weeks are Mon–Thu only.

If the site's markup changes, `notify.py` exits non-zero with
"No menu found on the page", so the workflow fails loudly instead of sending a
blank email.

## Files

| File | Purpose |
| --- | --- |
| `veggie_menu.py` | Fetch + parse into `Week` / `Day` / `Dish` |
| `message.py` | Subject, plain-text body and HTML body — **edit the wording and colours here** |
| `notify.py` | CLI: fetch, format, send over SMTP |
| `recipients.txt` | The mailing list — **edit this to add people** |
| `tests/` | Unit tests against saved HTML fixtures |
| `.github/workflows/weekly-menu-email.yml` | Sunday cron |

## GitHub setup

The repo is private, so everything except the password lives in the code:

| What | Where |
| --- | --- |
| SMTP server, port, account, From | `SMTP_HOST` … `MAIL_FROM` at the top of `notify.py` |
| Mailing list | `recipients.txt` |
| **App password** | GitHub secret `SMTP_PASSWORD` — the only secret |

Add it under Settings → Secrets and variables → Actions → New repository secret,
named `SMTP_PASSWORD`. For Gmail that is a 16-character
[App Password](https://myaccount.google.com/apppasswords), which requires
2-Step Verification on the account; the normal login password is rejected. Gmail
shows it in groups of four — any spaces are stripped before use.

Every setting also accepts an environment variable of the same name as an
override, which is handy for testing without editing the file.

### Changing the mailing list

Edit `recipients.txt`, commit, push. One address per line, `#` starts a comment,
duplicates and blank lines are dropped. Everyone is **Bcc**'d, so recipients
never see each other's addresses. No secret to update, and the diff shows who
was added or removed.

### Testing before you schedule it

```bash
python notify.py --dry-run                 # print the email, send nothing
python notify.py --to you@example.com      # real send, ignores recipients.txt
```

The second prompts for the password (hidden, not stored in shell history) unless
`SMTP_PASSWORD` is set.

Then run it from the Actions tab: **Run workflow** with `dry_run: true` prints
the email into the job log without sending. Untick it to send for real. The
scheduled run always sends.

The schedule is `0 15 * * 0` (Sunday 15:00 UTC). GitHub's cron can drift by up to
~15 minutes on busy hours — fine for this.

## Adjusting things

- **Wording** — `VEGGIE_LABEL`, `subject()`, `body()` and `html_body()` in
  `message.py`. Preview with `--html-out preview.html`.
- **Which tags are announced** — `VEGGIE_TAGS` in `message.py`. Tags in
  `veggie_menu.TAGS` that are not listed there are shown in the menu but never
  in the subject, which is how `FISKEDAG` is handled.
- **Badge colours** — `TAG_COLORS` in `message.py`, `(background, text)` per tag.
- **Only mail when there's something to announce** — add `--skip-if-empty` to the
  send step; otherwise a week with no veggie day still gets a "no VEGGIE day" mail.
- **Another canteen** — change `MENU_URL` in `veggie_menu.py`; the other
  Lautrupbjerg locations use the same layout.
- **More tags** — add to `TAGS` in `veggie_menu.py` and `TAG_LABELS` in
  `message.py`.

## The email itself

Sent as `multipart/alternative`: an HTML part styled with inline CSS (mail
clients discard `<style>` blocks) and the plain-text version as the fallback.
Layout is old-fashioned nested tables on purpose — that is what survives Outlook.
Everything from the site is HTML-escaped on the way in. It comes out around 6 KB,
well under Gmail's 102 KB clipping limit.
