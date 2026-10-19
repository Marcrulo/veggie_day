"""Score classify.py's prompt and rule against 56 hand-labelled menu lines.

Not a unit test: it needs a running Ollama and takes minutes. Run it before
changing the model, SYSTEM or the word lists, and compare the summary line.

    python tests/eval_classify.py qwen3.5:9b        # all layers on GPU if any
    python tests/eval_classify.py qwen3.5:9b 4      # cap CPU threads, as a runner

Truth is None (meat), "FISH DAY", "VEGETARIAN" or "VEGAN"; a set means either
answer is acceptable. DANGEROUS counts announced veggie/fish days that aren't.
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import classify  # noqa: E402

V, VG, F, M = "VEGETARIAN", "VEGAN", "FISH DAY", None
CASES = [
    # --- the fixtures (main dishes and alternatives) ---
    ("Chicken in curry with rice and chutney", M),
    ("Vegetarian bisque with fried egg", V),
    ("Thai stir fry with pork and vegetables", M),
    ("Greek potatoes with feta. Eggplant and onion saùte", V),
    ("Ratatouille of squash, bell pepper and tomato. Lentil meatballs", VG),
    ("Vegan Chili sin carne", VG),
    ("Fish lasagna", F),
    ("Risotto with mushrooms, onions, white wine and parmesan. Topped with herbs", V),
    ("Sweet potatoes and chickpeas in spicy curry with coconut milk. Rice", VG),
    ("Chicken burger", M),
    ("Eggplants baked in miso marinade with sesame and spring onions. Rice and vegetables", VG),
    ("Moussaka", M),
    ("Polenta with spinach. Fried vegetables and tomato sauce", {V, VG}),
    ("Roasted potatoes and carrots. Porchetta with herbs and apricots. Sauce", M),
    ("Tortillas with vegan filling and salsa", VG),
    ("Fish, shrimp and vegetables in red curry. Rice", F),
    ("Spicy cauliflower gratin with lentils, parsley and lemon. Potatoes and dip", V),
    # --- meat, including hidden and imitation traps ---
    ("Spaghetti bolognese", M),
    ("Veggie burger with bacon", M),
    ("Coq au vin", M),
    ("French onion soup with cheese croutons", M),  # beef stock
    ("Spaghetti carbonara", M),
    ("Quiche Lorraine with green salad", M),
    ("Chili con carne with rice", M),
    ("Beef stroganoff with mashed potatoes", M),
    ("Wiener schnitzel with peas and potatoes", M),
    ("Pulled pork burger with coleslaw", M),
    ("Ramen with chashu and soft-boiled egg", M),
    ("Frikadeller with potatoes and brown sauce", M),
    ("Stegt flæsk med persillesovs", M),
    ("Biksemad with fried egg and pickled beetroot", M),
    ("Lasagne", M),
    ("Hot dog with remoulade and crispy onions", M),
    ("Vegetable soup with meatballs and dumplings", M),
    # --- fish ---
    ("Fish and chips with tartar sauce", F),
    ("Salmon with hollandaise and new potatoes", F),
    ("Tuna pasta salad", F),
    ("Smørrebrød with pickled herring", F),
    ("Fiskefrikadeller with remoulade and rye bread", F),
    ("Pasta puttanesca", F),  # anchovies
    # --- vegetarian ---
    ("Mushroom stroganoff with rice", V),
    ("Mac and cheese", V),
    ("Shakshuka with bread", V),
    ("Spinach quiche", V),
    ("Pizza margherita", V),
    ("Gnocchi with gorgonzola sauce and walnuts", V),
    ("Cauliflower schnitzel with remoulade", V),
    ("Halloumi salad with grilled vegetables", V),
    ("Burrito with black beans, rice and cheese", V),
    # --- vegan, including imitation names ---
    ("Falafel with hummus and pita", VG),
    ("Gazpacho with bread", VG),
    ("Tofu in teriyaki sauce with rice", VG),
    ("Jackfruit 'pulled pork' burger with vegan mayo", VG),
    ("Pasta with vegan bolognese", VG),
    ("Vegetable spring rolls with sweet chili sauce", VG),
    ("Lentil soup with coconut milk and coriander", VG),
]


def group(tag):
    return "VEGGIE" if tag in (V, VG) else tag


def main():
    model = sys.argv[1]
    threads = int(sys.argv[2]) if len(sys.argv) > 2 else None
    opts = {"temperature": 0, "num_predict": 200}
    if threads:
        opts["num_thread"] = threads
    exact = grouped = danger = missed = 0
    t0 = time.time()
    rows = []
    for title, truth in CASES:
        req = {
            "model": model,
            "messages": [
                {"role": "system", "content": classify.SYSTEM},
                {"role": "user", "content": classify._prompt(title)},
            ],
            "stream": False, **({"think": False} if model.startswith("qwen3") else {}), "format": classify._schema(), "options": opts,
        }
        s = time.time()
        facts = classify._parse(classify._ollama_chat(req))
        got = classify._tag(facts)
        ok = truth if isinstance(truth, set) else {truth}
        e = got in ok
        g = group(got) in {group(t) for t in ok}
        # Dangerous: announcing a veggie (or fish) day that isn't one.
        d = group(got) in ("VEGGIE", F) and group(got) not in {group(t) for t in ok}
        mi = not g and not d
        exact += e; grouped += g; danger += d; missed += mi
        flag = "DANGER" if d else ("miss" if mi else ("~" if not e else ""))
        rows.append(f"{time.time()-s:6.1f}s {flag:6} {str(got):10} want {str(truth):10} {title}  | {facts['animal_products']}")
    total = time.time() - t0
    print("\n".join(rows))
    n = len(CASES)
    print(f"\n{model}: exact {exact}/{n}, right day-type {grouped}/{n}, "
          f"DANGEROUS {danger}, missed {missed}, {total:.0f}s total, {total/n:.1f}s/dish")


main()
