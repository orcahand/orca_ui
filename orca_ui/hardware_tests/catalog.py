"""Load and validate the feature definitions and plans, and decide which steps
apply to the hand under test.

Definitions are YAML files under ``definitions/`` (one per feature) and plans
YAML files under ``plans/`` (one per plan, named after its id); their keys map
one to one onto the dataclasses in :mod:`orca_ui.hardware_tests.model`. A
plan's ``includes`` are resolved here into its ``features``. Structural problems fail loudly at load.
Whether every named check is registered is a separate question
(:func:`unregistered_checks`), because checks live in modules that import the
console.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from orca_ui.hardware_tests.model import (
    PANELS,
    AppliesTo,
    FeatureDefinition,
    HandFacts,
    Plan,
    Step,
)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFINITIONS_DIR = PACKAGE_DIR / "definitions"
PLANS_DIR = PACKAGE_DIR / "plans"

STEP_KINDS = ("manual", "auto", "compare", "observe")
GROUPS = ("new", "existing", "observation")
CAPABILITIES = ("tactile", "encoders")
ACTION_PREFIXES = ("operation:", "jog:")
HANDS_ON_KINDS = ("manual",)


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Catalog:
    features: dict[str, FeatureDefinition]
    plans: dict[str, Plan]

    def plan(self, plan_id: str) -> Plan:
        try:
            return self.plans[plan_id]
        except KeyError:
            raise CatalogError(f"unknown plan {plan_id!r} (known: {', '.join(sorted(self.plans))})")

    def plan_features(self, plan_id: str) -> list[FeatureDefinition]:
        return [self.features[f] for f in self.plan(plan_id).features]

    def plan_chain(self, plan_id: str) -> list[str]:
        self.plan(plan_id)
        return include_chain(plan_id, self.plans)


def _tuple(value, where: str, cast=str) -> tuple:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CatalogError(f"{where}: expected a list, got {value!r}")
    try:
        return tuple(cast(v) for v in value)
    except (TypeError, ValueError):
        raise CatalogError(f"{where}: {value!r} is not a list of {cast.__name__}")


def _applies_to(raw, where: str) -> AppliesTo:
    if raw is None:
        return AppliesTo()
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}.applies_to: expected a mapping")
    unknown = set(raw) - {"motor_families", "hardware_versions", "sides", "requires"}
    if unknown:
        raise CatalogError(f"{where}.applies_to: unknown keys {sorted(unknown)}")
    applies = AppliesTo(
        motor_families=_tuple(raw.get("motor_families"), f"{where}.motor_families"),
        hardware_versions=_tuple(raw.get("hardware_versions"), f"{where}.hardware_versions", int),
        sides=_tuple(raw.get("sides"), f"{where}.sides"),
        requires=_tuple(raw.get("requires"), f"{where}.requires"),
    )
    bad = set(applies.requires) - set(CAPABILITIES)
    if bad:
        raise CatalogError(f"{where}.requires: unknown capabilities {sorted(bad)}")
    return applies


_STEP_KEYS = {"id", "title", "kind", "instructions", "pass_rule", "applies_to", "panels",
              "action", "check", "params"}


def _step(raw, where: str) -> Step:
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: a step must be a mapping")
    unknown = set(raw) - _STEP_KEYS
    if unknown:
        raise CatalogError(f"{where}: unknown keys {sorted(unknown)}")
    for key in ("id", "title", "kind", "instructions", "pass_rule"):
        if not raw.get(key):
            raise CatalogError(f"{where}: missing {key!r}")
    where = f"{where} ({raw['id']})"
    kind = raw["kind"]
    if kind not in STEP_KINDS:
        raise CatalogError(f"{where}: kind must be one of {STEP_KINDS}, not {kind!r}")
    check = raw.get("check")
    if kind in ("auto", "compare") and not check:
        raise CatalogError(f"{where}: an {kind} step needs a check")
    panels = _tuple(raw.get("panels"), f"{where}.panels")
    bad_panels = set(panels) - set(PANELS)
    if bad_panels:
        raise CatalogError(f"{where}: unknown panels {sorted(bad_panels)}")
    action = raw.get("action")
    if action is not None and not (isinstance(action, str) and action.startswith(ACTION_PREFIXES)):
        raise CatalogError(f"{where}: action must start with one of {ACTION_PREFIXES}")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise CatalogError(f"{where}: params must be a mapping")
    return Step(
        id=str(raw["id"]),
        title=str(raw["title"]),
        kind=kind,
        instructions=str(raw["instructions"]).strip(),
        pass_rule=str(raw["pass_rule"]).strip(),
        applies_to=_applies_to(raw.get("applies_to"), where),
        panels=panels,
        action=action,
        check=str(check) if check else None,
        params=dict(params),
    )


def _load_yaml(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CatalogError(f"{path.name}: {e}")
    return _yaml_mapping(text, path.name)


def _yaml_mapping(text: str, name: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise CatalogError(f"{name}: {e}")
    if not isinstance(data, dict):
        raise CatalogError(f"{name}: expected a mapping at the top level")
    return data


def load_feature(path: Path) -> FeatureDefinition:
    return parse_feature(_load_yaml(path), path)


def feature_from_text(text: str, name: str) -> FeatureDefinition:
    """A definition from a file's contents, e.g. as stored in a git commit."""
    return parse_feature(_yaml_mapping(text, name), Path(name))


def parse_feature(raw: dict, path: Path) -> FeatureDefinition:
    for key in ("id", "title", "summary", "group", "steps"):
        if not raw.get(key):
            raise CatalogError(f"{path.name}: missing {key!r}")
    if raw["id"] != path.stem:
        raise CatalogError(f"{path.name}: id {raw['id']!r} does not match the file name")
    if raw["group"] not in GROUPS:
        raise CatalogError(f"{path.name}: group must be one of {GROUPS}")
    if not isinstance(raw["steps"], list):
        raise CatalogError(f"{path.name}: steps must be a list")
    return FeatureDefinition(
        id=raw["id"],
        title=str(raw["title"]),
        summary=str(raw["summary"]).strip(),
        group=raw["group"],
        steps=tuple(_step(s, f"{path.name} step {i + 1}") for i, s in enumerate(raw["steps"])),
    )


def load_plan(path: Path) -> Plan:
    """One plan file as written: ``features`` are its own, unresolved."""
    return parse_plan(_load_yaml(path), path)


def plan_from_text(text: str, name: str) -> Plan:
    """A plan from a file's contents, as written (its includes unresolved)."""
    return parse_plan(_yaml_mapping(text, name), Path(name))


def parse_plan(raw: dict, path: Path) -> Plan:
    for key in ("id", "title", "summary"):
        if not raw.get(key):
            raise CatalogError(f"{path.name}: missing {key!r}")
    if raw["id"] != path.stem:
        raise CatalogError(f"{path.name}: id {raw['id']!r} does not match the file name")
    unknown = set(raw) - {"id", "title", "summary", "features", "includes", "default"}
    if unknown:
        raise CatalogError(f"{path.name}: unknown keys {sorted(unknown)}")
    features = _tuple(raw.get("features"), f"{path.name}.features")
    includes = _tuple(raw.get("includes"), f"{path.name}.includes")
    if not features and not includes:
        raise CatalogError(f"{path.name}: a plan needs features or includes")
    if len(set(features)) != len(features):
        raise CatalogError(f"plan {raw['id']!r} lists a feature twice")
    return Plan(
        id=str(raw["id"]),
        title=str(raw["title"]),
        summary=str(raw["summary"]).strip(),
        features=features,
        default=bool(raw.get("default", False)),
        includes=includes,
    )


def resolve_features(plan_id: str, raw: dict[str, Plan], chain: tuple[str, ...] = ()) -> tuple[str, ...]:
    """``plan_id``'s features: its includes' (recursively) first, then its own, each once."""
    if plan_id in chain:
        raise CatalogError(f"plans include each other in a cycle: {' -> '.join(chain + (plan_id,))}")
    out: list[str] = []
    for included in raw[plan_id].includes:
        if included not in raw:
            raise CatalogError(f"plan {plan_id!r} includes unknown plan {included!r}")
        out += resolve_features(included, raw, chain + (plan_id,))
    out += raw[plan_id].features
    return tuple(dict.fromkeys(out))


def include_chain(plan_id: str, plans: dict[str, Plan]) -> list[str]:
    """``plan_id`` and every plan it includes, recursively, each once."""
    out = [plan_id]
    for included in plans[plan_id].includes:
        out += [p for p in include_chain(included, plans) if p not in out]
    return out


def load_catalog(definitions_dir: Path = DEFINITIONS_DIR, plans_dir: Path = PLANS_DIR) -> Catalog:
    """Every feature and plan, validated: unique ids, unique step ids across
    all features (the REST API addresses steps by id), plans naming only
    known features and including only known plans, without cycles."""
    features: dict[str, FeatureDefinition] = {}
    step_owner: dict[str, str] = {}
    for path in sorted(definitions_dir.glob("*.yaml")):
        feature = load_feature(path)
        for step in feature.steps:
            if step.id in step_owner:
                raise CatalogError(
                    f"step id {step.id!r} is used by both {step_owner[step.id]} and {feature.id}")
            step_owner[step.id] = feature.id
        features[feature.id] = feature
    raw_plans: dict[str, Plan] = {}
    for path in sorted(plans_dir.glob("*.yaml")):
        plan = load_plan(path)
        missing = [f for f in plan.features if f not in features]
        if missing:
            raise CatalogError(f"plan {plan.id!r} names unknown features {missing}")
        raw_plans[plan.id] = plan
    plans = {pid: replace(plan, features=resolve_features(pid, raw_plans)) for pid, plan in raw_plans.items()}
    if sum(p.default for p in plans.values()) > 1:
        raise CatalogError("more than one plan is marked default")
    # The default plan first: the tab offers the first plan it is given.
    plans = dict(sorted(plans.items(), key=lambda kv: not kv[1].default))
    return Catalog(features=features, plans=plans)


@lru_cache(maxsize=1)
def default_catalog() -> Catalog:
    return load_catalog()


def unregistered_checks(catalog: Catalog, registered: frozenset[str]) -> dict[str, list[str]]:
    """Check name -> the step ids naming it, for every check not in ``registered``."""
    missing: dict[str, list[str]] = {}
    for feature in catalog.features.values():
        for step in feature.steps:
            if step.check and step.check not in registered:
                missing.setdefault(step.check, []).append(step.id)
    return missing


def is_hands_on(step: Step) -> bool:
    """Steps a person carries out in the Hands-on section."""
    return step.kind in HANDS_ON_KINDS or (step.kind == "observe" and not step.check)


def is_automatic(step: Step) -> bool:
    """Steps the "Run automatic checks" step runs."""
    return step.kind in ("auto", "compare") or (step.kind == "observe" and bool(step.check))


def applicability(step: Step, hand: HandFacts) -> tuple[bool, Optional[str]]:
    """Whether ``step`` runs on ``hand``, and in words why not when it does not.

    A fact the session does not know (no motor family, no version) does not
    rule a step out: the step stays applicable and the person decides.
    """
    rule = step.applies_to
    if rule.motor_families and hand.motor_family is not None \
            and hand.motor_family not in rule.motor_families:
        return False, f"only for {' / '.join(rule.motor_families)} motors; this hand has {hand.motor_family}"
    if rule.hardware_versions and hand.hardware_version is not None \
            and hand.hardware_version not in rule.hardware_versions:
        wanted = ", ".join(_version_text(v) for v in rule.hardware_versions)
        return False, f"only for hardware {wanted}; this hand is {_version_text(hand.hardware_version)}"
    if rule.sides and hand.side is not None and hand.side not in rule.sides:
        return False, f"only for {' / '.join(rule.sides)} hands; this is a {hand.side} hand"
    lacking = [cap for cap in rule.requires if cap not in hand.capabilities]
    if lacking:
        return False, f"needs {' and '.join(_capability_text(c) for c in lacking)}, which this hand does not have"
    return True, None


def _version_text(version: int) -> str:
    digits = f"{int(version):03d}"
    return f"v{digits[0]}.{digits[1]}" + (f".{digits[2]}" if digits[2] != "0" else "")


def _capability_text(capability: str) -> str:
    return {"tactile": "tactile sensors", "encoders": "joint encoders"}.get(capability, capability)
