from scripts.load_test_mobile_api import (
    Sample,
    evaluate_thresholds,
    percentile,
    summarize,
)


def test_percentile_uses_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) == 50.0
    assert percentile([], 95) == 0.0


def test_summary_reports_failures_and_per_path_latency() -> None:
    samples = [
        Sample("/health", 200, 10.0, 10),
        Sample("/health", 200, 20.0, 10),
        Sample("/feed", 503, 100.0, 5, "HTTP 503"),
    ]

    report = summarize(samples, elapsed_seconds=1.0)

    assert report["requests"] == 3
    assert report["errors"] == 1
    assert report["statuses"] == {200: 2, 503: 1}
    assert report["latency_ms"]["p95"] == 100.0
    assert report["by_path"]["/health"]["p50_ms"] == 10.0
    assert report["by_path"]["/feed"]["errors"] == 1


def test_thresholds_fail_when_one_path_is_slow() -> None:
    report = summarize(
        [
            Sample("/health", 200, 10.0, 10),
            Sample("/products", 200, 2500.0, 10),
        ],
        elapsed_seconds=1.0,
    )

    failures = evaluate_thresholds(
        report,
        max_p95_ms=1000.0,
        max_error_rate=0.01,
    )

    assert any("/products" in failure for failure in failures)
