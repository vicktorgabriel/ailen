# AI Router Benchmark Report

- **Date:** 2026-08-21T21:19:56Z
- **Total Operations:** 12000
- **Throughput:** **374,057 ops/sec**
- **Average Latency:** 2.522 µs
- **p50 Latency:** 2.170 µs
- **p95 Latency:** 2.870 µs
- **p99 Latency:** 5.930 µs

## Key Observations
1. **Low logical overhead on this DEV machine:** p95 routing latency was 2.870 µs in this run. This is not a hardware-target CPU benchmark.
2. **Determinism:** Zero network calls or LLM prompts are executed during the routing decision benchmark.
3. **Scope:** The measurement covers router logic and privacy checks represented in the request. It does **not** measure SQLite budget queries, backend health checks, network latency or inference.
