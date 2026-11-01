"""Compare a resume against a job description.

A simple, transparent heuristic (no network, no ML): it pulls the terms a
job posting leans on (acronyms, standards, tools, repeated words and phrases)
and checks which ones already appear anywhere in the resume text.
Use it as a checklist: add a missing term only if it is true for you.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .model import Resume

STOPWORDS = set("""
a about above across after again against all also am an and any are as at be
because been before being below between both but by can could did do does doing
down during each either etc every few for from further had has have having he
her here hers him his how i if in into is it its itself just least less like
made make many may me might more most much must my need needs new no nor not
now of off on once one only or other our ours out over own per please plus
preferred required requirements responsibilities role same she should so some
such than that the their them then there these they this those through to too
under until up upon us use used using very via was we well were what when where
which while who whom why will with within without would year years you your
ability able candidate company experience excellent strong work working team
including include includes position job looking skills skill knowledge good
great help ensure provide support within across various related based level
opportunity qualifications desired minimum bachelor degree equivalent etc
""".split())

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#&./-]*[A-Za-z0-9+#]|[A-Za-z]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip(" .,;:()")


def _contains(haystack: str, needle: str) -> bool:
    n = _norm(needle)
    if not n:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", haystack) is not None


@dataclass
class MatchReport:
    score: int                                   # 0-100, share of JD terms found
    matched_skills: list[str] = field(default_factory=list)   # your skills the JD mentions
    found_terms: list[str] = field(default_factory=list)      # JD terms already in resume
    missing_terms: list[str] = field(default_factory=list)    # JD terms not in resume


# Standards and versioned names: "ISO 9001", "AISC 360", "API RP 2A", "DNV-RP-C203"
STANDARD = re.compile(r"\b[A-Z]{2,6}(?:[ -][A-Z]{1,4})?[ -]\d[\w.-]*[\w]|\b[A-Z]{2,6}-[A-Z]+-[A-Z]?\d+\b")
SENTENCE_START = re.compile(r"(^|[.!?:;•\n\-–*]\s*)$")


def _is_acronym(raw: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", raw)
    return len(letters) >= 2 and letters.isupper()


def extract_terms(text: str, limit: int = 40) -> list[str]:
    """Key terms from a job description, most important first.

    Picks up: standards/codes with numbers, acronyms, mid-sentence proper
    nouns (tool names), and words or 2-3 word phrases the posting repeats.
    """
    scores: Counter[str] = Counter()
    display: dict[str, str] = {}

    def add(raw: str, weight: int):
        key = raw.lower()
        scores[key] += weight
        display.setdefault(key, raw)

    standards = [m.group(0) for m in STANDARD.finditer(text)]
    for s in standards:
        add(s, 4)
    in_standard = {w.lower() for s in standards for w in re.split(r"[ -]", s)}

    spans = [(m.group(0), m.start()) for m in TOKEN.finditer(text)]
    words = [w for w, _ in spans]
    lows = [w.lower() for w in words]
    for (raw, start), low in zip(spans, lows):
        if low in STOPWORDS or low in in_standard:
            continue
        at_start = bool(SENTENCE_START.search(text[max(0, start - 3):start]))
        if _is_acronym(raw) or re.search(r"[0-9+#&]", raw):
            add(raw, 3)
        elif raw[0].isupper() and not at_start and len(raw) > 2:
            add(raw, 2)           # mid-sentence capital: likely a tool/product
        elif len(low) >= 4:
            add(low, 1)

    def ngrams(n: int):
        for i in range(len(words) - n + 1):
            chunk = lows[i:i + n]
            if any(c in STOPWORDS or len(c) < 3 for c in chunk):
                continue
            yield " ".join(chunk), " ".join(words[i:i + n])

    tri = Counter(k for k, _ in ngrams(3))
    bi = Counter(k for k, _ in ngrams(2))
    for k, raw in ngrams(3):
        if tri[k] >= 2:
            add(raw, 2)
    for k, raw in ngrams(2):
        if bi[k] >= 2 and not any(k in t and tri[t] >= 2 for t in tri):
            add(raw, 2)

    keep = []
    for key, s in scores.most_common():
        raw = display[key]
        if " " not in key and not _is_acronym(raw) and s < 2:
            continue                                   # one-off plain word
        keep.append(key)

    phrases = [k for k in keep if " " in k]
    result = [k for k in keep
              if " " in k or _is_acronym(display[k])
              or not any(k in p.split() for p in phrases)]
    return [display[k] for k in result[:limit]]


def match(resume: Resume, job_description: str) -> MatchReport:
    jd = _norm(job_description)
    text = _norm(resume.full_text())
    if not jd:
        return MatchReport(score=0)

    matched_skills = [s for s in resume.all_skills() if _contains(jd, s)]
    terms = extract_terms(job_description)
    found = [t for t in terms if _contains(text, t)]
    missing = [t for t in terms if t not in found]
    score = round(100 * len(found) / len(terms)) if terms else 0
    return MatchReport(score=score, matched_skills=matched_skills,
                       found_terms=found, missing_terms=missing)
