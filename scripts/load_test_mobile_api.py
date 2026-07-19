"""Bounded load probe for Finora's public mobile API endpoints.

This is intentionally a staged verifier, not a generator for a one-shot
"million users" claim. Run it against an isolated load-test environment and
increase concurrency only after each gate passes.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_PATHS = (
    "/api/mobile/v1/health",
    "/api/mobile/v1/feed?limit=8",
    "/api/mobile/v1/products?limit=24",
    "/api/mobile/v1/categories",
)


@dataclass(frozen=True)
class Sample:
    path: str
    status: int
    latency_ms: float
    bytes_read: int
    error: str = ""


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil((percentile_value / 100) * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


def fetch_once(
    *,
    base_url: str,
    tenant: str,
    path: str,
    timeout: float,
    start_gate: threading.Event,
) -> Sample:
    url = urllib.parse.urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Finora-Mobile-Load-Probe/1.0",
            "X-Tenant-Slug": tenant,
        },
    )
    start_gate.wait()
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return Sample(
                path=path,
                status=int(response.status),
                latency_ms=(time.perf_counter() - started) * 1000,
                bytes_read=len(payload),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return Sample(
            path=path,
            status=int(exc.code),
            latency_ms=(time.perf_counter() - started) * 1000,
            bytes_read=len(body),
            error=f"HTTP {exc.code}",
        )
    except Exception as exc:  # noqa: BLE001 - failures belong in the report
        return Sample(
            path=path,
            status=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            bytes_read=0,
            error=f"{type(exc).__name__}: {exc}",
        )


def summarize(samples: list[Sample], elapsed_seconds: float) -> dict:
    latencies = [sample.latency_ms for sample in samples]
    failures = [sample for sample in samples if not 200 <= sample.status < 400]
    by_path: dict[str, dict] = {}
    for path in sorted({sample.path for sample in samples}):
        path_samples = [sample for sample in samples if sample.path == path]
        path_latencies = [sample.latency_ms for sample in path_samples]
        path_failures = [
            sample for sample in path_samples if not 200 <= sample.status < 400
        ]
        by_path[path] = {
            "requests": len(path_samples),
            "errors": len(path_failures),
            "p50_ms": round(percentile(path_latencies, 50), 2),
            "p95_ms": round(percentile(path_latencies, 95), 2),
            "p99_ms": round(percentile(path_latencies, 99), 2),
        }
    return {
        "requests": len(samples),
        "errors": len(failures),
        "error_rate": round(len(failures) / max(1, len(samples)), 6),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "requests_per_second": round(len(samples) / max(0.001, elapsed_seconds), 2),
        "latency_ms": {
            "min": round(min(latencies, default=0), 2),
            "mean": round(statistics.fmean(latencies) if latencies else 0, 2),
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "max": round(max(latencies, default=0), 2),
        },
        "statuses": dict(sorted(Counter(sample.status for sample in samples).items())),
        "bytes_read": sum(sample.bytes_read for sample in samples),
        "by_path": by_path,
        "sample_errors": [asdict(sample) for sample in failures[:10]],
    }


def evaluate_thresholds(
    report: dict, *, max_p95_ms: float, max_error_rate: float
) -> list[str]:
    failed_checks: list[str] = []
    if report["error_rate"] > max_error_rate:
        failed_checks.append(
            f"error_rate={report['error_rate']} exceeds {max_error_rate}"
        )
    if report["latency_ms"]["p95"] > max_p95_ms:
        failed_checks.append(
            f"overall p95={report['latency_ms']['p95']}ms exceeds {max_p95_ms}ms"
        )
    for path, path_report in report["by_path"].items():
        if path_report["p95_ms"] > max_p95_ms:
            failed_checks.append(
                f"{path} p95={path_report['p95_ms']}ms exceeds {max_p95_ms}ms"
            )
    return failed_checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant", default="super")
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument("--max-p95-ms", type=float, default=750.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--allow-high-concurrency",
        action="store_true",
        help="Required above 500 workers; use only in an isolated load-test environment.",
    )
    args = parser.parse_args()
    if args.concurrency < 1 or args.requests < 1:
        parser.error("--concurrency and --requests must be positive")
    if args.concurrency > 500 and not args.allow_high_concurrency:
        parser.error("concurrency above 500 requires --allow-high-concurrency")
    args.paths = tuple(args.paths or DEFAULT_PATHS)
    return args


def main() -> int:
    args = parse_args()
    gate = threading.Event()

    # Warm caches and validate connectivity without counting these calls.
    warm_gate = threading.Event()
    warm_gate.set()
    for index in range(max(0, args.warmup)):
        fetch_once(
            base_url=args.base_url,
            tenant=args.tenant,
            path=args.paths[index % len(args.paths)],
            timeout=args.timeout,
            start_gate=warm_gate,
        )

    samples: list[Sample] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                fetch_once,
                base_url=args.base_url,
                tenant=args.tenant,
                path=args.paths[index % len(args.paths)],
                timeout=args.timeout,
                start_gate=gate,
            )
            for index in range(args.requests)
        ]
        started = time.perf_counter()
        gate.set()
        for future in as_completed(futures):
            samples.append(future.result())
    elapsed = time.perf_counter() - started

    report = {
        "target": args.base_url,
        "tenant": args.tenant,
        "concurrency": args.concurrency,
        "thresholds": {
            "max_p95_ms": args.max_p95_ms,
            "max_error_rate": args.max_error_rate,
        },
        **summarize(samples, elapsed),
    }
    failed_checks = evaluate_thresholds(
        report,
        max_p95_ms=args.max_p95_ms,
        max_error_rate=args.max_error_rate,
    )
    report["failed_checks"] = failed_checks
    report["passed"] = not failed_checks
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(output + "\n", encoding="utf-8")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
