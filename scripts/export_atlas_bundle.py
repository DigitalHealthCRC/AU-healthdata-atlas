"""Export a compact, denormalized data bundle for the static Atlas viewer.

Reads a kg.json snapshot (either an existing file via --kg-json, or freshly
regenerated database-free via export_kg_snapshot.export_from_sources) and
writes two artefacts into frontend/atlas/data/:

- atlas_data.json  : plain JSON bundle (for any future API use)
- atlas_data.js    : the same payload as `window.ATLAS_DATA = {...};` so the
                     viewer works when index.html is opened directly from
                     file:// with zero server and zero CORS issues.

Usage:
    uv run python .\\scripts\\export_atlas_bundle.py
    uv run python .\\scripts\\export_atlas_bundle.py --kg-json output\\kg_exports\\<ts>\\kg.json
    uv run python .\\scripts\\export_atlas_bundle.py --source-mode auto
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "frontend" / "atlas" / "data"
DEFAULT_EXPORT_ROOT = ROOT / "output" / "kg_exports"
SCHEMA_VERSION = "atlas-1"

PROVENANCE_PREFIX = "source"
PROVENANCE_EXTRA_KEYS = {"kgLoadedAt"}


def is_provenance_key(key: str) -> bool:
    return key.startswith(PROVENANCE_PREFIX) or key in PROVENANCE_EXTRA_KEYS


def strip_provenance(properties: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in properties.items() if not is_provenance_key(key)}


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_kg(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    """Return (kg payload, description of where it came from)."""
    if args.kg_json:
        kg_path = Path(args.kg_json).resolve()
        if not kg_path.is_file():
            raise SystemExit(f"--kg-json file not found: {kg_path}")
        return json.loads(kg_path.read_text(encoding="utf-8")), str(kg_path)

    from export_kg_snapshot import Neo4jExportError, export_from_neo4j, export_from_sources
    from neo4j_credentials import resolve_credential_path

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = (DEFAULT_EXPORT_ROOT / f"{timestamp}_atlas").resolve()

    manifest: dict[str, Any] | None = None
    if args.source_mode == "auto":
        try:
            cred_path = resolve_credential_path(None)
            manifest = export_from_neo4j(export_dir=export_dir, cred_path=cred_path)
        except (OSError, Neo4jExportError, FileNotFoundError) as exc:
            print(f"Live Neo4j export unavailable ({exc}); falling back to source reconstruction.")
            manifest = None
        if manifest is not None and not manifest.get("summary", {}).get("nodeCount"):
            print("Live Neo4j database is empty; falling back to source reconstruction.")
            manifest = None
    if manifest is None:
        manifest = export_from_sources(export_dir=export_dir)

    kg_path = Path(manifest["files"]["kgJson"])
    return json.loads(kg_path.read_text(encoding="utf-8")), str(kg_path)


def index_kg(kg: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    nodes_by_eid = {node["nodeElementId"]: node for node in kg["nodes"]}
    rels_by_type: dict[str, list[dict[str, Any]]] = {}
    for rel in kg["relationships"]:
        rels_by_type.setdefault(rel["type"], []).append(rel)
    return nodes_by_eid, rels_by_type


def build_bundle(kg: dict[str, Any], kg_path: str) -> dict[str, Any]:
    nodes_by_eid, rels_by_type = index_kg(kg)

    def rels(rel_type: str) -> list[dict[str, Any]]:
        return rels_by_type.get(rel_type, [])

    def end_node(rel: dict[str, Any]) -> dict[str, Any] | None:
        return nodes_by_eid.get(rel["endNodeElementId"])

    # Group relationships by start element id for quick per-custodian lookups.
    by_start: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for rel_type, rel_list in rels_by_type.items():
        for rel in rel_list:
            by_start.setdefault(rel["startNodeElementId"], {}).setdefault(rel_type, []).append(rel)

    connections_in_by_target: dict[str, list[dict[str, Any]]] = {}
    for rel in rels("CONNECTED_TO"):
        connections_in_by_target.setdefault(rel["endNodeElementId"], []).append(rel)

    custodian_nodes = sorted(
        (node for node in kg["nodes"] if node["labels"] == ["Custodian"]),
        key=lambda node: (node["properties"].get("name") or "").lower(),
    )
    custodian_name_by_id = {
        node["properties"]["id"]: node["properties"].get("name") or "" for node in custodian_nodes
    }

    custodians: list[dict[str, Any]] = []
    flat_datasets: list[dict[str, Any]] = []
    lane_counts: dict[str, int] = {}
    unique_dataset_ids: set[str] = set()
    total_steps = 0

    for node in custodian_nodes:
        eid = node["nodeElementId"]
        props = node["properties"]
        custodian_id = props["id"]
        outgoing = by_start.get(eid, {})

        type_names = sorted(
            (end_node(rel) or {}).get("properties", {}).get("name", "")
            for rel in outgoing.get("HAS_TYPE", [])
        )
        jurisdiction_names = sorted(
            (end_node(rel) or {}).get("properties", {}).get("name", "")
            for rel in outgoing.get("IN_JURISDICTION", [])
        )

        steps: list[dict[str, Any]] = []
        for line_rel in outgoing.get("OFFERS_LINE", []):
            line_eid = line_rel["endNodeElementId"]
            for step_rel in by_start.get(line_eid, {}).get("HAS_STEP", []):
                step_node = end_node(step_rel)
                if not step_node:
                    continue
                step_props = step_node["properties"]
                steps.append(
                    {
                        "order": step_rel["properties"].get("order", step_props.get("stepNumber")),
                        "lane": step_rel["properties"].get("lane") or step_props.get("lane") or "",
                        "text": step_props.get("text") or "",
                        "actor": step_props.get("actor") or "",
                        "channel": step_props.get("channel") or "",
                        "timeline": step_props.get("timeline") or "",
                    }
                )
        steps.sort(key=lambda step: step["order"] or 0)
        for step in steps:
            lane_counts[step["lane"]] = lane_counts.get(step["lane"], 0) + 1
        total_steps += len(steps)

        datasets: list[dict[str, Any]] = []
        seen_dataset_ids: set[str] = set()
        for rel in outgoing.get("HAS_DATASET", []):
            dataset_node = end_node(rel)
            if not dataset_node:
                continue
            dataset_props = dataset_node["properties"]
            dataset_id = dataset_props.get("id") or rel["endNodeElementId"]
            if dataset_id in seen_dataset_ids:
                continue
            seen_dataset_ids.add(dataset_id)
            unique_dataset_ids.add(dataset_id)
            entry = {
                "id": dataset_id,
                "name": dataset_props.get("name") or "",
                "description": dataset_props.get("description") or "",
                "identifiable": dataset_props.get("identifiable") or "",
                "linkable": dataset_props.get("linkable") or "",
                "source": rel["properties"].get("source") or "",
            }
            datasets.append(entry)
            flat_datasets.append(
                {
                    **{key: entry[key] for key in ("id", "name", "description", "identifiable", "linkable")},
                    "custodianId": custodian_id,
                    "custodianName": props.get("name") or "",
                }
            )
        datasets.sort(key=lambda dataset: dataset["name"].lower())

        sources = sorted(
            {
                (end_node(rel) or {}).get("properties", {}).get("url", "")
                for rel in outgoing.get("HAS_SOURCE", [])
            }
            - {""}
        )

        def connection_entry(rel: dict[str, Any], other_business_id: str, key: str) -> dict[str, Any]:
            rel_props = rel["properties"]
            return {
                key: other_business_id,
                key.replace("Id", "Name"): custodian_name_by_id.get(other_business_id, other_business_id),
                "segment": rel_props.get("segment") or "",
                "matchType": rel_props.get("matchType") or "",
                "matchScore": to_float(rel_props.get("matchScore")),
            }

        connections_out = sorted(
            (
                connection_entry(rel, rel["endNodeBusinessId"], "targetId")
                for rel in outgoing.get("CONNECTED_TO", [])
            ),
            key=lambda conn: conn["targetName"].lower(),
        )
        connections_in = sorted(
            (
                connection_entry(rel, rel["startNodeBusinessId"], "sourceId")
                for rel in connections_in_by_target.get(eid, [])
            ),
            key=lambda conn: conn["sourceName"].lower(),
        )

        card_markdown = props.get("mdPathwayCardMarkdown") or props.get("fullPathwayCardMarkdown") or ""

        custodians.append(
            {
                "id": custodian_id,
                "name": props.get("name") or "",
                "subject": props.get("subject") or "",
                "type": type_names[0] if type_names else "",
                "types": type_names,
                "jurisdiction": jurisdiction_names[0] if jurisdiction_names else "",
                "jurisdictions": jurisdiction_names,
                "primaryRole": props.get("primaryRole") or "",
                "sector": props.get("sector") or "",
                "researchAccess": props.get("researchAccess") or "",
                "reverify": props.get("reverify") or "",
                "ethics": props.get("ethicsAndGovernanceRequirements") or "",
                "portal": props.get("contactAndApplicationPortal") or "",
                "timeline": props.get("indicativeTimeline") or "",
                "tre": props.get("treSecureAccessPlatform") or "",
                "gaps": props.get("gapsVerifyWithCustodian") or "",
                "datasets": datasets,
                "steps": steps,
                "sources": sources,
                "connectionsOut": connections_out,
                "connectionsIn": connections_in,
                "reviewCount": len(outgoing.get("HAS_CONNECTION_REVIEW", [])),
                "cardMarkdown": card_markdown,
            }
        )

    flat_datasets.sort(key=lambda dataset: (dataset["name"].lower(), dataset["custodianName"].lower()))

    directed_connections = rels("CONNECTED_TO")
    undirected_pairs = {
        tuple(sorted((rel["startNodeBusinessId"], rel["endNodeBusinessId"])))
        for rel in directed_connections
    }

    kg_source = kg.get("source", {})
    provenance = {
        "mode": kg_source.get("mode", ""),
        "registerTitle": kg_source.get("sourceRegisterTitle", ""),
        "registerVersion": kg_source.get("sourceRegisterVersion", ""),
        "registerGenerated": kg_source.get("sourceRegisterGenerated", ""),
        "csvPath": kg_source.get("sourceCsvPath", ""),
        "markdownPath": kg_source.get("sourceMarkdownPath", ""),
        "csvSha256": kg_source.get("sourceCsvSha256", ""),
        "markdownSha256": kg_source.get("sourceMarkdownSha256", ""),
        "gitCommit": kg_source.get("sourceGitCommit", ""),
        "provenanceStatus": kg_source.get("sourceProvenanceStatus", ""),
        "kgGeneratedAt": kg.get("generatedAt", ""),
        "kgJsonPath": kg_path,
    }

    bundle = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "schemaVersion": SCHEMA_VERSION,
            "provenance": provenance,
            "counts": {
                "custodians": len(custodians),
                "datasets": len(unique_dataset_ids),
                "datasetLinks": len(flat_datasets),
                "steps": total_steps,
                "connections": len(directed_connections),
                "connectionPairs": len(undirected_pairs),
                "sourceUrls": kg.get("summary", {}).get("labelCounts", {}).get("SourceURL", 0),
                "connectionReviews": kg.get("summary", {}).get("labelCounts", {}).get("ConnectionReview", 0),
            },
            "lanes": dict(sorted(lane_counts.items())),
        },
        "custodians": custodians,
        "datasets": flat_datasets,
    }
    return bundle


def write_bundle(bundle: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    json_path = out_dir / "atlas_data.json"
    js_path = out_dir / "atlas_data.js"
    json_path.write_text(payload, encoding="utf-8")
    js_path.write_text(f"window.ATLAS_DATA = {payload};\n", encoding="utf-8")
    return json_path, js_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Atlas viewer data bundle from a KG snapshot")
    parser.add_argument("--kg-json", default="", help="Use an existing kg.json instead of regenerating")
    parser.add_argument(
        "--source-mode",
        choices=["source", "auto"],
        default="source",
        help="When regenerating: 'source' rebuilds database-free from local files; "
        "'auto' tries live Neo4j first and falls back to source",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for the bundle files")
    args = parser.parse_args()

    kg, kg_path = load_kg(args)
    bundle = build_bundle(kg, kg_path)
    json_path, js_path = write_bundle(bundle, Path(args.out_dir).resolve())

    report = {
        "kgJson": kg_path,
        "atlasDataJson": str(json_path),
        "atlasDataJs": str(js_path),
        "counts": bundle["meta"]["counts"],
        "lanes": bundle["meta"]["lanes"],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
