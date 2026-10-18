"""`analyze-ai-tutor`: static scan + registry validation + verified-tutorial validation (CI friendly).

Exit codes: 0 = ok (warnings allowed), 1 = a tutorial declared `verified` is broken (or the runtime scan wrote data),
2 = the analyzer itself failed.
Missing knowledge / missing tutorials are reported but NEVER fail the build.
"""
from __future__ import annotations

import argparse
import json
import sys

from modules.ai_tutor.analyzer import snapshot as snapshots


def failures(snapshot: dict) -> list[str]:
    """Hard failures: verified tutorials that no longer work, and untrustworthy runtime scans."""
    problems = []
    for tutorial in snapshot["tutorials"]:
        if tutorial["declared_status"] == "verified" and tutorial["status"] == "broken":
            errors = "; ".join(p["message"] for p in tutorial["problems"] if p["severity"] == "error")
            problems.append(f"verified tutorial «{tutorial['id']}» is broken: {errors}")
    if any(w["code"] == "runtime_wrote_data" for w in snapshot["warnings"]):
        problems.append("the runtime scan observed write requests (it must be read-only)")
    return problems


def summary(snapshot: dict) -> str:
    c, m = snapshot["coverage"], snapshot["meta"]
    feat, allx = c["actions"]["feature"], c["actions"]["all"]
    lines = [
        f"Finora AI Tutor — system map ({'static + runtime' if m['runtime'] else 'static only'}, commit {m['git_commit'] or 'n/a'}, version {m['app_version']})",
        f"  Pages: {m['pages_count']}   Sections: {m['sections_count']}   Actions: {m['actions_count']}   Fields: {m['fields_count']}",
        f"  Discovery:      {c['discovery']['pages_instrumented']}/{c['discovery']['pages_total']} pages instrumented ({c['discovery']['pages_instrumented_pct']}%)"
        + (f", {c['discovery']['actions_confirmed_runtime']}/{c['discovery']['actions_discovered']} actions confirmed at runtime" if m["runtime"] else ""),
        f"  Knowledge:      {allx['knowledge']}/{allx['discovered']} actions ({allx['knowledge_pct']}%)  |  features {feat['knowledge']}/{feat['discovered']} ({feat['knowledge_pct']}%)",
        f"  Tutorials:      {allx['tutorial']}/{allx['discovered']} actions ({allx['tutorial_pct']}%)  |  features {feat['tutorial']}/{feat['discovered']} ({feat['tutorial_pct']}%)",
        f"  Verified:       {allx['verified']}/{allx['discovered']} actions ({allx['verified_pct']}%)  |  verified tutorials {c['tutorials']['verified']}/{c['tutorials']['total']}, broken {c['tutorials']['broken']}",
    ]
    for tutorial in snapshot["tutorials"]:
        lines.append(f"  - tutorial {tutorial['id']} v{tutorial['version']}: {tutorial['status']} ({tutorial['targets_found']}/{tutorial['targets_total']} targets)")
        for problem in tutorial["problems"]:
            lines.append(f"      [{problem['severity']}] {problem['code']}: {problem['message']}")
    for warning in snapshot["warnings"]:
        lines.append(f"  warning {warning['code']}: {warning['message']}")
    diff = snapshot.get("diff")
    if diff and not diff["first_scan"]:
        lines += [f"  + {a['id']} ({a['kind']})" for a in diff["added"]] + [f"  - {r['id']} ({r['kind']})" for r in diff["removed"]]
        lines += [f"  ! {c_['id']} changed: {', '.join(c_['change'])}" for c_ in diff["changed"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="analyze-ai-tutor", description=__doc__.split("\n")[0])
    parser.add_argument("--runtime", help="runtime scan JSON produced by scripts/ai_tutor_runtime_scan.mjs")
    parser.add_argument("--write", action="store_true", help="save the result as the latest snapshot (diffs against the previous one)")
    parser.add_argument("--json", action="store_true", help="print the full snapshot as JSON")
    args = parser.parse_args(argv)
    try:
        if args.runtime:
            with open(args.runtime, encoding="utf-8") as handle:
                runtime_payload = json.load(handle)
            if args.write:
                snapshots.save_runtime(runtime_payload)
            from modules.ai_tutor.analyzer.catalog import validate_runtime

            runtime = validate_runtime(runtime_payload)
        else:
            runtime = snapshots.load_runtime()
        if args.write:
            snapshot = snapshots.run_scan()
        else:
            snapshot = snapshots.build_snapshot(runtime)
    except (OSError, ValueError, LookupError, SyntaxError) as exc:
        print(f"analyze-ai-tutor: failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(snapshot, ensure_ascii=False, indent=1) if args.json else summary(snapshot))
    problems = failures(snapshot)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0
