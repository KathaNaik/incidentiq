"""Structural guarantees that Polaris ground truth cannot reach runtime code.

These tests derive what counts as a label from the label model itself, so a label added
upstream later is covered without anyone remembering to extend a list here.
"""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from ingestion.errors import IngestionError
from ingestion.polaris import features as features_module
from ingestion.polaris.features import PolarisFeatureRecord
from ingestion.polaris.labels import LABEL_COLUMNS, label_only_fields
from ingestion.polaris.normalize import split_row
from tests.ingestion_fixtures import POLARIS_LABEL_VALUES, POLARIS_ROW

API_ROOT = Path(__file__).resolve().parents[1]


def test_no_label_field_exists_on_the_feature_record() -> None:
    assert label_only_fields()  # guard against an empty set making this vacuous
    assert label_only_fields().isdisjoint(PolarisFeatureRecord.model_fields)


def test_a_feature_record_cannot_be_built_from_a_raw_row() -> None:
    """The raw row carries labels, so the feature model rejects it outright. Features can
    only be produced by selecting fields deliberately."""
    with pytest.raises(ValidationError):
        PolarisFeatureRecord(**POLARIS_ROW)


def test_serialized_features_contain_no_label_names_or_values() -> None:
    feature, label = split_row(POLARIS_ROW)
    serialized = feature.model_dump_json()

    for field in label_only_fields():
        assert field not in serialized

    # Value-level check: catches a label smuggled into feature text rather than a field.
    # Only distinctive values are checked; a generic one like "high" would match by
    # coincidence and make the test meaningless.
    for value in POLARIS_LABEL_VALUES:
        assert value not in serialized

    assert label.event_id is not None, "fixture must carry ground truth to be a real test"


def test_feature_record_rejects_a_label_passed_directly() -> None:
    with pytest.raises(ValidationError):
        PolarisFeatureRecord(
            ticket_id="TCK-TEST-99",
            created_at="2024-03-04T11:22:33Z",
            channel="email",
            plan="growth",
            user_role="analyst",
            reported_category="billing",
            subject="",
            body="text",
            event_id="EVT-TEST-SEV1",
        )


def test_the_feature_module_does_not_import_the_label_module() -> None:
    """Boundary direction, enforced: features never depend on labels."""
    source = Path(features_module.__file__).read_text(encoding="utf-8")
    imported = _imported_modules(ast.parse(source))

    assert not any("labels" in module for module in imported), imported


@pytest.mark.parametrize("package", ["ingestion", "evaluation"])
def test_the_runtime_api_does_not_import_offline_packages(package: str) -> None:
    """Neither external data nor ground truth may be reachable from a serving path.

    `evaluation` reads label files; the API serves evaluation *artifacts* instead, and
    declares its own schema for them.
    """
    offenders = []
    for path in sorted((API_ROOT / "app").rglob("*.py")):
        imported = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        if any(module.split(".")[0] == package for module in imported):
            offenders.append(str(path.relative_to(API_ROOT)))

    assert offenders == []


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("column", LABEL_COLUMNS)
def test_losing_any_ground_truth_column_upstream_fails_loudly(column: str) -> None:
    """Each label backs a metric. If upstream drops one, ingestion must stop rather than
    quietly produce a corpus that can no longer score correlation or triage."""
    row = {key: value for key, value in POLARIS_ROW.items() if key != column}

    with pytest.raises(IngestionError, match="missing expected column"):
        split_row(row)
