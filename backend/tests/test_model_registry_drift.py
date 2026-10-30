"""Guard fal.ai provider model configs against billing registry drift.

The fal provider configs drive the models exposed by generation and edit flows,
while model_registry supplies billing and cost-catalog metadata.  Both are derived
from app.services.model_catalog; these tests make sure neither drifts from it, so
newly exposed models resolve their billing metadata and removed models do not leave
stale registrations.
"""

from app.providers.fal_provider import FAL_EDIT_MODEL_CONFIG, FAL_MODEL_CONFIG
from app.services import model_registry
from app.services.model_catalog import offered_keys


def test_provider_configs_match_the_catalog():
    assert set(FAL_MODEL_CONFIG) == set(offered_keys("generate"))
    assert set(FAL_EDIT_MODEL_CONFIG) == set(offered_keys("edit"))


def test_registry_generation_and_edit_entries_match_the_catalog():
    for operation in ("generate", "edit"):
        registered = {e.short_name for e in model_registry.entries_for_operation(operation)}
        assert registered == set(offered_keys(operation))


def test_fal_generation_models_are_registered_for_billing():
    """Every configured fal generation model must have a base registry entry."""
    registered_short_names = {
        entry.short_name
        for entry in model_registry.entries_for_operation("generate")
        if entry.lora_variant_of is None
    }

    for short_name in FAL_MODEL_CONFIG:
        assert short_name in registered_short_names, (
            f"{short_name} is in FAL_MODEL_CONFIG but not registered in "
            "model_registry for operation=generate"
        )


def test_fal_edit_models_are_registered_for_billing():
    """Every configured fal edit model must have a registry entry."""
    registered_short_names = {
        entry.short_name for entry in model_registry.entries_for_operation("edit")
    }

    for short_name in FAL_EDIT_MODEL_CONFIG:
        assert short_name in registered_short_names, (
            f"{short_name} is in FAL_EDIT_MODEL_CONFIG but not registered in "
            "model_registry for operation=edit"
        )


def test_fal_generation_registry_entries_have_provider_configs():
    """fal generation registry entries must not outlive their provider configs."""
    for entry in model_registry.entries_for_operation("generate"):
        if entry.provider == "fal":
            assert entry.short_name in FAL_MODEL_CONFIG, (
                f"{entry.short_name} is registered in model_registry for "
                "operation=generate and provider=fal but not in FAL_MODEL_CONFIG"
            )


def test_fal_edit_registry_entries_have_provider_configs():
    """fal edit registry entries must not outlive their provider configs."""
    for entry in model_registry.entries_for_operation("edit"):
        if entry.provider == "fal":
            assert entry.short_name in FAL_EDIT_MODEL_CONFIG, (
                f"{entry.short_name} is registered in model_registry for "
                "operation=edit and provider=fal but not in FAL_EDIT_MODEL_CONFIG"
            )
