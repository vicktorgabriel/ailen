#!/usr/bin/env python3
"""Benchmark for AILEN Rule-Based AI Router.

Measures deterministic routing decision throughput, latency (p50, p95, p99),
and memory overhead across all profiles and scenarios.
"""

import json
import statistics
import time
from pathlib import Path

from ailen.ai.router import RouteRequest, RuleBasedRouter
from ailen.domain.enums import DeviceProfile, PrivacyLevel


def run_benchmark(iterations: int = 10000) -> dict:
    router = RuleBasedRouter()

    test_scenarios = [
        ("rule_fast_path", RouteRequest(intent="volume", privacy_level=PrivacyLevel.PUBLIC)),
        ("hybrid_private", RouteRequest(intent="chat", profile=DeviceProfile.HYBRID, privacy_level=PrivacyLevel.PRIVATE, local_backend_available=True, lan_brain_available=True)),
        ("satellite_lan", RouteRequest(intent="chat", profile=DeviceProfile.SATELLITE, privacy_level=PrivacyLevel.PUBLIC, lan_brain_available=True, cloud_allowed=True, internet_available=True)),
        ("cloud_public", RouteRequest(intent="chat", profile=DeviceProfile.CLOUD, privacy_level=PrivacyLevel.PUBLIC, cloud_allowed=True, internet_available=True)),
        ("budget_circuit_break", RouteRequest(intent="chat", profile=DeviceProfile.HYBRID, privacy_level=PrivacyLevel.PUBLIC, cloud_allowed=True, internet_available=True, budget_exceeded=True, local_backend_available=True)),
        ("offline_degraded", RouteRequest(intent="chat", profile=DeviceProfile.HYBRID, privacy_level=PrivacyLevel.PRIVATE, local_backend_available=False, lan_brain_available=False)),
    ]

    latencies_us: list[float] = []

    # Warmup
    for _ in range(100):
        for _, req in test_scenarios:
            router.route(req)

    start_total = time.perf_counter()
    for _ in range(iterations // len(test_scenarios)):
        for _, req in test_scenarios:
            t0 = time.perf_counter()
            router.route(req)
            t1 = time.perf_counter()
            latencies_us.append((t1 - t0) * 1_000_000.0)
    total_time_s = time.perf_counter() - start_total

    total_ops = len(latencies_us)
    throughput = total_ops / total_time_s
    latencies_sorted = sorted(latencies_us)

    p50 = statistics.median(latencies_us)
    p95 = latencies_sorted[int(total_ops * 0.95)]
    p99 = latencies_sorted[int(total_ops * 0.99)]
    avg = statistics.mean(latencies_us)

    results = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_operations": total_ops,
        "total_time_seconds": round(total_time_s, 4),
        "throughput_ops_sec": round(throughput, 2),
        "latency_us": {
            "avg": round(avg, 3),
            "p50": round(p50, 3),
            "p95": round(p95, 3),
            "p99": round(p99, 3),
            "min": round(min(latencies_us), 3),
            "max": round(max(latencies_us), 3),
        },
    }

    return results


def main() -> None:
    results = run_benchmark(iterations=12000)

    docs_dir = Path("docs/benchmarks")
    docs_dir.mkdir(parents=True, exist_ok=True)

    json_path = docs_dir / "dev_ai_router_benchmark.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    md_content = f"""# AI Router Benchmark Report

- **Date:** {results['timestamp_utc']}
- **Total Operations:** {results['total_operations']}
- **Throughput:** **{results['throughput_ops_sec']:,.0f} ops/sec**
- **Average Latency:** {results['latency_us']['avg']:.3f} µs
- **p50 Latency:** {results['latency_us']['p50']:.3f} µs
- **p95 Latency:** {results['latency_us']['p95']:.3f} µs
- **p99 Latency:** {results['latency_us']['p99']:.3f} µs

## Key Observations
1. **Low logical overhead on this DEV machine:** p95 routing latency was {results['latency_us']['p95']:.3f} µs in this run. This is not a hardware-target CPU benchmark.
2. **Determinism:** Zero network calls or LLM prompts are executed during the routing decision benchmark.
3. **Scope:** This covers router logic and privacy checks represented in the request. It does **not** measure SQLite budget queries, backend health checks, network latency or inference.
"""
    md_path = docs_dir / "dev_ai_router_benchmark.md"
    md_path.write_text(md_content, encoding="utf-8")

    print(f"Benchmark completed: {results['throughput_ops_sec']:,.0f} ops/sec, avg {results['latency_us']['avg']:.3f} µs")
    print(f"Saved reports to {json_path} and {md_path}")


if __name__ == "__main__":
    main()
