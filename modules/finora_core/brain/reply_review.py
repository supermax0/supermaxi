"""Final deterministic communication checks; never a source of facts or execution authority."""
import re
from dataclasses import dataclass

from .extract import normalize


def comparable(value):
    return re.sub(r"[\W_]+", " ", normalize(value)).strip()


@dataclass
class ReviewedReply:
    text: str
    issues: list[str]
    needs_review: bool = False


def review(value, *, current, recent, generated=False, allow_repeat=False, language="ar-iq"):
    issues, lines, seen = [], [], set()
    for line in value.strip().splitlines():
        key = comparable(line)
        previous_key = comparable(lines[-1]) if lines else ""
        if key and (key == previous_key or (key in seen and re.search(r"[؟?]\s*$", line))):
            issues.append("duplicate_line_removed")
            continue
        if key:
            seen.add(key)
        lines.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    previous = next((r["text"] for r in reversed(recent) if r["role"] == "finora"), "")
    # Same request may legitimately have the same answer (e.g. a resent question).
    before_reply = recent[:max((i for i, r in enumerate(recent) if r["role"] == "finora"), default=0)]
    previous_request = next((r["text"] for r in reversed(before_reply) if r["role"] == "customer"), "")
    repeated = (generated and not allow_repeat and previous and comparable(text) == comparable(previous)
                and comparable(current) != comparable(previous_request))
    if not text or repeated:
        issues.append("empty_reply" if not text else "repeated_answer_to_new_request")
        text = ("I couldn't prepare a reliable answer to this point. Your message is in the conversation for FINORA to review."
                if language == "en" else "ما كدرت أجهز جواب دقيق لهالنقطة. رسالتك موجودة بالمحادثة، وطلبت من فريق فينورا يراجعها حتى تحصل جواب مناسب.")
        return ReviewedReply(text, list(dict.fromkeys(issues)), True)
    return ReviewedReply(text, list(dict.fromkeys(issues)))
