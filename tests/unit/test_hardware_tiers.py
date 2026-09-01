"""Canonical memory-tier budgets for recycled AILEN hardware."""

from ailen.hardware.tiers import classify_hardware_tier


def test_recycled_4gb_tier_reserves_os_audio_and_core_memory() -> None:
    tier = classify_hardware_tier(total_ram_mb=4096, available_ram_mb=3276)

    assert tier.tier_id == "recycled_4gb"
    assert tier.context_tokens == 1024
    assert tier.model_ram_budget_mb == 1400
    assert tier.minimum_free_ram_mb == 700
    assert tier.preferred_runtime == "llama.cpp"


def test_recycled_8gb_tier_has_larger_but_still_bounded_model_budget() -> None:
    tier = classify_hardware_tier(total_ram_mb=8192, available_ram_mb=6553)

    assert tier.tier_id == "recycled_8gb"
    assert tier.context_tokens == 2048
    assert tier.model_ram_budget_mb == 3000
    assert tier.minimum_free_ram_mb == 1200


def test_available_memory_pressure_can_make_local_model_temporarily_nonviable() -> None:
    tier = classify_hardware_tier(total_ram_mb=4096, available_ram_mb=1100)

    assert tier.model_ram_budget_mb == 400
    assert tier.requires_target_benchmark is True


def test_high_memory_envelopes_scale_instead_of_stopping_at_six_gb() -> None:
    tier_16 = classify_hardware_tier(total_ram_mb=16384, available_ram_mb=14500)
    tier_32 = classify_hardware_tier(total_ram_mb=32768, available_ram_mb=30000)
    tier_64 = classify_hardware_tier(total_ram_mb=65536, available_ram_mb=60000)

    assert tier_16.model_ram_budget_mb > 6000
    assert tier_16.context_tokens == 4096
    assert tier_32.model_ram_budget_mb > tier_16.model_ram_budget_mb
    assert tier_32.context_tokens == 8192
    assert tier_64.model_ram_budget_mb > tier_32.model_ram_budget_mb
    assert tier_64.context_tokens == 16384
