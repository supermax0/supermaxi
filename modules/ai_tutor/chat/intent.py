"""Deterministic Intent Resolver (exact → alias → fuzzy). The LLM is only a later, optional step."""
from __future__ import annotations

from dataclasses import dataclass, field

from modules.ai_tutor.chat.knowledge import Entry, Knowledge, load
from modules.ai_tutor.chat.normalize import Analysis, analyze, normalize

# Confidence bands (spec §12).
CONFIDENT = 0.85
CLARIFY = 0.60
SIMILAR_HINT = 0.50
AMBIGUITY_MARGIN = 0.10

META_PAGE = "page.explain"
META_ACTIVE_HELP = "active.help"
META_ACTIVE_WHY = "active.why"
META_MEDICAL = "medical.advice"
META_NO_REVERSAL = "payment.no_reversal"  # void an invoice / reverse or delete a payment: no real workflow exists
META_GREETING = "greeting"
META_THANKS = "thanks"
META_IDS = frozenset({META_PAGE, META_ACTIVE_HELP, META_ACTIVE_WHY, META_MEDICAL, META_NO_REVERSAL, META_GREETING, META_THANKS})

MODE_GUIDE, MODE_EXPLAIN, MODE_SHOW_ME = "guide", "explain", "show_me"


@dataclass
class Resolution:
    intent: str | None = None          # entry id | meta id | None
    confidence: float = 0.0
    mode: str = MODE_GUIDE
    source: str = "none"               # exact | alias | fuzzy | meta | choice | ai | none
    candidates: list[tuple[str, float]] = field(default_factory=list)  # best-first, for clarification/hints

    @property
    def is_meta(self) -> bool:
        return self.intent in META_IDS


def detect_mode(a: Analysis) -> str:
    if "q:where" in a.flags or "v:show" in a.flags:
        return MODE_SHOW_ME
    if "q:what" in a.flags or "q:why" in a.flags:
        return MODE_EXPLAIN
    return MODE_GUIDE


def _novelty_factor(content: set[str], known: frozenset) -> float:
    """Words that appear in no alias at all ("واتساب", "رسالة") are evidence the request is about something else."""
    novel = sum(1 for t in content if t.startswith("u:") and t not in known)
    if novel == 0:
        return 1.0
    return 0.95 * 0.8 ** (novel - 1)


def _score(entry: Entry, message_norm: str, content: set[str]) -> tuple[float, str]:
    best, source = 0.0, "alias"
    for alias, alias_set in zip(entry.aliases, entry.alias_sets):
        if normalize(alias) == message_norm:
            return 1.0, "exact"
        inter = len(alias_set & content)
        if not inter:
            continue
        recall = inter / len(alias_set)
        precision = inter / len(content)
        score = 0.7 * recall + 0.3 * precision
        if score > best:
            best, source = score, ("alias" if score >= CONFIDENT else "fuzzy")
    return best, source


def _meta(a: Analysis) -> Resolution | None:
    content = a.content
    if not a.tokens and not a.flags:
        return None
    if "m:reversal" in a.flags:
        return Resolution(META_NO_REVERSAL, 1.0, MODE_EXPLAIN, "meta")
    if "m:medical" in a.flags and "q:where" not in a.flags and "v:add" not in content:
        return Resolution(META_MEDICAL, 1.0, MODE_EXPLAIN, "meta")
    if content and content <= {"c:page"} and ("c:page" in content):
        return Resolution(META_PAGE, 0.97, MODE_EXPLAIN, "meta")
    if content and content <= {"c:problem"}:
        return Resolution(META_ACTIVE_WHY, 0.95, MODE_EXPLAIN, "meta")
    if content <= {"v:add"} and ("n:now" in a.flags or ({"q:what", "q:how"} & a.flags)) and "v:add" in content:
        return Resolution(META_ACTIVE_HELP, 0.95, MODE_EXPLAIN, "meta")
    if not content and "g:thanks" in a.flags:
        return Resolution(META_THANKS, 1.0, MODE_EXPLAIN, "meta")
    if not content and "g:hello" in a.flags:
        return Resolution(META_GREETING, 1.0, MODE_EXPLAIN, "meta")
    return None


def _same_family(first: Entry, second: Entry) -> bool:
    """A feature and its own page (or two entries of one tutorial) are one answer, not an ambiguity."""
    if first.tutorial and first.tutorial == second.tutorial:
        return True
    return first.page == second.page and "page" in (first.kind, second.kind)


def resolve(message: str, knowledge: Knowledge | None = None) -> Resolution:
    kb = knowledge or load()
    a = analyze(message, set(kb.vocabulary))
    meta = _meta(a)
    medical = meta if meta and meta.intent == META_MEDICAL else None
    if meta and not medical:
        return meta
    content = a.content
    if not content:
        return Resolution(mode=detect_mode(a))

    message_norm = normalize(message)
    novelty = _novelty_factor(content, kb.alias_tokens)
    scored = []
    for entry in kb.entries.values():
        score, source = _score(entry, message_norm, content)
        if source != "exact":
            score *= novelty
        if score > 0:
            if entry.kind == "page" and "v:add" in content:
                score *= 0.85  # "add X" asks for an action, not a page tour
            scored.append((score, source, entry))
    # Ties go to the lesson's own entry ("treatment_plan.create") over a helper entry that shares its lesson.
    scored.sort(key=lambda row: (-row[0], row[2].kind != "feature", row[2].id != row[2].tutorial, row[2].id))
    mode = detect_mode(a)
    if medical and not (scored and scored[0][0] >= CONFIDENT and scored[0][2].kind == "feature"):
        return medical  # a medical word counts as advice-seeking unless the sentence is clearly a feature of this system
    if not scored:
        return Resolution(mode=mode)

    best_score, best_source, best = scored[0]
    rivals = [(s, e) for s, _, e in scored[1:] if s >= CLARIFY and best_score - s < AMBIGUITY_MARGIN and not _same_family(best, e)]
    candidates = [(best.id, round(best_score, 3))] + [(e.id, round(s, 3)) for s, e in rivals]
    if rivals and best_score >= CLARIFY:
        return Resolution(None, best_score, mode, best_source, candidates)
    if best_score >= CONFIDENT:
        return Resolution(best.id, best_score, mode, best_source, candidates)
    if best_score >= CLARIFY:
        return Resolution(None, best_score, mode, best_source, candidates)  # single mid-confidence → "did you mean?"
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= SIMILAR_HINT and best_score - second >= 0.2:
        return Resolution(None, best_score, mode, "none", candidates)  # only a clear near-miss is offered as a hint
    return Resolution(None, best_score, mode, "none", [])


def known_ids(knowledge: Knowledge | None = None) -> set[str]:
    return set((knowledge or load()).entries) | set(META_IDS)
