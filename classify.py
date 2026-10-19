"""Fallback tagging for weeks the canteen forgot to tag.

Normally the site writes VEGAN / VEGETARIAN / FISH DAY as an ALL-CAPS prefix on
the dish title and `veggie_menu` just reads them off. When a whole week comes
back with no prefix anywhere, we ask a local language model to read the main
dish - the first line of each weekday - instead.

The model runs on the GitHub Actions runner itself, through Ollama on
localhost. No API key, no account, no per-call cost. See the README for the
workflow steps that install it.

The model is never asked for the label. It is asked only what the dish
*contains*, which is the part a small model is reliable at; the label is then
derived in `_tag` by rule. Measured on a set of real menu lines, asking a 3B
model for the label directly produced confident nonsense ("Moussaka" -> VEGAN);
asking for ingredients and deriving the label does not. See the README.

The guard is deliberately all-or-nothing: a single tag anywhere in the week
means the site is still tagging, so we trust it and never ask. That way the
model can't contradict the canteen, and an ordinary week costs nothing.

Nothing here raises. Every failure comes back as a warning string with the week
left untagged, so a broken runner still gets the menu out.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from veggie_menu import Week

DEFAULT_HOST = "http://localhost:11434"
MODEL = "qwen3.5:9b"

# A 9B model on a 4-core runner has to load ~7.6GB off disk, read the prompt and
# then generate. A couple of minutes is normal; the ceiling is for a bad day.
TIMEOUT = 600

# Backstop over the model's own free-text answer. It sometimes lists an
# ingredient correctly and then fails to set the matching flag - "anchovy, egg,
# parmesan" with fish=false is a real observed answer. Only meat and fish are
# rescued this way: those are the errors that would announce a veggie day that
# isn't one. A missed dairy word only moves VEGAN <-> VEGETARIAN, and both are
# announced as a VEGGIE day, so guessing there would risk more than it fixes.
MEAT_WORDS = (
    "meat beef pork lamb veal chicken poultry turkey duck bacon ham sausage "
    "salami chorizo pepperoni prosciutto porchetta mince minced meatball "
    "frikadelle gelatine gelatin lard"
).split()
FISH_WORDS = (
    "fish anchovy anchovies salmon tuna cod herring mackerel haddock plaice "
    "trout sardine shrimp prawn crab lobster mussel clam squid shellfish surimi"
).split()

SYSTEM = """\
You are given the main dish of one day on a Danish workplace canteen menu.
Report what it contains. Do not label the dish; report facts.

Give:

- animal_products: the meat, fish, dairy and egg the dish contains, comma
  separated, or "none". Use what the dish traditionally contains even when only
  its name is given: a moussaka contains lamb and bechamel, a carbonara contains
  egg and pork, a lasagne contains beef and cheese, a caesar salad contains
  anchovy, egg and parmesan, porchetta is pork.
- meat: true if it contains any meat or poultry, including stock, bacon or ham.
- fish: true if it contains fish or shellfish, including anchovy and fish sauce.
- dairy_or_egg: true if it contains milk, cream, butter, cheese, yoghurt,
  mayonnaise or egg. Coconut milk and other plant milks do not count.

Judge the dish as it would be served, not by the words in its name. Dishes are
often named after what they imitate: "Chili sin carne" and "vegan sausages"
contain no meat, while a "veggie burger with bacon" does contain meat. If the
dish is described as vegan, every field is false."""

FIELDS = ("animal_products", "meat", "fish", "dairy_or_egg")

_FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        # Order matters: Ollama constrains decoding to this schema, so naming
        # the ingredients first makes the model recall them before committing
        # to the booleans that depend on them.
        "animal_products": {"type": "string"},
        "meat": {"type": "boolean"},
        "fish": {"type": "boolean"},
        "dairy_or_egg": {"type": "boolean"},
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}


def _schema() -> dict:
    """The JSON schema for one dish.

    Ollama compiles this into a decoding grammar, so the model cannot omit a
    field or return a non-boolean where a boolean belongs.
    """
    return dict(_FACTS_SCHEMA)


def _mentions(text: str, words) -> bool:
    return bool(re.search(r"\b(%s)\b" % "|".join(words), text, re.I))


def _tag(facts: dict) -> str | None:
    """Derive the label from the reported ingredients. None means no themed day."""
    text = facts["animal_products"]
    if facts["meat"] or _mentions(text, MEAT_WORDS):
        return None
    if facts["fish"] or _mentions(text, FISH_WORDS):
        return "FISH DAY"
    if facts["dairy_or_egg"]:
        return "VEGETARIAN"
    return "VEGAN"


def _prompt(title: str) -> str:
    return f"Report what this dish contains.\n\n{title}"


def _ollama_chat(request: dict, host: str | None = None, timeout: int = TIMEOUT) -> str:
    """POST to Ollama's /api/chat and return the assistant's message content."""
    host = host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
    call = urllib.request.Request(
        host.rstrip("/") + "/api/chat",
        data=json.dumps(request).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(call, timeout=timeout) as response:
        body = json.load(response)
    return body["message"]["content"]


def _parse(content: str) -> dict:
    """Validate one dish's reported facts.

    Strict on purpose: the schema should already guarantee this shape, so
    anything else means the grammar wasn't applied and the answer is not
    trustworthy.
    """
    try:
        facts = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"reply was not JSON: {error}") from None
    if not isinstance(facts, dict):
        raise ValueError(f"expected a JSON object, got {type(facts).__name__}")
    for field in FIELDS:
        if field not in facts:
            raise ValueError(f"reply is missing {field}")
    if not isinstance(facts["animal_products"], str):
        raise ValueError("animal_products is not a string")
    for field in ("meat", "fish", "dairy_or_egg"):
        if not isinstance(facts[field], bool):
            raise ValueError(f"{field} is not a boolean")
    return facts


def apply_fallback(week: Week, call=None, model: str | None = None) -> str | None:
    """Tag `week` in place if the site tagged nothing. Returns a warning or None.

    `call` takes the request dict and returns the reply text; tests pass a stub
    so they never need a running Ollama.
    """
    if any(dish.tags for day in week.days for dish in day.dishes):
        return None  # the site is still tagging; trust it

    pairs = [(day.name, day.dishes[0].title) for day in week.days if day.dishes]
    if not pairs:
        return None

    model = model or os.environ.get("OLLAMA_MODEL") or MODEL
    ask = call or _ollama_chat

    # One request per dish. Asking about the whole week at once is measurably
    # worse: the model's answer for one dish gets contaminated by its
    # neighbours ("Baked salmon" came back with no fish when batched, and
    # correctly when asked alone). Separate requests cost nothing extra in
    # wall time - each one is tiny and the model stays loaded between them.
    tags: dict[str, str | None] = {}
    try:
        for name, title in pairs:
            request = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": _prompt(title)},
                ],
                "stream": False,
                # Qwen3.5 reasons before answering by default. On a CPU runner
                # that costs minutes per dish, and the schema already makes it
                # name the ingredients before the flags, which is the part of
                # the reasoning that matters.
                "think": False,
                "format": _schema(),
                # Deterministic: the same menu always produces the same email.
                "options": {"temperature": 0, "num_predict": 200},
            }
            tags[name] = _tag(_parse(ask(request)))
    except Exception as error:  # connection refused, timeout, bad reply - all the same
        return (
            f"Could not classify the menu ({type(error).__name__}: {error}); "
            "sending it untagged."
        )

    # Only reached once every day answered cleanly, so the week is never half-tagged.
    for day in week.days:
        tag = tags.get(day.name)
        if tag and day.dishes:
            day.dishes[0].tags = [tag]
    return None
