"""Golden snapshot test for export_from_sources (database-free, offline).

Runs the full source reconstruction into a tmp dir, normalizes away the
volatile provenance fields (timestamps, mtimes, git commit, machine paths -
see tests/golden_util.py), and compares against the checked-in golden under
tests/golden/. Both sides of the comparison are in normalized form.

If raw_data/ or config/ changed INTENTIONALLY, regenerate the golden via:

    uv run python tests/regenerate_golden.py

then review the tests/golden/ diff before committing. To skip this test while
raw_data changes are in progress: ``uv run pytest -m "not golden"``.
"""

import importlib
import json

import pytest

import golden_util as gu

pytestmark = pytest.mark.golden

REGEN_HELP = (
    "Golden snapshot mismatch. If raw_data/ or config/ changed intentionally, "
    f"regenerate the golden via: {gu.REGENERATE_CMD} "
    "(then review the tests/golden/ diff before committing). "
    "If the sources did NOT change, this is a behavior regression in "
    "register_parsing.py / export_kg_snapshot.py."
)
MISSING_GOLDEN_HELP = f"Golden files not present yet. Generate them via: {gu.REGENERATE_CMD}"


def _import_export_module():
    # export_kg_snapshot may be mid-edit by concurrent work; retry the import
    # once before giving up.
    try:
        return importlib.import_module("export_kg_snapshot")
    except Exception:
        return importlib.import_module("export_kg_snapshot")


@pytest.fixture(scope="module")
def export_dir(tmp_path_factory):
    module = _import_export_module()
    out = tmp_path_factory.mktemp("kg_export") / "export"
    module.export_from_sources(out)
    return out


def test_normalization_strips_all_volatile_fields(export_dir):
    """Sanity-check the normalization helper itself (runs even without golden)."""
    normalized = json.loads(gu.normalize_json_text((export_dir / "kg.json").read_text(encoding="utf-8")))
    assert normalized["generatedAt"] == gu.VOLATILE_PLACEHOLDER
    assert normalized["source"]["sourceGitCommit"] == gu.VOLATILE_PLACEHOLDER
    assert normalized["source"]["sourceCsvModifiedAt"] == gu.VOLATILE_PLACEHOLDER
    assert normalized["source"]["sourceMarkdownModifiedAt"] == gu.VOLATILE_PLACEHOLDER
    assert normalized["source"]["csvPath"] == gu.PATH_PLACEHOLDER
    assert normalized["source"]["markdownPath"] == gu.PATH_PLACEHOLDER
    assert normalized["source"]["overridePath"] == gu.PATH_PLACEHOLDER
    assert "\\" not in normalized["source"]["sourceCsvPath"]

    assert normalized["summary"]["nodeCount"] > 0
    assert normalized["summary"]["relationshipCount"] > 0
    assert normalized["summary"]["labelCounts"].get("Custodian", 0) > 0

    first_node_props = normalized["nodes"][0]["properties"]
    assert first_node_props["kgLoadedAt"] == gu.VOLATILE_PLACEHOLDER
    assert first_node_props["sourceGitCommit"] == gu.VOLATILE_PLACEHOLDER

    manifest = json.loads(
        gu.normalize_json_text((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    )
    assert manifest["generatedAt"] == gu.VOLATILE_PLACEHOLDER
    assert manifest["exportDir"] == gu.PATH_PLACEHOLDER
    assert set(manifest["files"].values()) == {gu.PATH_PLACEHOLDER}


def test_manifest_summary_matches_golden(export_dir):
    """Human-readable first line of defence: node/rel counts per label/type."""
    if not gu.MANIFEST_PATH.exists():
        pytest.skip(MISSING_GOLDEN_HELP)
    fresh = gu.normalize_json_text((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    golden = gu.MANIFEST_PATH.read_text(encoding="utf-8")
    assert json.loads(fresh) == json.loads(golden), REGEN_HELP


def test_all_export_files_match_golden_digests(export_dir):
    """Full-content check: sha256 of every normalized export file."""
    if not gu.DIGESTS_PATH.exists():
        pytest.skip(MISSING_GOLDEN_HELP)
    fresh = gu.normalized_export_digests(export_dir)
    golden = json.loads(gu.DIGESTS_PATH.read_text(encoding="utf-8"))
    missing = sorted(set(golden) - set(fresh))
    extra = sorted(set(fresh) - set(golden))
    changed = sorted(name for name in set(golden) & set(fresh) if golden[name] != fresh[name])
    assert not (missing or extra or changed), (
        f"{REGEN_HELP}\n"
        f"files missing vs golden: {missing}\n"
        f"files added vs golden: {extra}\n"
        f"files with changed normalized content: {changed}"
    )
