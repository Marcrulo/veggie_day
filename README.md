# veggie_day

Scrapes the Coor canteen week menu for **Lautrupbjerg 7** and emails a mailing list
which days are marked `VEGAN`, `VEGETARIAN` or `FISH DAY`.

Source: <https://gn.foodbycoor.dk/lautrupbjerg-7/en/weekmenu> (the site's own
English edition — day names, dishes and tags all come through in English)

Python 3.9+, standard library only — no dependencies to install. The LLM
fallback talks to a local Ollama over plain HTTP, so there is no SDK either.

## Quick start

```bash
python notify.py --dry-run                 # next week's email as plain text
python notify.py --html-out preview.html   # the HTML mail, open it in a browser
python notify.py --json                    # parsed menu as JSON
python notify.py --week 0 --dry-run        # force a tab instead of auto-picking
python notify.py --no-llm --dry-run        # never call the LLM fallback
python -m unittest discover -s tests
LIVE=1 python -m unittest tests.test_menu.TestLive   # also hits the real site
OLLAMA_LIVE=1 python -m unittest tests.test_classify.TestLive  # needs ollama running
```

The subject carries the announcements; the body is just the week's menu, with the
tags marked in place. Only `VEGAN` and `VEGETARIAN` are announced, together as
one **VEGGIE day** (a day tagged both ways is named once), with multiple days
joined: `VEGGIE day on Monday and Wednesday`. `FISH DAY` is intentionally *not*
in the subject — it still appears as a badge on its dish in the menu.

Example output:

```
Subject: 🥦🚨 Week 36: VEGGIE day on Monday

Canteen menu for 31. August - 4. September 2026 (Week 36).

  Monday 31/08
    - [VEGETARIAN] Risotto with mushrooms, onions, white wine and parmesan...
    - [VEGAN] Sweet potatoes and chickpeas in spicy curry with coconut milk...
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
VEGAN        Ratatouille of squash, bell pepper and tomato
```

So the tag match is case-sensitive and anchored to the start of the title. That
matters: `Vegan Chili sin carne` and `Vegetarian bisque` are just dish names and
are deliberately *not* counted as themed days. There is a test for this.

Dates aren't in the markup per day, only the range in the heading
(`31. August - 4. September 2026`), so dates are derived from that Monday plus
the weekday offset. Saturday and Sunday appear as empty day divs and are skipped;
some weeks are Mon–Thu only.

If the site's markup changes, `notify.py` exits non-zero with
"No menu found on the page", so the workflow fails loudly instead of sending a
blank email.

## When the site stops writing the tags

The ALL-CAPS prefixes are not guaranteed. When a whole week comes back with no
`VEGAN`, `VEGETARIAN` or `FISH DAY` anywhere, `classify.py` reads the **first
dish of each weekday** — the main dish — and labels it instead. The tags it
produces are ordinary tags: subject line, badges and plain-text body all behave
exactly as they do for a scraped week, and nothing in the email says which of
the two it was.

The model runs **on the Actions runner itself**, via [Ollama](https://ollama.com)
on `localhost:11434`. No API key, no account, no per-call cost, nothing leaves
the runner. The workflow installs Ollama, restores the weights from the Actions
cache and starts the server before running `notify.py`.

The guard is all-or-nothing on purpose:

```python
if any(dish.tags for day in week.days for dish in day.dishes):
    return None   # the site is still tagging; trust it, don't ask
```

One tag anywhere means the site is fine, so a normal week never asks the model.
It also means the model can't contradict the canteen — it only ever fills a
vacuum. The trade-off is that a *partial* format change (the site keeps
`FISH DAY` but drops `VEGAN`) goes unnoticed.

### The model is never asked for the label

This is the part worth understanding before changing anything. Asked directly
for a label, a small model produces confident nonsense: `qwen2.5:3b` labelled
**"Moussaka" as VEGAN** and **"Veggie burger with bacon" as VEGETARIAN**. Both
are false positives — they announce a veggie day that isn't one, so people turn
up to lamb.

So the model is asked only what the dish *contains*, which it is far better at,
and the label is derived by rule in `_tag`:

```json
{"animal_products": "lamb, bechamel", "meat": true, "fish": false, "dairy_or_egg": true}
```

→ `meat` wins → no tag. Then `fish` → `FISH DAY`, then `dairy_or_egg` →
`VEGETARIAN`, else `VEGAN`. Three things make this hold up:

- **Schema property order is generation order.** Ollama compiles the JSON schema
  into a decoding grammar, and `animal_products` comes first, so the model has
  to recall the ingredients *before* committing to the booleans that depend on
  them. The grammar also means it cannot omit a field or return a non-boolean.
- **A keyword backstop** (`MEAT_WORDS`, `FISH_WORDS`) re-reads the model's own
  free text and overrides the flags. `"anchovy, egg, parmesan"` with
  `fish: false` is a real observed answer; the backstop catches it. It covers
  meat and fish only — those are the errors that would announce a veggie day
  falsely. A missed dairy word only moves `VEGAN` ↔ `VEGETARIAN`, and both are
  announced as a VEGGIE day, so guessing there would risk more than it fixes.
- **One request per dish.** Asking about the whole week at once is measurably
  worse: batched, `"Baked salmon with dill"` came back with `fish: false`; asked
  alone it is correct. Separate requests cost nothing in wall time — each is
  tiny and the model stays loaded between them.

### Choosing the model

`tests/eval_classify.py` scores a model against 56 hand-labelled menu lines —
the fixtures plus traps: hidden meat (French onion soup, Frikadeller, Biksemad),
hidden fish (puttanesca), and imitation names (Chili sin carne, jackfruit
"pulled pork"). **Dangerous** counts dishes announced as a veggie or fish day
that aren't one; that is the number to keep at or near zero.

| Model | Size | Right day type | Exact tag | Dangerous |
| --- | --- | --- | --- | --- |
| `qwen2.5:7b` | 4.7 GB | 50/56 | 47/56 | 6 |
| `qwen3:14b` | 9.3 GB | 51/56 | 48/56 | 5 |
| `qwen2.5:14b` | 9.0 GB | 54/56 | 51/56 | 1 |
| **`qwen3.5:9b`** | **7.6 GB** | **55/56** | **54/56** | **1** |

`qwen3.5:9b` is the default: the most accurate and smaller than the 14Bs. Its
one dangerous answer is French onion soup (it missed the beef stock). The
runner — 4 CPUs, 16 GB RAM on a public repo — caps the choice at roughly 14B;
`qwen3:30b-a3b` and the 27B+ Qwen 3.5/3.6 models are 19 GB and up and do not
fit in memory. Qwen 3.x reasons before answering unless told not to, which
costs minutes per dish on a CPU, so requests send `"think": false`.

### The rest of it

- **Model:** `qwen3.5:9b`, ~7.6 GB. Set `OLLAMA_MODEL` in the workflow (or the
  environment) to swap it; `OLLAMA_HOST` points at a different server. Sampling
  is `temperature: 0`, so the same menu always produces the same email.
- **Speed:** CPU only, capped at 4 threads to match the runner: ~110 s for a
  full week cold, ~100 s warm — about 20 s a dish, nearly all of it generation.
  On the Actions runner it measured ~26 s a dish, so an untagged week adds
  ~2–3 minutes. The client timeout
  is 600 s per dish.
- **On failure** — Ollama not running, model not pulled, timeout, unparseable
  reply — the run prints a warning to stderr and sends the menu untagged. The
  job still exits 0: nobody misses the menu because inference had a bad day.
  If *any* day fails, the whole week is discarded rather than half-tagged.
  Watch the log if a "no VEGGIE day" subject looks wrong.
- `--no-llm` skips the fallback entirely.

### Running it locally

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3.5:9b
python notify.py --file tests/fixtures/week37-untagged.html --dry-run
OLLAMA_LIVE=1 python -m unittest tests.test_classify.TestLive
python tests/eval_classify.py qwen3.5:9b   # the 56-dish benchmark
```

The live tests assert the two things that matter: the parmesan risotto is
`VEGETARIAN` and not `VEGAN`, the fish curry is `FISH DAY`, moussaka and
porchetta are left untagged — and a week of five meat dishes produces no veggie
announcement at all.

### Notes on the workflow

- The Ollama setup runs on **every** run, even weeks the site tagged properly,
  because knowing in advance whether it is needed would mean scraping the site
  twice. It costs a few runner minutes a week.
- The weights are cached with `actions/cache`. GitHub evicts caches after 7 days
  without a hit and this job runs every 7 days, so expect the occasional miss —
  it just re-downloads.
- The installer's systemd service is stopped deliberately: it runs as the
  `ollama` user and keeps weights in `/usr/share/ollama`, which would hold the
  port and bypass the cache. The workflow runs its own server as the runner user
  with `OLLAMA_MODELS` pointed at the cached directory.

## Files

| File | Purpose |
| --- | --- |
| `veggie_menu.py` | Fetch + parse into `Week` / `Day` / `Dish` |
| `classify.py` | Local-LLM fallback when the site publishes an untagged week |
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
| LLM fallback | No secret: the model runs on the runner |

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

The schedule is `23 15 * * 0` (Sunday 15:23 UTC, 17:23 Danish summer time). The
odd minute is deliberate: GitHub runs scheduled jobs on shared capacity and can
*drop* them at peak times, and the start of every hour is peak. Expect some drift
regardless. Note that scheduled runs always send — `dry_run` only defaults to
true for the manual button.

## Adjusting things

- **Wording** — `SUBJECT_PREFIX`, `VEGGIE_LABEL`, `subject()`, `body()` and
  `html_body()` in `message.py`. Preview with `--html-out preview.html`.
- **Which tags are announced** — `VEGGIE_TAGS` in `message.py`. Tags in
  `veggie_menu.TAGS` that are not listed there are shown in the menu but never
  in the subject, which is how `FISH DAY` is handled.
- **Badge colours** — `TAG_COLORS` in `message.py`, `(background, text)` per tag.
- **Only mail when there's something to announce** — add `--skip-if-empty` to the
  send step; otherwise a week with no veggie day still gets a "no VEGGIE day" mail.
- **Another canteen** — change `MENU_URL` in `veggie_menu.py`; the other
  Lautrupbjerg locations use the same layout.
- **Back to Danish** — point `MENU_URL` at `/da/ugemenu` and swap `TAGS`,
  `DAY_NAMES` and `MONTHS` in `veggie_menu.py` for the Danish words (the Danish
  page says `VEGANSK` / `VEGETARISK` / `FISKEDAG`, `Mandag`…, `august`…).
- **More tags** — add to `TAGS` in `veggie_menu.py` and `TAG_COLORS` in
  `message.py`. If the LLM fallback should be able to produce the new tag too,
  add it to `VALID` and describe it in `SYSTEM` in `classify.py`.
- **The fallback's judgement** — `SYSTEM`, `MEAT_WORDS` and `FISH_WORDS` in
  `classify.py`; the rule itself is `_tag`. `OLLAMA_LIVE=1 python -m unittest
  tests.test_classify.TestLive` checks it against a real week. A different model
  goes in `OLLAMA_MODEL` in the workflow — run `tests/eval_classify.py` on it
  first; smaller models fail this task in the dangerous direction.

## The email itself

Sent as `multipart/alternative`: an HTML part styled with inline CSS (mail
clients discard `<style>` blocks) and the plain-text version as the fallback.
Layout is old-fashioned nested tables on purpose — that is what survives Outlook.
Everything from the site is HTML-escaped on the way in. It comes out around 6 KB,
well under Gmail's 102 KB clipping limit.
