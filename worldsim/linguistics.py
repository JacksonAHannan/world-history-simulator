"""Original compact languages, ordered sound rules, dated loans and etymologies."""
from __future__ import annotations

import copy
import re

from .config import RandomStreams

MEANINGS = ("water", "river", "stone", "hill", "forest", "field", "home", "people", "sun", "moon",
            "fire", "grain", "fish", "tree", "hand", "eye", "one", "two", "three", "mother", "father",
            "child", "walk", "see", "carry", "eat", "sleep", "give", "good", "large", "small", "cold")
SOUND_RULES = (("p", "b", "intervocalic"), ("t", "d", "intervocalic"),
               ("k", "g", "intervocalic"), ("s", "h", "anywhere"),
               ("e", "i", "anywhere"), ("o", "u", "anywhere"))
FEATURES = {"p": "voiceless bilabial stop", "b": "voiced bilabial stop", "t": "voiceless alveolar stop",
            "d": "voiced alveolar stop", "k": "voiceless velar stop", "g": "voiced velar stop",
            "m": "voiced bilabial nasal", "n": "voiced alveolar nasal", "s": "voiceless alveolar fricative",
            "h": "voiceless glottal fricative", "l": "voiced alveolar lateral", "r": "voiced alveolar trill",
            "w": "voiced labiovelar approximant", "a": "open unrounded vowel", "i": "close front unrounded vowel",
            "u": "close back rounded vowel", "e": "mid front unrounded vowel", "o": "mid back rounded vowel"}


def word(rng: RandomStreams, language: dict, entity: int, domain: str = "word") -> str:
    consonants, vowels = language["consonants"], language["vowels"]
    result = ""
    for syllable in range(2+(rng.draw(domain, entity, slot=6) > .7)):
        result += consonants[int(rng.draw(domain, entity, slot=syllable*2)*len(consonants))]
        result += vowels[int(rng.draw(domain, entity, slot=syllable*2+1)*len(vowels))]
    if rng.draw(domain, entity, slot=7) < .25:
        result += "n"
    return result


def create_language(rng: RandomStreams, lid: int, year: int = 0) -> dict:
    consonants = ["p", "t", "k", "m", "n", "s", "l"]
    if rng.draw("inventory", lid) > .4:
        consonants.append("r")
    if rng.draw("inventory", lid, slot=1) > .6:
        consonants.append("w")
    vowels = ["a", "i", "u"] if rng.draw("vowels", lid) < .4 else ["a", "e", "i", "o", "u"]
    lang = {"id": lid, "name": "", "founded": year, "parents": [], "consonants": consonants,
            "vowels": vowels, "phonotactics": "CV syllables; optional final n; no clusters",
            "stress": "penultimate syllable; monosyllables stressed", "tone": "none",
            "grammar": {"word_order": ["SOV", "SVO", "VSO"][int(rng.draw("word-order", lid)*3)],
                        "morphology": ["isolating", "agglutinative"][int(rng.draw("morphology", lid)*2)],
                        "case": "unmarked subject; optional object particle",
                        "plural": "separate plural particle", "negation": "preverbal particle"},
            "writing": [], "usage_domains": ["household", "exchange"], "lexicon": {},
            "sound_rules": [], "contact_sources": [], "historical_names": []}
    lang["name"] = word(rng, lang, lid+5000, "language-name").capitalize()
    used = set()
    for index, meaning in enumerate(MEANINGS):
        entity, form = lid*100+index, ""
        for attempt in range(100):
            form = word(rng, lang, entity+attempt*10000)
            if form not in used:
                break
        used.add(form)
        lang["lexicon"][meaning] = {"form": form, "root": f"root:{lid}:{meaning}", "formation": "native root",
                                   "origin_language": lid, "history": [{"year": year, "form": form}]}
    return lang


def place_name(language: dict, feature: str, ordinal: int = 0) -> tuple[str, dict]:
    head = language["lexicon"][feature]["form"]
    modifier_meaning = ("sun", "stone", "forest", "large", "good", "moon", "water")[ordinal % 7]
    modifier = language["lexicon"][modifier_meaning]["form"]
    form = modifier+head
    return form.capitalize(), {"meaning": f"{modifier_meaning} {feature}", "formation": "modifier + head compound",
                               "language": language["id"], "year": language["founded"], "forms": [modifier, head]}


def sound_change(language: dict, rule: tuple[str, str, str], year: int) -> tuple[dict, dict]:
    source, target, environment = rule
    new = copy.deepcopy(language)
    changed = {}
    for meaning, entry in new["lexicon"].items():
        before = entry["form"]
        after = (re.sub(f"(?<=[aeiou]){source}(?=[aeiou])", target, before)
                 if environment == "intervocalic" else before.replace(source, target))
        if after != before:
            changed[meaning] = {"before": before, "after": after}
            entry["form"] = after
            entry["history"].append({"year": year, "form": after, "rule": f"{source}>{target}/{environment}"})
    if changed:
        inventory = new["vowels"] if source in "aeiou" else new["consonants"]
        if target not in inventory:
            inventory.append(target)
        if not any(source in v["form"] for v in new["lexicon"].values()):
            if source in inventory:
                inventory.remove(source)
        new["sound_rules"].append({"year": year, "source": source, "target": target, "environment": environment})
    return new, changed


def adapt_loan(form: str, recipient: dict) -> str:
    allowed = recipient["consonants"]+recipient["vowels"]
    replacements = {"b": "p", "d": "t", "g": "k", "h": "s", "e": "i", "o": "u", "r": "l", "w": "m"}
    return "".join(c if c in allowed else replacements.get(c, recipient["consonants"][0]) for c in form)


def intelligibility(a: dict, b: dict) -> dict:
    if a["id"] == b["id"]:
        return {"score": 1., "shared_roots": 1., "regular_correspondence": 1., "grammar_similarity": 1., "heuristic": True}
    shared = sum(a["lexicon"][m]["root"] == b["lexicon"][m]["root"] for m in MEANINGS)/len(MEANINGS)
    same_forms = sum(a["lexicon"][m]["form"] == b["lexicon"][m]["form"] for m in MEANINGS)/len(MEANINGS)
    grammar = sum(a["grammar"][k] == b["grammar"][k] for k in a["grammar"])/len(a["grammar"])
    correspondence = .7*shared+.3*same_forms
    return {"score": round(.5*shared+.3*correspondence+.2*grammar, 4), "shared_roots": shared,
            "regular_correspondence": correspondence, "grammar_similarity": grammar,
            "heuristic": True, "note": "Model similarity, not a universal language/dialect threshold."}


def phonology_valid(language: dict) -> bool:
    c, v = "".join(language["consonants"]), "".join(language["vowels"])
    pattern = re.compile(f"(?:[{c}][{v}])+n?$")
    return all(pattern.fullmatch(entry["form"]) for entry in language["lexicon"].values())
