"""Normalization helpers for the export_from_sources golden snapshot test.

The exporter stamps volatile provenance metadata onto every node /
relationship record and into kg.json / export_manifest.json:

- run timestamps: ``generatedAt``, ``kgLoadedAt``
- source file mtimes: ``sourceCsvModifiedAt``, ``sourceMarkdownModifiedAt``
  (mtimes are unstable across machines / OneDrive sync, even when content
  is identical)
- ``sourceGitCommit`` (changes with every commit)
- machine-specific absolute paths: manifest ``exportDir`` + ``files`` values,
  kg.json ``source.csvPath`` / ``markdownPath`` / ``overridePath``
- OS-specific path separators in the repo-relative ``sourceCsvPath`` /
  ``sourceMarkdownPath`` values

These helpers replace those values with stable placeholders (recursively,
including inside the ``properties_json`` CSV columns) so that golden
comparisons only fail on real content changes. Deliberately KEPT as-is:
``sourceCsvSha256`` / ``sourceMarkdownSha256`` and all parsed content - those
change exactly when raw_data changes, which is when the golden must be
regenerated anyway.

The golden itself is stored in normalized form (normalized-vs-normalized
comparison). Because a full normalized export is ~6.5 MB, the golden stores
sha256 digests of each normalized file plus the full normalized manifest
(which carries the human-readable node/relationship counts per label/type).
Regenerate with: ``uv run python tests/regenerate_golden.py``
"""

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
DIGESTS_PATH = GOLDEN_DIR / "export_digests.json"
MANIFEST_PATH = GOLDEN_DIR / "export_manifest.normalized.json"
REGENERATE_CMD = "uv run python tests/regenerate_golden.py"

VOLATILE_VALUE_KEYS = {
    "generatedAt",
    "kgLoadedAt",
    "sourceCsvModifiedAt",
    "sourceMarkdownModifiedAt",
    "sourceGitCommit",
}
VOLATILE_PATH_KEYS = {
    "exportDir",
    "csvPath",
    "markdownPath",
    "overridePath",
    "kgJson",
    "allNodesCsv",
    "allRelationshipsCsv",
}
PATH_SEPARATOR_KEYS = {"sourceCsvPath", "sourceMarkdownPath"}
VOLATILE_PLACEHOLDER = "<volatile>"
PATH_PLACEHOLDER = "<path>"


def normalize_value(key: str, value: Any) -> Any:
    if key in VOLATILE_VALUE_KEYS:
        return VOLATILE_PLACEHOLDER
    if key in VOLATILE_PATH_KEYS:
        return PATH_PLACEHOLDER
    if key in PATH_SEPARATOR_KEYS and isinstance(value, str):
        return value.replace("\\", "/")
    return value


def normalize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                out[key] = normalize_obj(value)
            else:
                out[key] = normalize_value(key, value)
        return out
    if isinstance(obj, list):
        return [normalize_obj(item) for item in obj]
    return obj


def normalize_json_text(text: str) -> str:
    return json.dumps(normalize_obj(json.loads(text)), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _normalize_csv_cell(column: str, cell: str) -> str:
    if column == "properties_json" and cell:
        return json.dumps(normalize_obj(json.loads(cell)), ensure_ascii=False, sort_keys=True)
    return normalize_value(column, cell)


def normalize_csv_text(text: str) -> str:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ""
    header = rows[0]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows[1:]:
        writer.writerow([_normalize_csv_cell(column, cell) for column, cell in zip(header, row)])
    return buffer.getvalue()


def normalized_file_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return normalize_json_text(text)
    if path.suffix.lower() == ".csv":
        return normalize_csv_text(text)
    return text


def export_file_relpaths(export_dir: Path) -> list[str]:
    return sorted(p.relative_to(export_dir).as_posix() for p in export_dir.rglob("*") if p.is_file())


def normalized_export_digests(export_dir: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for relpath in export_file_relpaths(export_dir):
        normalized = normalized_file_text(export_dir / relpath)
        digests[relpath] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digests


def write_golden(export_dir: Path) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    digests = normalized_export_digests(export_dir)
    DIGESTS_PATH.write_text(json.dumps(digests, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(
        normalize_json_text((export_dir / "export_manifest.json").read_text(encoding="utf-8")),
        encoding="utf-8",
    )
