"""Tests for the LLM fallback that tags a week the site left untagged.

Nothing here starts Ollama. `classify.apply_fallback` takes the transport as an
argument, so every test hands it a stub that returns a canned reply - or raises,
or is asserted never to have been called at all.

The one exception is TestLive at the bottom, skipped unless OLLAMA_LIVE=1.
"""

import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import classify  # noqa: E402
import message  # noqa: E402
import notify  # noqa: E402
import veggie_menu  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def load(name):
    return veggie_menu.parse((FIXTURES / name).read_text(encoding="utf-8"))


def facts(animal_products="none", meat=False, fish=False, dairy_or_egg=False):
    """One dish's reported ingredients, as the model would return them."""
    return json.dumps(
        {
            "animal_products": animal_products,
            "meat": meat,
            "fish": fish,
            "dairy_or_egg": dairy_or_egg,
        }
    )


class FakeCall:
    """Stands in for classify._ollama_chat.

    One request is made per dish, so `reply` may be a single string reused for
    every dish, or a list consumed in order. `error` is raised instead if set.
    Records every request so tests can assert on the prompt and the schema.
    """

    def __init__(self, reply="", error=None):
        self.reply = reply
        self.error = error
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if isinstance(self.reply, list):
            return self.reply[len(self.requests) - 1]
        return self.reply


# Monday vegetarian, Friday fish, the rest meat - matching week37-untagged.html.
ALL_FIVE = [
    facts("parmesan", dairy_or_egg=True),
    facts("chicken", meat=True),
    facts("beef", meat=True),
    facts("pork", meat=True),
    facts("fish, shrimp", fish=True),
]

NOTHING = facts()  # no animal products at all -> VEGAN


class TestTriggering(unittest.TestCase):
    """The fallback runs only when the site tagged nothing at all."""

    def test_tagged_week_is_left_alone_and_costs_nothing(self):
        week = load("week36.html")
        call = FakeCall(reply=ALL_FIVE)
        self.assertIsNone(classify.apply_fallback(week, call=call))
        self.assertEqual(call.requests, [], "must not ask the model on a tagged week")
        self.assertEqual([d.name for d in week.days_with("VEGAN")], ["Monday"])

    def test_partially_tagged_week_is_left_alone(self):
        """One tag anywhere is enough to trust the site for the whole week."""
        week = load("week37-untagged.html")
        week.days[4].dishes[0].tags = ["FISH DAY"]
        call = FakeCall(reply=ALL_FIVE)
        self.assertIsNone(classify.apply_fallback(week, call=call))
        self.assertEqual(call.requests, [])

    def test_empty_week_is_left_alone(self):
        week = veggie_menu.parse("<html><body>nothing here</body></html>")
        call = FakeCall(reply=ALL_FIVE)
        self.assertIsNone(classify.apply_fallback(week, call=call))
        self.assertEqual(call.requests, [])

    def test_one_request_per_weekday(self):
        week = load("week37-untagged.html")
        call = FakeCall(reply=ALL_FIVE)
        classify.apply_fallback(week, call=call)
        self.assertEqual(len(call.requests), 5, "one request per day, not one per week")

    def test_a_short_week_asks_only_about_its_days(self):
        week = load("week35.html")  # Mon-Thu only
        for day in week.days:
            for dish in day.dishes:
                dish.tags = []
        call = FakeCall(reply=NOTHING)
        classify.apply_fallback(week, call=call)
        self.assertEqual(len(call.requests), 4)


class TestRequest(unittest.TestCase):
    def requests_for(self, week, reply=ALL_FIVE):
        call = FakeCall(reply=reply)
        classify.apply_fallback(week, call=call)
        return call.requests

    def test_each_request_carries_exactly_one_dish(self):
        requests = self.requests_for(load("week37-untagged.html"))
        prompts = [r["messages"][1]["content"] for r in requests]
        self.assertIn("Chicken burger", prompts[1])
        # Tuesday's second dish must never be sent - only line one counts.
        for prompt in prompts:
            self.assertNotIn("Eggplants baked in miso", prompt)
        # One dish per prompt, so Monday's dish is not in Tuesday's request.
        self.assertNotIn("Risotto", prompts[1])

    def test_first_dish_of_each_day_is_the_one_sent(self):
        requests = self.requests_for(load("week37-untagged.html"))
        self.assertIn("Risotto with mushrooms", requests[0]["messages"][1]["content"])
        self.assertIn("Fish, shrimp", requests[4]["messages"][1]["content"])

    def test_model_and_streaming(self):
        request = self.requests_for(load("week37-untagged.html"))[0]
        self.assertEqual(request["model"], "qwen3.5:9b")
        self.assertIs(request["stream"], False, "we read one whole reply, not a stream")

    def test_thinking_is_off(self):
        """Reasoning tokens cost minutes per dish on a CPU runner."""
        request = self.requests_for(load("week37-untagged.html"))[0]
        self.assertIs(request["think"], False)

    def test_deterministic_sampling(self):
        """The same menu must always produce the same email."""
        request = self.requests_for(load("week37-untagged.html"))[0]
        self.assertEqual(request["options"]["temperature"], 0)

    def test_schema_asks_for_facts_not_a_label(self):
        schema = self.requests_for(load("week37-untagged.html"))[0]["format"]
        self.assertEqual(
            sorted(schema["required"]),
            ["animal_products", "dairy_or_egg", "fish", "meat"],
        )
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["meat"]["type"], "boolean")
        self.assertEqual(schema["properties"]["animal_products"]["type"], "string")

    def test_ingredients_are_generated_before_the_booleans(self):
        """Property order is generation order under a decoding grammar."""
        schema = self.requests_for(load("week37-untagged.html"))[0]["format"]
        self.assertEqual(list(schema["properties"])[0], "animal_products")

    def test_days_without_dishes_are_skipped(self):
        week = load("week37-untagged.html")
        week.days[2].dishes = []
        call = FakeCall(reply=NOTHING)
        self.assertIsNone(classify.apply_fallback(week, call=call))
        self.assertEqual(len(call.requests), 4)
        for request in call.requests:
            self.assertNotIn("Moussaka", request["messages"][1]["content"])

    def test_model_can_be_overridden(self):
        week = load("week37-untagged.html")
        call = FakeCall(reply=ALL_FIVE)
        classify.apply_fallback(week, call=call, model="llama3.2:3b")
        self.assertEqual(call.requests[0]["model"], "llama3.2:3b")




class TestTag(unittest.TestCase):
    """The label is derived in Python, not chosen by the model."""

    def tag(self, **kwargs):
        return classify._tag(json.loads(facts(**kwargs)))

    def test_meat_wins(self):
        self.assertIsNone(self.tag(animal_products="beef, cheese", meat=True, dairy_or_egg=True))

    def test_fish_beats_dairy(self):
        self.assertEqual(
            self.tag(animal_products="cod, butter", fish=True, dairy_or_egg=True), "FISH DAY"
        )

    def test_dairy_is_vegetarian(self):
        self.assertEqual(self.tag(animal_products="parmesan", dairy_or_egg=True), "VEGETARIAN")

    def test_nothing_is_vegan(self):
        self.assertEqual(self.tag(), "VEGAN")

    def test_meat_word_rescues_a_missed_flag(self):
        """Observed: the model lists an ingredient then forgets to set the flag."""
        self.assertIsNone(self.tag(animal_products="bacon", meat=False))

    def test_fish_word_rescues_a_missed_flag(self):
        self.assertEqual(
            self.tag(animal_products="anchovy, egg, parmesan", fish=False, dairy_or_egg=True),
            "FISH DAY",
        )

    def test_backstop_is_case_insensitive(self):
        self.assertIsNone(self.tag(animal_products="Porchetta"))

    def test_backstop_matches_whole_words_only(self):
        """'ham' must not fire on 'hammered', nor 'cod' on 'codfish-free'."""
        self.assertEqual(self.tag(animal_products="hammered tofu"), "VEGAN")

    def test_coconut_milk_is_not_dairy(self):
        """The backstop deliberately does not guess at dairy."""
        self.assertEqual(self.tag(animal_products="coconut milk"), "VEGAN")

    def test_none_text_is_vegan(self):
        self.assertEqual(self.tag(animal_products="none"), "VEGAN")


class TestApplyingTags(unittest.TestCase):
    def test_tags_land_on_the_right_days(self):
        week = load("week37-untagged.html")
        self.assertIsNone(classify.apply_fallback(week, call=FakeCall(reply=ALL_FIVE)))
        self.assertEqual([d.name for d in week.days_with("VEGETARIAN")], ["Monday"])
        self.assertEqual([d.name for d in week.days_with("FISH DAY")], ["Friday"])
        self.assertEqual([d.name for d in week.days_with("VEGAN")], [])

    def test_tag_goes_on_the_first_dish_only(self):
        week = load("week37-untagged.html")
        classify.apply_fallback(week, call=FakeCall(reply=ALL_FIVE))
        monday = week.days[0]
        self.assertEqual(monday.dishes[0].tags, ["VEGETARIAN"])
        self.assertEqual(monday.dishes[1].tags, [])

    def test_a_meat_day_stays_untagged(self):
        week = load("week37-untagged.html")
        classify.apply_fallback(week, call=FakeCall(reply=ALL_FIVE))
        self.assertEqual(week.days[1].tags, [])

    def test_titles_are_not_modified(self):
        week = load("week37-untagged.html")
        classify.apply_fallback(week, call=FakeCall(reply=ALL_FIVE))
        self.assertEqual(
            week.days[0].dishes[0].title.split(".")[0],
            "Risotto with mushrooms, onions, white wine and parmesan",
        )

    def test_the_email_reads_exactly_like_a_scraped_week(self):
        """Downstream code cannot tell inferred tags from scraped ones."""
        week = load("week37-untagged.html")
        classify.apply_fallback(week, call=FakeCall(reply=ALL_FIVE))
        self.assertEqual(message.subject(week), "🥦🚨 Week 37: VEGGIE day on Monday")
        self.assertIn("[VEGETARIAN]", message.body(week))
        self.assertIn("[FISH DAY]", message.body(week))
        self.assertIn("VEGETARIAN", message.html_body(week))

    def test_two_veggie_days_are_joined(self):
        week = load("week37-untagged.html")
        reply = [
            facts("none"),  # Monday  -> VEGAN
            facts("chicken", meat=True),  # Tuesday -> untagged
            facts("cheese", dairy_or_egg=True),  # Wednesday -> VEGETARIAN
            facts("pork", meat=True),  # Thursday -> untagged
            facts("beef", meat=True),  # Friday -> untagged
        ]
        classify.apply_fallback(week, call=FakeCall(reply=reply))
        self.assertEqual(
            message.subject(week), "🥦🚨 Week 37: VEGGIE day on Monday and Wednesday"
        )


class TestReplyParsing(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(
            classify._parse(facts("parmesan", dairy_or_egg=True)),
            {"animal_products": "parmesan", "meat": False, "fish": False, "dairy_or_egg": True},
        )

    def test_not_json_is_rejected(self):
        with self.assertRaises(ValueError):
            classify._parse("Monday: VEGAN")

    def test_json_that_is_not_an_object_is_rejected(self):
        with self.assertRaises(ValueError):
            classify._parse('["beef"]')

    def test_missing_field_is_rejected(self):
        with self.assertRaises(ValueError):
            classify._parse('{"animal_products": "beef", "meat": true, "fish": false}')

    def test_non_boolean_flag_is_rejected(self):
        with self.assertRaises(ValueError):
            classify._parse(
                '{"animal_products": "beef", "meat": "yes", "fish": false, "dairy_or_egg": false}'
            )

    def test_non_string_ingredients_is_rejected(self):
        with self.assertRaises(ValueError):
            classify._parse(
                '{"animal_products": 1, "meat": false, "fish": false, "dairy_or_egg": false}'
            )

    def test_empty_reply_is_rejected(self):
        with self.assertRaises(ValueError):
            classify._parse("")


class TestFailureModes(unittest.TestCase):
    """Every failure warns and leaves the week untagged - it never raises."""

    def assertUntagged(self, week, warning):
        self.assertIsNotNone(warning, "a failure must produce a warning")
        self.assertEqual([d.tags for d in week.days], [[] for _ in week.days])

    def test_ollama_not_running(self):
        week = load("week37-untagged.html")
        error = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        warning = classify.apply_fallback(week, call=FakeCall(error=error))
        self.assertUntagged(week, warning)
        self.assertIn("Connection refused", warning)

    def test_timeout(self):
        week = load("week37-untagged.html")
        warning = classify.apply_fallback(week, call=FakeCall(error=TimeoutError("timed out")))
        self.assertUntagged(week, warning)
        self.assertIn("timed out", warning)

    def test_model_not_pulled(self):
        week = load("week37-untagged.html")
        error = urllib.error.HTTPError(
            "http://localhost:11434/api/chat", 404, 'model "qwen3.5:9b" not found', {}, None
        )
        warning = classify.apply_fallback(week, call=FakeCall(error=error))
        self.assertUntagged(week, warning)

    def test_garbage_reply(self):
        week = load("week37-untagged.html")
        warning = classify.apply_fallback(
            week, call=FakeCall(reply="I'm afraid I can't help with that.")
        )
        self.assertUntagged(week, warning)

    def test_malformed_ollama_envelope(self):
        """A 200 that isn't the shape we expect must not raise."""
        week = load("week37-untagged.html")
        warning = classify.apply_fallback(week, call=FakeCall(error=KeyError("message")))
        self.assertUntagged(week, warning)

    def test_one_bad_day_discards_the_whole_week(self):
        """All days or none - never a half-tagged week."""
        week = load("week37-untagged.html")
        reply = [
            facts("none"),  # Monday would have been VEGAN
            facts("chicken", meat=True),
            "not json at all",  # Wednesday fails
            facts("pork", meat=True),
            facts("fish", fish=True),
        ]
        warning = classify.apply_fallback(week, call=FakeCall(reply=reply))
        self.assertUntagged(week, warning)

    def test_failure_on_the_last_day_still_discards_everything(self):
        week = load("week37-untagged.html")
        reply = ALL_FIVE[:4] + ["{}"]
        warning = classify.apply_fallback(week, call=FakeCall(reply=reply))
        self.assertUntagged(week, warning)


class TestTransport(unittest.TestCase):
    """_ollama_chat builds the right HTTP request and reads Ollama's envelope."""

    def fake_urlopen(self, captured, payload):
        import io
        from contextlib import contextmanager

        @contextmanager
        def opener(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            yield io.BytesIO(json.dumps(payload).encode("utf-8"))

        return opener

    def call(self, payload, **kwargs):
        captured = {}
        original = classify.urllib.request.urlopen
        classify.urllib.request.urlopen = self.fake_urlopen(captured, payload)
        try:
            result = classify._ollama_chat({"model": "qwen3.5:9b"}, **kwargs)
        finally:
            classify.urllib.request.urlopen = original
        return result, captured

    def test_posts_json_to_the_chat_endpoint(self):
        result, captured = self.call({"message": {"content": NOTHING}})
        request = captured["request"]
        self.assertEqual(request.full_url, "http://localhost:11434/api/chat")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(json.loads(request.data)["model"], "qwen3.5:9b")
        self.assertEqual(result, NOTHING)

    def test_host_override_and_trailing_slash(self):
        _, captured = self.call(
            {"message": {"content": "{}"}}, host="http://ollama.internal:1234/"
        )
        self.assertEqual(captured["request"].full_url, "http://ollama.internal:1234/api/chat")

    def test_timeout_is_passed_through(self):
        _, captured = self.call({"message": {"content": "{}"}})
        self.assertEqual(captured["timeout"], classify.TIMEOUT)


class TestNotifyIntegration(unittest.TestCase):
    def run_notify(self, argv, call):
        original = classify.apply_fallback
        classify.apply_fallback = lambda week, **kw: original(week, call=call)
        try:
            return notify.main(argv)
        finally:
            classify.apply_fallback = original

    def test_dry_run_shows_the_inferred_tags(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            code = self.run_notify(
                ["--file", str(FIXTURES / "week37-untagged.html"), "--dry-run"],
                FakeCall(reply=ALL_FIVE),
            )
        self.assertEqual(code, 0)
        self.assertIn("VEGGIE day on Monday", out.getvalue())
        self.assertIn("[FISH DAY]", out.getvalue())

    def test_failure_still_sends_and_warns(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.run_notify(
                ["--file", str(FIXTURES / "week37-untagged.html"), "--dry-run"],
                FakeCall(error=RuntimeError("nope")),
            )
        self.assertEqual(code, 0, "a failed classification must not fail the job")
        self.assertIn("no VEGGIE day", out.getvalue())
        self.assertIn("nope", err.getvalue())

    def test_no_llm_flag_skips_the_call(self):
        import io
        from contextlib import redirect_stdout

        call = FakeCall(reply=ALL_FIVE)
        out = io.StringIO()
        with redirect_stdout(out):
            self.run_notify(
                ["--file", str(FIXTURES / "week37-untagged.html"), "--dry-run", "--no-llm"],
                call,
            )
        self.assertEqual(call.requests, [])
        self.assertIn("no VEGGIE day", out.getvalue())

    def test_tagged_week_is_unaffected_end_to_end(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            self.run_notify(
                ["--file", str(FIXTURES / "week36.html"), "--dry-run"],
                FakeCall(reply=ALL_FIVE),
            )
        self.assertIn("VEGGIE day on Monday", out.getvalue())


class TestLive(unittest.TestCase):
    """Really calls Ollama on localhost. Skipped unless OLLAMA_LIVE=1.

    Needs `ollama serve` running and `ollama pull qwen3.5:9b` done.
    """

    def setUp(self):
        if os.environ.get("OLLAMA_LIVE") != "1":
            self.skipTest("set OLLAMA_LIVE=1 with ollama running to run")

    def test_classifies_the_untagged_fixture(self):
        week = load("week37-untagged.html")
        warning = classify.apply_fallback(week)
        self.assertIsNone(warning, warning)
        # Parmesan in the risotto rules out VEGAN; the fish curry is a fish day.
        self.assertEqual(week.days[0].dishes[0].tags, ["VEGETARIAN"])
        self.assertEqual(week.days[4].dishes[0].tags, ["FISH DAY"])
        # Moussaka is lamb, porchetta is pork, a chicken burger is chicken.
        # A 3B model called Moussaka VEGAN, which is what this guards against.
        self.assertEqual(week.days[1].tags, [], "chicken burger is not a themed day")
        self.assertEqual(week.days[2].tags, [], "moussaka is lamb")
        self.assertEqual(week.days[3].tags, [], "porchetta is pork")

    def test_no_veggie_day_is_announced_for_a_week_of_meat(self):
        """The error that matters: never announce a veggie day that isn't one."""
        week = load("week37-untagged.html")
        for i, title in enumerate(
            [
                "Moussaka",
                "Spaghetti bolognese",
                "Veggie burger with bacon",
                "Coq au vin",
                "Roasted potatoes and carrots. Porchetta with herbs. Sauce",
            ]
        ):
            week.days[i].dishes[0].title = title
        self.assertIsNone(classify.apply_fallback(week))
        self.assertEqual(message.headline_lines(week), [])


if __name__ == "__main__":
    unittest.main()
