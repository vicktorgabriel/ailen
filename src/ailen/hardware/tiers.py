"""Canonical memory envelopes for heterogeneous AILEN installations.

These values are planning limits, not performance claims. A model is selected
only if its verified descriptor fits the current available-memory envelope;
realtime quality and latency still require a benchmark on the target device.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareTier:
    """Memory-safe local inference envelope for one hardware class."""

    tier_id: str
    context_tokens: int
    model_ram_budget_mb: int
    minimum_free_ram_mb: int
    preferred_runtime: str
    requires_target_benchmark: bool = True


def classify_hardware_tier(total_ram_mb: int, available_ram_mb: int) -> HardwareTier:
    """Return a bounded tier using measured total and currently free RAM.

    The model budget reserves explicit headroom for the OS, Core, Vosk, Piper,
    display and transient buffers instead of treating all available RAM as
    model capacity.
    """
    total = max(0, int(total_ram_mb))
    available = max(0, int(available_ram_mb))
    if total < 3500:
        return HardwareTier("under_4gb", 1024, 0, 600, "none")
    if total < 6500:
        reserve = 700
        return HardwareTier(
            "recycled_4gb",
            1024,
            min(1400, max(0, available - reserve)),
            reserve,
            "llama.cpp",
        )
    if total < 12500:
        reserve = 1200
        return HardwareTier(
            "recycled_8gb",
            2048,
            min(3000, max(0, available - reserve)),
            reserve,
            "llama.cpp",
        )
    # Above the recycled 4/8 GB envelopes there is deliberately no fixed model
    # ceiling.  Keep a proportional whole-system reserve, then let the model
    # planner and target-specific evidence decide what fits.  This prevents a
    # 32/64 GB host from being capped by the former 6 GB laboratory policy.
    if total < 24500:
        tier_id = "workstation_16gb"
        context_tokens = 4096
        reserve_floor = 1800
    elif total < 49100:
        tier_id = "workstation_32gb"
        context_tokens = 8192
        reserve_floor = 3000
    else:
        tier_id = "workstation_64gb_plus"
        context_tokens = 16384
        reserve_floor = 6000
    reserve = max(reserve_floor, round(total * 0.15))
    return HardwareTier(
        tier_id,
        context_tokens,
        max(0, available - reserve),
        reserve,
        "llama.cpp",
    )
