"""Framework-based question banks (SOCRATES / OPQRST), bilingual EN/PL.

Used in two places:
* the deterministic `mock` provider, which emulates differential-guided questioning with an
  internal working list of hypotheses (never shown, never persisted), and
* the static fallback questionnaire when the LLM is unavailable (graceful degradation).

Hypothesis labels below are internal identifiers for question selection. They never appear in
any API response; tests/eval/test_leakage.py checks that.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable


def norm(text: str) -> str:
    """Lowercase, strip diacritics (incl. Polish ł), collapse whitespace."""
    t = text.lower().replace("ł", "l")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


@dataclass(frozen=True)
class Opt:
    en: str
    pl: str


@dataclass
class Slot:
    id: str
    label: str  # doctor-facing label (English)
    type: str  # free | single | multi | scale
    q_en: str
    q_pl: str
    options: list[Opt] = field(default_factory=list)
    discriminates: list[str] = field(default_factory=list)
    core: bool = False  # always asked (framework minimum)

    def text(self, lang: str) -> str:
        return self.q_pl if lang == "pl" else self.q_en

    def option_labels(self, lang: str) -> list[str]:
        return [o.pl if lang == "pl" else o.en for o in self.options]

    def canonical(self, value: str) -> str:
        """Map a displayed option (EN or PL) back to its canonical English value."""
        n = norm(value)
        for o in self.options:
            if n in (norm(o.en), norm(o.pl)):
                return o.en
        return value.strip()


@dataclass
class Hypothesis:
    id: str
    applies: Callable[[dict], bool] = lambda ctx: True


@dataclass
class Rule:
    """If answer for `slot` satisfies `test`, set `hyp` to `status`."""
    slot: str
    test: Callable[[str | list[str]], bool]
    hyp: str
    status: str = "unlikely"


@dataclass
class Category:
    id: str
    subject_en: str
    slots: list[Slot]
    hypotheses: list[Hypothesis] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    extractors: list[tuple[str, str, str]] = field(default_factory=list)  # (regex on normalised text, slot, canonical value)


ONSET = Slot("onset", "Onset", "single", "When did it start?", "Kiedy to się zaczęło?", [
    Opt("Less than a week ago", "Mniej niż tydzień temu"),
    Opt("1–2 weeks ago", "1–2 tygodnie temu"),
    Opt("About 3 weeks ago", "Około 3 tygodni temu"),
    Opt("More than a month ago", "Ponad miesiąc temu"),
])

SEVERITY = Slot("severity", "Impact (0–10)", "scale",
                "How much is it bothering you day to day, from 0 (not at all) to 10 (the worst)?",
                "Jak bardzo to Panu/Pani przeszkadza na co dzień, od 0 (wcale) do 10 (najgorzej)?",
                core=True)

ONSET_EXTRACT = [
    (r"\b(three|3) weeks|\btrzy tygodn|\b3 tygodn", "onset", "About 3 weeks ago"),
    (r"\b(a|one|1|two|2) weeks?\b|\btydzien|\bdwa tygodnie|\b2 tygodnie", "onset", "1–2 weeks ago"),
    (r"\b(a|one|two|several) months?\b|\bmiesiac", "onset", "More than a month ago"),
    (r"\b(few|couple of|two|three) days\b|\bkilka dni\b|\byesterday\b|\bwczoraj", "onset", "Less than a week ago"),
]


def _has(v, *needles: str) -> bool:
    vals = v if isinstance(v, list) else [v]
    return any(n.lower() in str(x).lower() for x in vals for n in needles)


def _lacks(v, *needles: str) -> bool:
    return not _has(v, *needles)


def _ctx_has_side_effect(*terms: str) -> Callable[[dict], bool]:
    def f(ctx: dict) -> bool:
        for r in ctx.get("records", []):
            effects = " ".join(r.get("details", {}).get("product_info_side_effects", []))
            if any(t in effects for t in terms):
                return True
        return False
    return f


def _ctx_smoker(ctx: dict) -> bool:
    for r in ctx.get("records", []):
        if r.get("kind") == "lifestyle" and r.get("details", {}).get("topic") == "smoking":
            v = r["details"].get("value", "").lower()
            return "former" in v or "current" in v or "smok" in v and "never" not in v
    return False


RESPIRATORY = Category(
    id="respiratory",
    subject_en="cough",
    slots=[
        ONSET,
        Slot("character", "Character", "single", "Is the cough dry, or do you cough anything up?",
             "Czy kaszel jest suchy, czy coś Pan/Pani odkrztusza?", [
                 Opt("Dry", "Suchy"), Opt("Clear mucus", "Przejrzysta wydzielina"),
                 Opt("Yellow or green mucus", "Żółta lub zielona wydzielina"), Opt("Blood", "Krew")],
             discriminates=["lower_resp", "med_effect", "post_infectious"]),
        Slot("timing", "Timing", "single", "Is there a time of day when it's worse?",
             "Czy jest pora dnia, kiedy jest gorzej?", [
                 Opt("At night", "W nocy"), Opt("In the morning", "Rano"),
                 Opt("After physical effort", "Po wysiłku"), Opt("No pattern", "Bez reguły")],
             discriminates=["reflux", "asthma_like", "med_effect"]),
        Slot("assoc", "Other symptoms", "multi", "Have you noticed any of these as well? Choose all that apply.",
             "Czy zauważył(a) Pan/Pani coś z poniższych? Proszę wybrać wszystkie pasujące.", [
                 Opt("Fever", "Gorączka"), Opt("Runny or blocked nose", "Katar lub zatkany nos"),
                 Opt("Heartburn", "Zgaga"), Opt("Wheezing", "Świszczący oddech"),
                 Opt("Hoarse voice", "Chrypka"), Opt("None of these", "Nic z tych rzeczy")],
             discriminates=["reflux", "asthma_like", "lower_resp", "post_infectious"]),
        Slot("sob", "Breathlessness", "single", "Do you get out of breath?", "Czy brakuje Panu/Pani tchu?", [
                 Opt("No", "Nie"), Opt("Only on stairs or when hurrying", "Tylko na schodach lub przy pośpiechu"),
                 Opt("Yes, even when resting", "Tak, nawet w spoczynku")],
             discriminates=["asthma_like", "lower_resp"]),
        Slot("changes", "Recent changes", "single",
             "In the two months before it started, did anything change? For example new medicines, a cold, or a new place.",
             "Czy w ciągu dwóch miesięcy przed początkiem coś się zmieniło? Na przykład nowe leki, przeziębienie lub nowe miejsce.", [
                 Opt("Started a new medicine", "Zacząłem/zaczęłam nowy lek"), Opt("Had a cold", "Byłem/byłam przeziębiony(a)"),
                 Opt("Moved home or changed job", "Przeprowadzka lub nowa praca"),
                 Opt("Nothing I can think of", "Nic takiego nie pamiętam")],
             discriminates=["med_effect", "post_infectious", "exposure"]),
        SEVERITY,
    ],
    hypotheses=[
        Hypothesis("post_infectious"), Hypothesis("lower_resp"), Hypothesis("reflux"), Hypothesis("asthma_like"),
        Hypothesis("exposure"), Hypothesis("med_effect", _ctx_has_side_effect("cough")),
        Hypothesis("smoking_related", _ctx_smoker),
    ],
    rules=[
        Rule("character", lambda v: _has(v, "Dry"), "lower_resp"),
        Rule("character", lambda v: _has(v, "Yellow"), "med_effect"),
        Rule("assoc", lambda v: _lacks(v, "Heartburn"), "reflux"),
        Rule("assoc", lambda v: _lacks(v, "Wheezing"), "asthma_like"),
        Rule("assoc", lambda v: _lacks(v, "Fever"), "lower_resp"),
        Rule("assoc", lambda v: _lacks(v, "Runny", "Fever"), "post_infectious"),
        Rule("changes", lambda v: _lacks(v, "cold"), "post_infectious"),
        Rule("changes", lambda v: _lacks(v, "Moved"), "exposure"),
        Rule("sob", lambda v: _has(v, "No"), "asthma_like"),
    ],
    extractors=ONSET_EXTRACT + [
        (r"\bdry\b|\bsuch", "character", "Dry"),
        (r"\bnight|\bw nocy|\bnoca\b", "timing", "At night"),
        (r"\bmorning|\brano\b", "timing", "In the morning"),
    ],
)

MUSCULOSKELETAL = Category(
    id="musculoskeletal",
    subject_en="pain",
    slots=[
        Slot("location", "Location", "single", "Where exactly is the pain?", "Gdzie dokładnie boli?", [
            Opt("Front, around the kneecap", "Z przodu, wokół rzepki"), Opt("Inner side", "Po wewnętrznej stronie"),
            Opt("Outer side", "Po zewnętrznej stronie"), Opt("Back", "Z tyłu"), Opt("All over the joint", "Cały staw")],
            discriminates=["overuse_front", "ligament", "meniscal", "tendon"], core=True),
        ONSET,
        Slot("mechanism", "How it started", "single", "How did it start?", "Jak to się zaczęło?", [
            Opt("After a fall or twist", "Po upadku lub skręceniu"), Opt("Came on gradually", "Stopniowo"),
            Opt("Suddenly, without injury", "Nagle, bez urazu")],
            discriminates=["ligament", "meniscal", "overuse_front", "inflammatory"]),
        Slot("character", "Character", "single", "What does the pain feel like?", "Jaki to ból?", [
            Opt("Dull ache", "Tępy"), Opt("Sharp", "Ostry"), Opt("Burning", "Piekący"), Opt("Throbbing", "Pulsujący")],
            discriminates=["tendon", "overuse_front"]),
        Slot("aggravating", "Worse with", "multi", "What makes it worse? Choose all that apply.",
             "Co nasila ból? Proszę wybrać wszystkie pasujące.", [
                 Opt("Running", "Bieganie"), Opt("Going down stairs", "Schodzenie po schodach"),
                 Opt("Sitting for a long time", "Długie siedzenie"), Opt("Kneeling or squatting", "Klękanie lub przysiad"),
                 Opt("Nothing in particular", "Nic szczególnego")],
             discriminates=["overuse_front", "meniscal", "tendon"]),
        Slot("swelling", "Swelling, locking, giving way", "multi", "Have you noticed any of these? Choose all that apply.",
             "Czy zauważył(a) Pan/Pani coś z poniższych? Proszę wybrać wszystkie pasujące.", [
                 Opt("Swelling", "Obrzęk"), Opt("Locking or catching", "Blokowanie lub przeskakiwanie"),
                 Opt("Giving way", "Uciekanie kolana"), Opt("Warmth or redness", "Ocieplenie lub zaczerwienienie"),
                 Opt("None of these", "Nic z tych rzeczy")],
             discriminates=["meniscal", "ligament", "inflammatory"]),
        Slot("activity_change", "Activity change", "single", "Did anything change in your activity before it started?",
             "Czy przed początkiem zmieniła się Pana/Pani aktywność?", [
                 Opt("Increased my training", "Zwiększyłem/am treningi"), Opt("Started a new sport", "Nowy sport"),
                 Opt("New shoes or surface", "Nowe buty lub nawierzchnia"), Opt("No change", "Bez zmian")],
             discriminates=["overuse_front", "tendon"]),
        Slot("relief", "Relief", "single", "What helps?", "Co przynosi ulgę?", [
            Opt("Rest helps", "Odpoczynek"), Opt("Painkillers help a bit", "Leki przeciwbólowe trochę pomagają"),
            Opt("Nothing helps", "Nic nie pomaga")], discriminates=["inflammatory"]),
        Slot("severity", "Impact (0–10)", "scale", "At its worst, how bad is it, from 0 (no pain) to 10 (the worst)?",
             "W najgorszym momencie, jak silny jest ból, od 0 (brak) do 10 (najgorszy)?", core=True),
    ],
    hypotheses=[Hypothesis("overuse_front"), Hypothesis("ligament"), Hypothesis("meniscal"), Hypothesis("tendon"),
                Hypothesis("inflammatory")],
    rules=[
        Rule("mechanism", lambda v: _lacks(v, "fall"), "ligament"),
        Rule("mechanism", lambda v: _has(v, "fall"), "overuse_front"),
        Rule("location", lambda v: _lacks(v, "Front"), "overuse_front"),
        Rule("swelling", lambda v: _lacks(v, "Locking", "Giving"), "meniscal"),
        Rule("swelling", lambda v: _lacks(v, "Warmth"), "inflammatory"),
    ],
    extractors=ONSET_EXTRACT + [
        (r"\b(front|kneecap)\b|\brzepk|\bz przodu", "location", "Front, around the kneecap"),
        (r"\bgradual|\bstopniow", "mechanism", "Came on gradually"),
    ],
)

HEADACHE = Category(
    id="headache",
    subject_en="headache",
    slots=[
        ONSET,
        Slot("character", "Character", "single", "What does the headache feel like?", "Jaki to ból głowy?", [
            Opt("Throbbing", "Pulsujący"), Opt("Pressing or tight", "Uciskający"), Opt("Stabbing", "Kłujący"),
            Opt("Hard to describe", "Trudno opisać")], discriminates=["primary_a", "primary_b"]),
        Slot("location", "Location", "single", "Where is it?", "Gdzie boli?", [
            Opt("One side", "Po jednej stronie"), Opt("Both sides", "Obustronnie"), Opt("Forehead", "Czoło"),
            Opt("Back of the head", "Tył głowy")], discriminates=["primary_a", "primary_b", "bp_related"]),
        Slot("timing", "Timing", "single", "When is it worst?", "Kiedy jest najgorzej?", [
            Opt("In the morning", "Rano"), Opt("Later in the day", "Później w ciągu dnia"), Opt("No pattern", "Bez reguły")],
            discriminates=["bp_related", "sleep_related", "primary_b"]),
        Slot("assoc", "Other symptoms", "multi", "Have you noticed any of these as well? Choose all that apply.",
             "Czy zauważył(a) Pan/Pani coś z poniższych? Proszę wybrać wszystkie pasujące.", [
                 Opt("Nausea", "Nudności"), Opt("Sensitivity to light", "Nadwrażliwość na światło"),
                 Opt("Changes in vision", "Zmiany widzenia"), Opt("Neck stiffness", "Sztywność karku"),
                 Opt("None of these", "Nic z tych rzeczy")], discriminates=["primary_a"]),
        Slot("triggers", "Possible triggers", "single", "Does anything seem to bring it on?", "Czy coś go wywołuje?", [
            Opt("Stress", "Stres"), Opt("Screen work", "Praca przy ekranie"), Opt("Poor sleep", "Słaby sen"),
            Opt("Alcohol", "Alkohol"), Opt("Nothing I can think of", "Nic takiego")],
            discriminates=["sleep_related", "primary_b", "med_overuse"]),
        Slot("painkillers", "Painkiller use", "single", "How often do you take painkillers for it?",
             "Jak często bierze Pan/Pani na to leki przeciwbólowe?", [
                 Opt("Rarely", "Rzadko"), Opt("1–2 days a week", "1–2 dni w tygodniu"),
                 Opt("3 or more days a week", "3 lub więcej dni w tygodniu")], discriminates=["med_overuse"]),
        SEVERITY,
    ],
    hypotheses=[Hypothesis("primary_a"), Hypothesis("primary_b"), Hypothesis("bp_related"), Hypothesis("sleep_related"),
                Hypothesis("med_overuse")],
    rules=[
        Rule("assoc", lambda v: _lacks(v, "Nausea", "light"), "primary_a"),
        Rule("painkillers", lambda v: _has(v, "Rarely"), "med_overuse"),
        Rule("triggers", lambda v: _lacks(v, "sleep"), "sleep_related"),
    ],
    extractors=ONSET_EXTRACT + [(r"\bmorning|\brano\b", "timing", "In the morning")],
)

GENERAL = Category(
    id="general",
    subject_en="complaint",
    slots=[
        ONSET,
        Slot("location", "Location", "free", "Where in your body do you notice it most?",
             "W którym miejscu ciała odczuwa Pan/Pani to najbardziej?", core=True),
        Slot("character", "Character", "single", "How would you describe it?", "Jak by Pan/Pani to opisał(a)?", [
            Opt("Aching", "Pobolewanie"), Opt("Sharp", "Ostry"), Opt("Burning", "Pieczenie"),
            Opt("Tiredness or weakness", "Zmęczenie lub osłabienie"), Opt("Hard to describe", "Trudno opisać")], core=True),
        Slot("timing", "Timing", "single", "Is it there all the time, or does it come and go?",
             "Czy jest cały czas, czy pojawia się i znika?", [
                 Opt("All the time", "Cały czas"), Opt("Comes and goes", "Pojawia się i znika"),
                 Opt("Mostly at night", "Głównie w nocy")], core=True),
        Slot("aggravating", "What changes it", "free", "Does anything make it better or worse?",
             "Czy coś to łagodzi albo nasila?", core=True),
        Slot("assoc", "Other symptoms", "multi", "Have you noticed any of these as well? Choose all that apply.",
             "Czy zauważył(a) Pan/Pani coś z poniższych? Proszę wybrać wszystkie pasujące.", [
                 Opt("Fever", "Gorączka"), Opt("Nausea", "Nudności"), Opt("Tiredness", "Zmęczenie"),
                 Opt("Dizziness", "Zawroty głowy"), Opt("Weight loss", "Utrata wagi"), Opt("None of these", "Nic z tych rzeczy")],
             core=True),
        SEVERITY,
    ],
    extractors=ONSET_EXTRACT,
)

CATEGORIES: dict[str, Category] = {c.id: c for c in (RESPIRATORY, MUSCULOSKELETAL, HEADACHE, GENERAL)}
CATEGORIES["abdominal"] = GENERAL  # framework questionnaire covers it in the hackathon build


def complaint_slot(lang: str, first_name: str, doctor: str) -> dict:
    text = (f"Dzień dobry, {first_name}. Proszę opisać własnymi słowami, z czym zgłasza się Pan/Pani na wizytę ({doctor})."
            if lang == "pl" else
            f"Hi {first_name}. In your own words, what would you like to talk to {doctor} about?")
    return {"slot": "complaint", "text": text, "answer_type": "free", "options": []}


def slot_by_id(category: str, slot_id: str) -> Slot | None:
    cat = CATEGORIES.get(category, GENERAL)
    return next((s for s in cat.slots if s.id == slot_id), None)


def extract_from_text(category: str, text: str) -> list[tuple[str, str]]:
    """Deterministic extraction of framework answers from free text (e.g. a voice answer)."""
    cat = CATEGORIES.get(category, GENERAL)
    n = norm(text)
    found: dict[str, str] = {}
    for rx, slot, value in cat.extractors:
        if slot not in found and re.search(rx, n):
            found[slot] = value
    return list(found.items())
