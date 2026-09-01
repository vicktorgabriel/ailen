"""Lab profile generation must use only canonical configuration fields."""

import tomllib

import pytest

from ailen.core.config import load_config_from_dict, validate_config
from ailen.runtime.lab_config import LAB_PROFILE_IDS, generate_lab_config_toml


@pytest.mark.parametrize("profile_id", LAB_PROFILE_IDS)
def test_lab_profiles_generate_valid_canonical_toml(profile_id: str) -> None:
    raw = tomllib.loads(generate_lab_config_toml(profile_id=profile_id))
    config = load_config_from_dict(raw)

    assert validate_config(config) == []
    assert raw["display"]["face_style"] == "facepack"
    assert "voice_volume" not in raw["audio"]
    assert "sound_volume" not in raw["audio"]
    assert "model" not in raw["ai"]
    assert "trusted" not in raw["ai"]["local"]
    assert "qwen3.5:9b" not in generate_lab_config_toml(profile_id=profile_id)


def test_lab_profiles_express_distinct_topologies_without_hidden_local() -> None:
    local4 = tomllib.loads(
        generate_lab_config_toml(profile_id="recycled-4gb-local-candidate")
    )
    satellite = tomllib.loads(generate_lab_config_toml(profile_id="lan-satellite"))
    external = tomllib.loads(generate_lab_config_toml(profile_id="external-only"))

    assert local4["ai"]["provider"] == "auto"
    assert local4["ai"]["local"]["enabled"] is False
    assert local4["ai"]["local"]["model"] == ""
    assert satellite["node"]["profile"] == "SATELLITE"
    assert satellite["ai"]["local"]["enabled"] is False
    assert satellite["ai"]["lan"]["enabled"] is True
    assert external["ai"]["local"]["enabled"] is False
    assert external["ai"]["lan"]["enabled"] is False
    assert external["ai"]["provider"] == "auto"


def test_lab_model_requires_explicit_override_or_provisioning_plan() -> None:
    raw = tomllib.loads(
        generate_lab_config_toml(
            profile_id="recycled-8gb-hybrid",
            local_model="qualified-model-from-lab-operator",
        )
    )

    assert raw["ai"]["local"]["enabled"] is True
    assert raw["ai"]["local"]["model"] == "qualified-model-from-lab-operator"


def test_lab_profile_rejects_unknown_id_instead_of_guessing_hardware() -> None:
    with pytest.raises(ValueError, match="Unknown lab profile"):
        generate_lab_config_toml(profile_id="magic-fast-machine")
