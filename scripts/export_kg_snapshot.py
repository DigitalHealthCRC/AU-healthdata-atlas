import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from load_au_health_kg_via_mcp import (
    CSV_PATH,
    MD_PATH,
    OVERRIDE_PATH,
    build_connection_matches,
    extract_aliases,
    extract_md_cards,
    extract_subject_short,
    load_connection_overrides,
    parse_csv_datasets,
    parse_md_dataset_rows,
    parse_pathway_steps,
    parse_urls,
    read_csv_rows,
    similarity,
    slugify,
    split_delimited,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CRED_PATH = ROOT / "Neo4j-e0662ca0-Created-2026-02-27.txt"
DEFAULT_EXPORT_ROOT = ROOT / "output" / "kg_exports"


def parse_credentials(path: Path) -> dict[str, str]:
    creds: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = re.match(r"^(NEO4J_[A-Z_]+)=(.+)$", line.strip())
        if match:
            creds[match.group(1)] = match.group(2)

    required = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]
    missing = [key for key in required if key not in creds]
    if missing:
        raise ValueError(f"Missing credentials in {path}: {missing}")
    return creds


def run_query(session, query: str) -> list[dict[str, Any]]:
    return [record.data() for record in session.run(query)]


def stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_node_rows(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    all_rows: list[dict[str, Any]] = []
    by_label: dict[str, list[dict[str, Any]]] = {}

    for node in nodes:
        labels = node["labels"]
        properties = node["properties"]
        base_row = {
            "node_element_id": node["nodeElementId"],
            "labels": "|".join(labels),
            "primary_label": labels[0] if labels else "",
            "business_id": stringify_cell(properties.get("id")),
            "name": stringify_cell(properties.get("name")),
            "properties_json": json.dumps(properties, ensure_ascii=False, sort_keys=True),
        }
        all_rows.append(base_row)

        for label in labels:
            label_row = {"node_element_id": node["nodeElementId"]}
            for key, value in properties.items():
                label_row[key] = stringify_cell(value)
            by_label.setdefault(label, []).append(label_row)

    return all_rows, by_label


def build_relationship_rows(
    relationships: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    all_rows: list[dict[str, Any]] = []
    by_type: dict[str, list[dict[str, Any]]] = {}

    for rel in relationships:
        properties = rel["properties"]
        base_row = {
            "relationship_element_id": rel["relationshipElementId"],
            "type": rel["type"],
            "start_node_element_id": rel["startNodeElementId"],
            "end_node_element_id": rel["endNodeElementId"],
            "properties_json": json.dumps(properties, ensure_ascii=False, sort_keys=True),
        }
        all_rows.append(base_row)

        type_row = {
            "relationship_element_id": rel["relationshipElementId"],
            "start_node_element_id": rel["startNodeElementId"],
            "end_node_element_id": rel["endNodeElementId"],
        }
        for key, value in properties.items():
            type_row[key] = stringify_cell(value)
        by_type.setdefault(rel["type"], []).append(type_row)

    return all_rows, by_type


def write_export_artifacts(
    export_dir: Path,
    nodes: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    source_info: dict[str, Any],
) -> dict[str, Any]:
    export_dir.mkdir(parents=True, exist_ok=True)
    nodes_dir = export_dir / "nodes"
    relationships_dir = export_dir / "relationships"
    node_rows, node_rows_by_label = build_node_rows(nodes)
    relationship_rows, relationship_rows_by_type = build_relationship_rows(relationships)

    write_csv(
        nodes_dir / "all_nodes.csv",
        node_rows,
        ["node_element_id", "labels", "primary_label", "business_id", "name", "properties_json"],
    )
    for label, rows in sorted(node_rows_by_label.items()):
        property_keys = sorted({key for row in rows for key in row.keys() if key != "node_element_id"})
        write_csv(nodes_dir / f"{sanitize_name(label)}.csv", rows, ["node_element_id", *property_keys])

    write_csv(
        relationships_dir / "all_relationships.csv",
        relationship_rows,
        [
            "relationship_element_id",
            "type",
            "start_node_element_id",
            "end_node_element_id",
            "properties_json",
        ],
    )
    for rel_type, rows in sorted(relationship_rows_by_type.items()):
        property_keys = sorted(
            {
                key
                for row in rows
                for key in row.keys()
                if key not in {"relationship_element_id", "start_node_element_id", "end_node_element_id"}
            }
        )
        write_csv(
            relationships_dir / f"{sanitize_name(rel_type)}.csv",
            rows,
            ["relationship_element_id", "start_node_element_id", "end_node_element_id", *property_keys],
        )

    label_counts: dict[str, int] = {}
    for node in nodes:
        for label in node["labels"]:
            label_counts[label] = label_counts.get(label, 0) + 1

    relationship_type_counts: dict[str, int] = {}
    for rel in relationships:
        relationship_type_counts[rel["type"]] = relationship_type_counts.get(rel["type"], 0) + 1

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": source_info,
        "summary": {
            "nodeCount": len(nodes),
            "relationshipCount": len(relationships),
            "labelCounts": dict(sorted(label_counts.items())),
            "relationshipTypeCounts": dict(sorted(relationship_type_counts.items())),
        },
        "nodes": nodes,
        "relationships": relationships,
    }
    (export_dir / "kg.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "generatedAt": payload["generatedAt"],
        "exportDir": str(export_dir),
        "files": {
            "kgJson": str(export_dir / "kg.json"),
            "allNodesCsv": str(nodes_dir / "all_nodes.csv"),
            "allRelationshipsCsv": str(relationships_dir / "all_relationships.csv"),
        },
        "summary": payload["summary"],
    }
    (export_dir / "export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def export_from_neo4j(export_dir: Path, cred_path: Path) -> dict[str, Any]:
    creds = parse_credentials(cred_path)
    driver = GraphDatabase.driver(
        creds["NEO4J_URI"],
        auth=(creds["NEO4J_USERNAME"], creds["NEO4J_PASSWORD"]),
    )

    try:
        with driver.session(database=creds["NEO4J_DATABASE"]) as session:
            nodes = run_query(
                session,
                """
                MATCH (n)
                RETURN
                  elementId(n) AS nodeElementId,
                  labels(n) AS labels,
                  properties(n) AS properties
                ORDER BY labels(n), coalesce(n.id, n.name, elementId(n))
                """,
            )
            relationships = run_query(
                session,
                """
                MATCH (a)-[r]->(b)
                RETURN
                  elementId(r) AS relationshipElementId,
                  type(r) AS type,
                  elementId(a) AS startNodeElementId,
                  elementId(b) AS endNodeElementId,
                  properties(r) AS properties
                ORDER BY type(r), elementId(a), elementId(b), elementId(r)
                """,
            )
    finally:
        driver.close()

    return write_export_artifacts(
        export_dir=export_dir,
        nodes=nodes,
        relationships=relationships,
        source_info={
            "mode": "neo4j",
            "uri": creds["NEO4J_URI"],
            "database": creds["NEO4J_DATABASE"],
        },
    )


def make_node_ref(label: str, identity: str) -> str:
    return f"{label}|{identity}"


def export_from_sources(export_dir: Path) -> dict[str, Any]:
    custodians = read_csv_rows(CSV_PATH)
    overrides = load_connection_overrides(OVERRIDE_PATH)
    md_text = MD_PATH.read_text(encoding="utf-8")
    cards = extract_md_cards(md_text)

    title_to_custodian_id: dict[str, str] = {}
    for title, _ in cards:
        best_id = None
        best_score = 0.0
        for custodian in custodians:
            subject_short = extract_subject_short(custodian.row.get("Subject") or "")
            score = max(similarity(title, custodian.name), similarity(title, subject_short))
            if score > best_score:
                best_score = score
                best_id = custodian.custodian_id
        if best_id and best_score >= 0.55:
            title_to_custodian_id[title] = best_id

    md_cards_by_custodian_id: dict[str, str] = {}
    md_datasets_by_custodian_id: dict[str, list[dict[str, str]]] = {}
    for title, card_body in cards:
        custodian_id = title_to_custodian_id.get(title)
        if not custodian_id:
            continue
        md_cards_by_custodian_id[custodian_id] = card_body
        md_datasets_by_custodian_id[custodian_id] = parse_md_dataset_rows(card_body)

    datasets_by_custodian_id: dict[str, list[dict[str, str]]] = {}
    aliases_by_id: dict[str, set[str]] = {}
    for custodian in custodians:
        csv_sets = parse_csv_datasets(custodian.row.get("Key Datasets") or "")
        md_sets = md_datasets_by_custodian_id.get(custodian.custodian_id, [])
        datasets_by_custodian_id[custodian.custodian_id] = md_sets + csv_sets

        title = ""
        for candidate_title, candidate_id in title_to_custodian_id.items():
            if candidate_id == custodian.custodian_id:
                title = candidate_title
                break
        aliases_by_id[custodian.custodian_id] = extract_aliases(
            custodian.name,
            custodian.row.get("Subject") or "",
            title,
        )

    accepted_connections, review_connections = build_connection_matches(custodians, aliases_by_id, overrides)

    nodes: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    node_seen: set[str] = set()
    rel_seen: set[str] = set()

    def add_node(label: str, identity: str, properties: dict[str, Any]) -> str:
        node_ref = make_node_ref(label, identity)
        if node_ref not in node_seen:
            nodes.append(
                {
                    "nodeElementId": node_ref,
                    "labels": [label],
                    "properties": properties,
                }
            )
            node_seen.add(node_ref)
        return node_ref

    def add_relationship(
        rel_type: str,
        start_ref: str,
        end_ref: str,
        properties: dict[str, Any] | None = None,
        identity: str | None = None,
    ) -> None:
        relationship_id = identity or f"{rel_type}|{start_ref}|{end_ref}|{json.dumps(properties or {}, sort_keys=True)}"
        if relationship_id in rel_seen:
            return
        relationships.append(
            {
                "relationshipElementId": relationship_id,
                "type": rel_type,
                "startNodeElementId": start_ref,
                "endNodeElementId": end_ref,
                "properties": properties or {},
            }
        )
        rel_seen.add(relationship_id)

    dataset_nodes_map: dict[str, dict[str, Any]] = {}
    for custodian in custodians:
        row = custodian.row
        subject = (row.get("Subject") or "").strip()
        md_card = md_cards_by_custodian_id.get(custodian.custodian_id, "")
        custodian_ref = add_node(
            "Custodian",
            custodian.custodian_id,
            {
                "id": custodian.custodian_id,
                "name": custodian.name,
                "subject": subject,
                "primaryRole": row.get("Primary Role") or "",
                "ethicsAndGovernanceRequirements": row.get("Ethics and Governance Requirements") or "",
                "treSecureAccessPlatform": row.get("TRE / Secure Access Platform") or "",
                "contactAndApplicationPortal": row.get("Contact and Application Portal") or "",
                "indicativeTimeline": row.get("Indicative Timeline") or "",
                "gapsVerifyWithCustodian": row.get("Gaps / Verify with Custodian") or "",
                "fullPathwayCardMarkdown": row.get("Full Pathway Card (Markdown)") or "",
                "mdPathwayCardMarkdown": md_card,
            },
        )

        for custodian_type in split_delimited(row.get("Custodian Type") or ""):
            type_ref = add_node("CustodianType", custodian_type, {"name": custodian_type})
            add_relationship("HAS_TYPE", custodian_ref, type_ref, identity=f"HAS_TYPE|{custodian_ref}|{type_ref}")

        for jurisdiction in split_delimited(row.get("Jurisdiction") or ""):
            jurisdiction_ref = add_node("Jurisdiction", jurisdiction, {"name": jurisdiction})
            add_relationship(
                "IN_JURISDICTION",
                custodian_ref,
                jurisdiction_ref,
                identity=f"IN_JURISDICTION|{custodian_ref}|{jurisdiction_ref}",
            )

        line_id = f"line:{custodian.custodian_id}"
        line_ref = add_node("ProcessLine", line_id, {"id": line_id, "name": custodian.name})
        add_relationship("OFFERS_LINE", custodian_ref, line_ref, identity=f"OFFERS_LINE|{custodian_ref}|{line_ref}")

        for step in parse_pathway_steps(row.get("Access Pathway Steps") or ""):
            step_id = f"step:{custodian.custodian_id}:{step['number']}"
            step_ref = add_node(
                "PathwayStep",
                step_id,
                {
                    "id": step_id,
                    "text": step["text"],
                    "stepNumber": step["number"],
                    "actor": step["actor"],
                    "channel": step["channel"],
                    "timeline": step["timeline"],
                    "lane": step["lane"],
                },
            )
            add_relationship(
                "HAS_STEP",
                line_ref,
                step_ref,
                {"order": step["number"], "lane": step["lane"]},
                identity=f"HAS_STEP|{line_ref}|{step_ref}",
            )

        for url in parse_urls(row.get("Source URLs") or ""):
            url_ref = add_node("SourceURL", url, {"url": url})
            add_relationship("HAS_SOURCE", custodian_ref, url_ref, identity=f"HAS_SOURCE|{custodian_ref}|{url_ref}")

        for dataset in datasets_by_custodian_id.get(custodian.custodian_id, []):
            dataset_name = dataset["name"].strip()
            if not dataset_name:
                continue
            dataset_id = f"dataset:{slugify(dataset_name)}"
            existing = dataset_nodes_map.get(dataset_id)
            if not existing:
                dataset_nodes_map[dataset_id] = {
                    "id": dataset_id,
                    "name": dataset_name,
                    "description": dataset.get("description") or "",
                    "identifiable": dataset.get("identifiable") or "",
                    "linkable": dataset.get("linkable") or "",
                }
            else:
                if not existing["description"] and dataset.get("description"):
                    existing["description"] = dataset["description"]
                if not existing["identifiable"] and dataset.get("identifiable"):
                    existing["identifiable"] = dataset["identifiable"]
                if not existing["linkable"] and dataset.get("linkable"):
                    existing["linkable"] = dataset["linkable"]

            dataset_ref = add_node("Dataset", dataset_id, dataset_nodes_map[dataset_id])
            add_relationship(
                "HAS_DATASET",
                custodian_ref,
                dataset_ref,
                {"source": dataset.get("source") or "csv"},
                identity=f"HAS_DATASET|{custodian_ref}|{dataset_ref}|{dataset.get('source') or 'csv'}",
            )

    for edge in accepted_connections:
        source_ref = make_node_ref("Custodian", edge["sourceId"])
        target_ref = make_node_ref("Custodian", edge["targetId"])
        add_relationship(
            "CONNECTED_TO",
            source_ref,
            target_ref,
            {
                "segment": edge["segment"],
                "rawText": edge["rawText"],
                "matchScore": edge["score"],
                "matchType": edge["matchType"],
            },
            identity=f"CONNECTED_TO|{source_ref}|{target_ref}",
        )

    for review in review_connections:
        review_ref = add_node(
            "ConnectionReview",
            review["id"],
            {
                "id": review["id"],
                "segment": review["segment"],
                "rawText": review["rawText"],
                "candidateCustodian": review["candidateCustodian"],
                "score": review["score"],
                "matchType": review["matchType"],
                "status": review["status"],
            },
        )
        source_ref = make_node_ref("Custodian", review["sourceId"])
        add_relationship(
            "HAS_CONNECTION_REVIEW",
            source_ref,
            review_ref,
            identity=f"HAS_CONNECTION_REVIEW|{source_ref}|{review_ref}",
        )
        if review.get("targetId"):
            target_ref = make_node_ref("Custodian", review["targetId"])
            add_relationship(
                "REVIEW_SUGGESTS",
                review_ref,
                target_ref,
                {"score": review["score"]},
                identity=f"REVIEW_SUGGESTS|{review_ref}|{target_ref}",
            )

    return write_export_artifacts(
        export_dir=export_dir,
        nodes=nodes,
        relationships=relationships,
        source_info={
            "mode": "raw_source_reconstruction",
            "csvPath": str(CSV_PATH),
            "markdownPath": str(MD_PATH),
            "overridePath": str(OVERRIDE_PATH),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Neo4j KG to local JSON and CSV snapshots")
    parser.add_argument("--cred-path", default=str(DEFAULT_CRED_PATH))
    parser.add_argument("--out-dir", default="")
    parser.add_argument(
        "--source-mode",
        choices=["auto", "neo4j", "source"],
        default="auto",
        help="Export from live Neo4j, reconstruct from local source files, or try Neo4j then fallback to source",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = Path(args.out_dir).resolve() if args.out_dir else (DEFAULT_EXPORT_ROOT / timestamp).resolve()

    if args.source_mode == "neo4j":
        manifest = export_from_neo4j(export_dir=export_dir, cred_path=Path(args.cred_path).resolve())
    elif args.source_mode == "source":
        manifest = export_from_sources(export_dir=export_dir)
    else:
        try:
            manifest = export_from_neo4j(export_dir=export_dir, cred_path=Path(args.cred_path).resolve())
        except (OSError, ServiceUnavailable, Neo4jError):
            manifest = export_from_sources(export_dir=export_dir)

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
