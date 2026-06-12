"""Regenerate the golden snapshot for the export_from_sources test.

Run this after INTENTIONAL changes to raw_data/ or config/, then review the
diff of tests/golden/ before committing:

    uv run python tests/regenerate_golden.py

It runs the database-free source reconstruction into a temporary directory,
normalizes away volatile provenance fields (see tests/golden_util.py), and
writes:

- tests/golden/export_digests.json            sha256 per normalized file
- tests/golden/export_manifest.normalized.json  human-readable summary
                                                (node/relationship counts)
"""

import sys
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
for entry in (str(TESTS_DIR), str(TESTS_DIR.parent / "scripts")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import golden_util  # noqa: E402


def main() -> None:
    from export_kg_snapshot import export_from_sources

    with tempfile.TemporaryDirectory() as tmp:
        export_dir = Path(tmp) / "export"
        manifest = export_from_sources(export_dir)
        golden_util.write_golden(export_dir)
        summary = manifest.get("summary", {})
        print(f"Golden files written to {golden_util.GOLDEN_DIR}")
        print(f"nodes={summary.get('nodeCount')} relationships={summary.get('relationshipCount')}")


if __name__ == "__main__":
    main()
