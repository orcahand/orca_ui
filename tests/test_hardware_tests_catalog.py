"""The hardware-test definitions load, every check they name exists, and a
step that does not fit the hand says why."""

from pathlib import Path

import pytest

from orca_ui.hardware_tests import catalog as cat
from orca_ui.hardware_tests.model import HandFacts

# Registered by checks/compare.py, which is written alongside the console checks.
COMPARE_CHECKS = frozenset({
    "compare_detect", "compare_config_loading", "compare_plain_calibration", "compare_neutral",
    "compare_tension_hold", "compare_joint_loop", "compare_tactile_health", "compare_script_flags",
    "calibration_redrive", "calibration_plain_pass", "hardware_version_pin", "guided_tension_refusal",
    "calibration_vs_encoders",
})


def _hand(**facts) -> HandFacts:
    base = dict(label="ser-0000", model_name="orcahand-right", motor_family="dynamixel",
                hardware_version=210, hardware_version_source="board", side="right",
                capabilities=("encoders",), mock=False)
    return HandFacts(**{**base, **facts})


def test_every_named_check_is_registered():
    from orca_ui.hardware_tests import checks

    catalog = cat.load_catalog()
    assert "merge-0.13" in catalog.plans
    missing = cat.unregistered_checks(catalog, checks.registered_checks())
    compare_written = Path(checks.__file__).with_name("compare.py").exists()
    if not compare_written:
        assert set(missing) <= COMPARE_CHECKS, f"console checks not registered: {sorted(set(missing) - COMPARE_CHECKS)}"
        pytest.skip(f"checks/compare.py does not exist yet; not verified: {', '.join(sorted(missing))}")
    assert checks.COMPARE_IMPORT_ERROR is None, f"checks/compare.py failed to import: {checks.COMPARE_IMPORT_ERROR!r}"
    assert not missing, f"definitions name unregistered checks: {missing}"


def test_applicability_names_the_reason():
    steps = {s.id: s for f in cat.load_catalog().features.values() for s in f.steps}

    applicable, reason = cat.applicability(steps["C1"], _hand())
    assert not applicable and "feetech" in reason and "dynamixel" in reason
    applicable, reason = cat.applicability(steps["A9"], _hand())
    assert not applicable and "left" in reason
    applicable, reason = cat.applicability(steps["B7"], _hand())
    assert not applicable and "tactile" in reason
    applicable, reason = cat.applicability(steps["A5"], _hand(hardware_version=200))
    assert not applicable and "v2.0" in reason

    # A fact the console does not know leaves the step to the person.
    unknown = _hand(motor_family=None, hardware_version=None, side=None)
    assert cat.applicability(steps["A9"], unknown) == (True, None)


def test_a_broken_definition_fails_at_load(tmp_path):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    (definitions / "broken.yaml").write_text(
        "id: broken\ntitle: Broken\nsummary: s\ngroup: new\nsteps:\n"
        "  - {id: X1, title: t, kind: auto, instructions: i, pass_rule: p}\n")
    with pytest.raises(cat.CatalogError, match="needs a check"):
        cat.load_catalog(definitions, plans)


def test_plan_includes_resolve_and_fail_loudly(tmp_path):
    definitions, plans = tmp_path / "definitions", tmp_path / "plans"
    definitions.mkdir()
    plans.mkdir()
    for fid, sid in (("f1", "X1"), ("f2", "X2"), ("f3", "X3")):
        (definitions / f"{fid}.yaml").write_text(
            f"id: {fid}\ntitle: t\nsummary: s\ngroup: new\nsteps:\n"
            f"  - {{id: {sid}, title: t, kind: manual, instructions: i, pass_rule: p}}\n")
    (plans / "base.yaml").write_text("id: base\ntitle: b\nsummary: s\nfeatures: [f1, f2]\n")
    (plans / "rel.yaml").write_text("id: rel\ntitle: r\nsummary: s\nincludes: [base]\nfeatures: [f3, f1]\n")
    catalog = cat.load_catalog(definitions, plans)
    assert catalog.plans["rel"].features == ("f1", "f2", "f3")
    assert catalog.plan_chain("rel") == ["rel", "base"]

    (plans / "base.yaml").write_text("id: base\ntitle: b\nsummary: s\nincludes: [rel]\nfeatures: [f1]\n")
    with pytest.raises(cat.CatalogError, match="cycle"):
        cat.load_catalog(definitions, plans)
    (plans / "base.yaml").write_text("id: base\ntitle: b\nsummary: s\nincludes: [nope]\nfeatures: [f1]\n")
    with pytest.raises(cat.CatalogError, match="unknown plan 'nope'"):
        cat.load_catalog(definitions, plans)
