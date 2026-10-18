"""Knowledge registry: the ONLY facts the chat may state (features, pages, tutorials, setup plan)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from modules.ai_tutor import registry as tutorials
from modules.ai_tutor.chat.normalize import analyze, normalize, _strip_prefix

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


class KnowledgeError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    """A thing the user can ask about: a feature (maybe with a tutorial) or a page."""
    id: str
    kind: str                      # "feature" | "page"
    title_ar: str
    page: str                      # page id where it lives
    target: dict | None            # on-page UI reference ({"action": id} | {"section": id}) or None
    tutorial: str | None
    explain_ar: str
    prompt_ar: str | None
    choice_ar: str | None
    aliases: tuple[str, ...]
    alias_sets: tuple[frozenset, ...] = field(default=(), compare=False)
    # Shown instead of a lesson suggestion when the tutorial exists but registry.is_available() says otherwise
    # for a reason other than permission (e.g. the tenant's specialty doesn't support it yet).
    unavailable_ar: str | None = None


@dataclass(frozen=True)
class Page:
    id: str
    nav_action: str
    nav_group: str | None
    title_ar: str
    summary_ar: str
    feature_ids: tuple[str, ...]


@dataclass(frozen=True)
class Knowledge:
    entries: dict[str, Entry]
    pages: dict[str, Page]
    plan: dict
    vocabulary: frozenset
    alias_tokens: frozenset = frozenset()  # every canonical token that appears in some alias


def _load(name: str) -> dict:
    return json.loads((KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))


def load() -> Knowledge:
    """JSON registry + features the analyzer discovered that the registry does not cover (rebuilt when the scan changes)."""
    from modules.ai_tutor.chat import discovered

    return _build(discovered.snapshot_key())


def _clear() -> None:
    _build.cache_clear()


load.cache_clear = _clear  # type: ignore[attr-defined]  (tests reset the registry through this)


@lru_cache(maxsize=4)
def _build(snapshot_key: str) -> Knowledge:
    features_raw = _load("features.json")["features"]
    pages_raw = _load("pages.json")["pages"]
    plan = _load("plan.json")

    # Vocabulary = every normalised word used in an alias, so typos can snap to it.
    vocabulary: set[str] = set()
    for raw in [*features_raw, *pages_raw]:
        for alias in raw["aliases_ar"]:
            vocabulary.update(normalize(alias).split())
    vocab = frozenset(_strip_prefix(w, vocabulary) for w in vocabulary)

    pages: dict[str, Page] = {}
    entries: dict[str, Entry] = {}
    for p in pages_raw:
        if p["id"] in pages:
            raise KnowledgeError(f"duplicate page {p['id']}")
        pages[p["id"]] = Page(p["id"], p["nav_action"], p.get("nav_group"), p["title_ar"], p["summary_ar"], tuple(p.get("features", [])))
    for f in features_raw:
        if f["id"] in entries or f["page"] not in pages:
            raise KnowledgeError(f"bad feature {f['id']}")
        entries[f["id"]] = _entry(f, "feature", f["page"], vocab)
    for p in pages_raw:
        key = f"page:{p['id']}"
        entries[key] = _entry({
            "id": key, "title_ar": p["title_ar"], "target": None, "tutorial": None,
            "explain_ar": f"{p['title_ar']}: {p['summary_ar']}", "aliases_ar": p["aliases_ar"],
        }, "page", p["id"], vocab)
    for page in pages.values():
        for fid in page.feature_ids:
            if fid not in entries:
                raise KnowledgeError(f"page {page.id} lists unknown feature {fid}")
    all_tutorials = tutorials.load_all()
    for entry in entries.values():
        if entry.tutorial and entry.tutorial not in all_tutorials:
            raise KnowledgeError(f"{entry.id}: tutorial {entry.tutorial!r} does not exist")
    group_ids = [g["id"] for g in plan["groups"]]
    if len(set(group_ids)) != len(group_ids):
        raise KnowledgeError("duplicate curriculum group")
    for definition in all_tutorials.values():
        group = (definition.get("curriculum") or {}).get("group")
        if group and group not in group_ids:
            raise KnowledgeError(f"{definition['id']}: curriculum group {group!r} is not defined in plan.json")
    from modules.ai_tutor.chat import discovered

    registered_actions = {next(iter(r.values())) for r in _static_refs(entries, pages) if next(iter(r)) == "action"}
    for item in discovered.feature_items(registered_actions, set(pages)):
        key = f"discovered:{item['id']}"
        entries[key] = Entry(
            id=key, kind="discovered", title_ar=item["label_ar"], page=item["page"], target={"action": item["id"]}, tutorial=None,
            explain_ar=f"«{item['label_ar']}» موجودة في صفحة {pages[item['page']].title_ar}.", prompt_ar=None, choice_ar=None,
            aliases=(item["label_ar"],), alias_sets=(frozenset(analyze(item["label_ar"], set(vocab)).content),),
        )
    alias_tokens = frozenset(t for e in entries.values() for s in e.alias_sets for t in s)
    return Knowledge(entries, pages, plan, vocab, alias_tokens)


def _entry(raw: dict, kind: str, page: str, vocab: frozenset) -> Entry:
    sets = tuple(frozenset(analyze(alias, set(vocab)).content) for alias in raw["aliases_ar"])
    if any(not s for s in sets):
        raise KnowledgeError(f"alias of {raw['id']} has no content tokens")
    return Entry(
        id=raw["id"], kind=kind, title_ar=raw["title_ar"], page=page, target=raw.get("target"),
        tutorial=raw.get("tutorial"), explain_ar=raw["explain_ar"], prompt_ar=raw.get("prompt_ar"), choice_ar=raw.get("choice_ar"),
        aliases=tuple(raw["aliases_ar"]), alias_sets=sets, unavailable_ar=raw.get("unavailable_ar"),
    )


def _static_refs(entries: dict, pages: dict) -> list[dict]:
    refs = [{"action": p.nav_action} for p in pages.values()]
    refs += [{"section": f"nav.group.{p.nav_group}"} for p in pages.values() if p.nav_group]
    refs += [e.target for e in entries.values() if e.target and e.kind != "discovered"]
    refs += [{"action": "nav.menu.open"}]
    return refs


def ui_references(include_discovered: bool = True) -> list[dict]:
    """Every UI identifier the knowledge base relies on (the hand-written registry; analyzer-discovered ones optional)."""
    k = load()
    refs = _static_refs(k.entries, k.pages)
    if include_discovered:
        refs += [e.target for e in k.entries.values() if e.kind == "discovered"]
    return refs
