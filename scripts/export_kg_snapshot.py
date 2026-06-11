import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from load_au_health_kg_via_mcp import (
    CSV_PATH,
    MD_PATH,
    OVERRIDE_PATH,
    apply_iteration2_remediations,
    build_connection_matches,
    build_source_metadata,
    ensure_dataset_coverage,
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
from neo4j_credentials import DEFAULT_CRED_PATH, parse_credentials, resolve_credential_path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_ROOT = ROOT / "output" / "kg_exports"


class Neo4jExportError(RuntimeError):
    pass


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
            "start_node_business_id": stringify_cell(rel.get("startNodeBusinessId")),
            "start_node_labels": "|".join(rel.get("startNodeLabels") or []),
            "end_node_business_id": stringify_cell(rel.get("endNodeBusinessId")),
            "end_node_labels": "|".join(rel.get("endNodeLabels") or []),
            "properties_json": json.dumps(properties, ensure_ascii=False, sort_keys=True),
        }
        all_rows.append(base_row)

        type_row = {
            "relationship_element_id": rel["relationshipElementId"],
            "start_node_element_id": rel["startNodeElementId"],
            "end_node_element_id": rel["endNodeElementId"],
            "start_node_business_id": stringify_cell(rel.get("startNodeBusinessId")),
            "start_node_labels": "|".join(rel.get("startNodeLabels") or []),
            "end_node_business_id": stringify_cell(rel.get("endNodeBusinessId")),
            "end_node_labels": "|".join(rel.get("endNodeLabels") or []),
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
            "start_node_business_id",
            "start_node_labels",
            "end_node_business_id",
            "end_node_labels",
            "properties_json",
        ],
    )
    for rel_type, rows in sorted(relationship_rows_by_type.items()):
        property_keys = sorted(
            {
                key
                for row in rows
                for key in row.keys()
                if key
                not in {
                    "relationship_element_id",
                    "start_node_element_id",
                    "end_node_element_id",
                    "start_node_business_id",
                    "start_node_labels",
                    "end_node_business_id",
                    "end_node_labels",
                }
            }
        )
        write_csv(
            relationships_dir / f"{sanitize_name(rel_type)}.csv",
            rows,
            [
                "relationship_element_id",
                "start_node_element_id",
                "end_node_element_id",
                "start_node_business_id",
                "start_node_labels",
                "end_node_business_id",
                "end_node_labels",
                *property_keys,
            ],
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
    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import Neo4jError, ServiceUnavailable
    except ImportError as exc:
        raise Neo4jExportError("The neo4j package is required for --source-mode neo4j. Run uv sync first.") from exc

    creds = parse_credentials(cred_path)
    driver = None

    try:
        driver = GraphDatabase.driver(
            creds["NEO4J_URI"],
            auth=(creds["NEO4J_USERNAME"], creds["NEO4J_PASSWORD"]),
        )
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
                  coalesce(a.id, a.name, elementId(a)) AS startNodeBusinessId,
                  labels(a) AS startNodeLabels,
                  coalesce(b.id, b.name, elementId(b)) AS endNodeBusinessId,
                  labels(b) AS endNodeLabels,
                  properties(r) AS properties
                ORDER BY type(r), elementId(a), elementId(b), elementId(r)
                """,
            )
    except (OSError, ServiceUnavailable, Neo4jError) as exc:
        raise Neo4jExportError(f"Live Neo4j export failed: {exc}") from exc
    finally:
        if driver is not None:
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


def parse_node_ref(node_ref: str) -> tuple[str, str]:
    label, _, identity = node_ref.partition("|")
    return label, identity


def export_from_sources(export_dir: Path) -> dict[str, Any]:
    custodians = apply_iteration2_remediations(read_csv_rows(CSV_PATH))
    overrides = load_connection_overrides(OVERRIDE_PATH)
    md_text = MD_PATH.read_text(encoding="utf-8")
    cards = extract_md_cards(md_text)
    source_metadata = build_source_metadata(
        md_text,
        custodian_row_count=len(custodians),
        markdown_card_count=len(cards),
        override_rule_count=len(overrides),
    )
    export_generated_at = datetime.now(timezone.utc).isoformat()
    source_props = {**source_metadata, "kgLoadedAt": export_generated_at}

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
        datasets_by_custodian_id[custodian.custodian_id] = ensure_dataset_coverage(custodian, md_sets + csv_sets)

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

    accepted_connections, review_connections, gap_custodians = build_connection_matches(custodians, aliases_by_id, overrides)
    accepted_connections = [{**edge, **source_props} for edge in accepted_connections]
    review_connections = [{**review, **source_props} for review in review_connections]

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
                "startNodeBusinessId": parse_node_ref(start_ref)[1],
                "startNodeLabels": [parse_node_ref(start_ref)[0]],
                "endNodeBusinessId": parse_node_ref(end_ref)[1],
                "endNodeLabels": [parse_node_ref(end_ref)[0]],
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
                **source_props,
            },
        )

        for custodian_type in split_delimited(row.get("Custodian Type") or ""):
            type_ref = add_node("CustodianType", custodian_type, {"name": custodian_type, **source_props})
            add_relationship(
                "HAS_TYPE",
                custodian_ref,
                type_ref,
                source_props,
                identity=f"HAS_TYPE|{custodian_ref}|{type_ref}",
            )

        for jurisdiction in split_delimited(row.get("Jurisdiction") or ""):
            jurisdiction_ref = add_node("Jurisdiction", jurisdiction, {"name": jurisdiction, **source_props})
            add_relationship(
                "IN_JURISDICTION",
                custodian_ref,
                jurisdiction_ref,
                source_props,
                identity=f"IN_JURISDICTION|{custodian_ref}|{jurisdiction_ref}",
            )

        line_id = f"line:{custodian.custodian_id}"
        line_ref = add_node("ProcessLine", line_id, {"id": line_id, "name": custodian.name, **source_props})
        add_relationship(
            "OFFERS_LINE",
            custodian_ref,
            line_ref,
            source_props,
            identity=f"OFFERS_LINE|{custodian_ref}|{line_ref}",
        )

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
                    **source_props,
                },
            )
            add_relationship(
                "HAS_STEP",
                line_ref,
                step_ref,
                {"order": step["number"], "lane": step["lane"], **source_props},
                identity=f"HAS_STEP|{line_ref}|{step_ref}",
            )

        for url in parse_urls(row.get("Source URLs") or ""):
            url_ref = add_node("SourceURL", url, {"url": url, **source_props})
            add_relationship(
                "HAS_SOURCE",
                custodian_ref,
                url_ref,
                source_props,
                identity=f"HAS_SOURCE|{custodian_ref}|{url_ref}",
            )

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
                    **source_props,
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
                {"source": dataset.get("source") or "csv", **source_props},
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
                **source_props,
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
                **source_props,
            },
        )
        source_ref = make_node_ref("Custodian", review["sourceId"])
        add_relationship(
            "HAS_CONNECTION_REVIEW",
            source_ref,
            review_ref,
            source_props,
            identity=f"HAS_CONNECTION_REVIEW|{source_ref}|{review_ref}",
        )
        if review.get("targetId"):
            target_ref = make_node_ref("Custodian", review["targetId"])
            add_relationship(
                "REVIEW_SUGGESTS",
                review_ref,
                target_ref,
                {"score": review["score"], **source_props},
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
            "gapCustodianCount": len(gap_custodians),
            **source_metadata,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the Neo4j KG to local JSON and CSV snapshots")
    parser.add_argument(
        "--cred-path",
        default=None,
        help=f"Neo4j credential file path. Defaults to {DEFAULT_CRED_PATH.name} or NEO4J_CREDENTIAL_FILE.",
    )
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
    cred_path = resolve_credential_path(args.cred_path)

    if args.source_mode == "neo4j":
        manifest = export_from_neo4j(export_dir=export_dir, cred_path=cred_path)
    elif args.source_mode == "source":
        manifest = export_from_sources(export_dir=export_dir)
    else:
        try:
            manifest = export_from_neo4j(export_dir=export_dir, cred_path=cred_path)
        except (OSError, Neo4jExportError):
            manifest = export_from_sources(export_dir=export_dir)

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
