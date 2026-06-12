import argparse
import asyncio
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from export_kg_snapshot import Neo4jExportError, export_from_neo4j
from neo4j_credentials import DEFAULT_CRED_PATH, parse_credentials, resolve_credential_path
from register_parsing import (
    CSV_PATH,
    MD_PATH,
    OVERRIDE_PATH,
    SOURCE_METADATA_FIELDS,
    CustodianRow,
    apply_iteration2_remediations,
    build_connection_matches,
    build_source_metadata,
    ensure_dataset_coverage,
    extract_aliases,
    extract_md_cards,
    extract_subject_short,
    load_connection_overrides,
    normalize_custodian_type_name,
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
OUT_DIR = ROOT / "output"
REVIEW_CSV = OUT_DIR / "connection_match_review.csv"
SUMMARY_JSON = OUT_DIR / "kg_load_summary.json"
GAP_JSON = OUT_DIR / "gap_custodians.json"
DRYRUN_REVIEW_CSV = OUT_DIR / "connection_match_review_dryrun.csv"
DRYRUN_SUMMARY_JSON = OUT_DIR / "kg_load_summary_dryrun.json"
DRYRUN_GAP_JSON = OUT_DIR / "gap_custodians_dryrun.json"
BACKUP_ROOT = OUT_DIR / "kg_exports"

CONSTRAINT_QUERIES = [
    "CREATE CONSTRAINT Custodian_constraint IF NOT EXISTS FOR (n:Custodian) REQUIRE (n.id) IS NODE KEY;",
    "CREATE CONSTRAINT CustodianType_constraint IF NOT EXISTS FOR (n:CustodianType) REQUIRE (n.name) IS NODE KEY;",
    "CREATE CONSTRAINT Jurisdiction_constraint IF NOT EXISTS FOR (n:Jurisdiction) REQUIRE (n.name) IS NODE KEY;",
    "CREATE CONSTRAINT Dataset_constraint IF NOT EXISTS FOR (n:Dataset) REQUIRE (n.id) IS NODE KEY;",
    "CREATE CONSTRAINT PathwayStep_constraint IF NOT EXISTS FOR (n:PathwayStep) REQUIRE (n.id) IS NODE KEY;",
    "CREATE CONSTRAINT ProcessLine_constraint IF NOT EXISTS FOR (n:ProcessLine) REQUIRE (n.id) IS NODE KEY;",
    "CREATE CONSTRAINT SourceURL_constraint IF NOT EXISTS FOR (n:SourceURL) REQUIRE (n.url) IS NODE KEY;",
    "CREATE CONSTRAINT ConnectionReview_constraint IF NOT EXISTS FOR (n:ConnectionReview) REQUIRE (n.id) IS NODE KEY;",
]

SOURCE_SET_CLAUSE = ",\n                    ".join(f"{{alias}}.{field} = row.{field}" for field in SOURCE_METADATA_FIELDS)


def source_set_clause(alias: str, indent: int = 20) -> str:
    spacing = " " * indent
    return SOURCE_SET_CLAUSE.format(alias=alias).replace("\n                    ", "\n" + spacing)


def call_tool_text(result: Any) -> str:
    # CallToolResult content is list[TextContent]
    if not getattr(result, "content", None):
        return ""
    first = result.content[0]
    return getattr(first, "text", "")


def mcp_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    # uvx hardlink installs fail under OneDrive (os error 396); copy mode is reliable.
    env = {**os.environ, **(extra or {})}
    env.setdefault("UV_LINK_MODE", "copy")
    return env


async def validate_servers(creds: dict[str, str]) -> dict[str, Any]:
    data_modeling = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"],
        env=mcp_subprocess_env(),
    )
    cypher = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-cypher@0.5.3", "--transport", "stdio"],
        env=mcp_subprocess_env(creds),
    )

    validation: dict[str, Any] = {}

    async with stdio_client(data_modeling) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            dm_resources = await s.list_resources()
            dm_tools = await s.list_tools()
            dm_examples = await s.call_tool("list_example_data_models", {})
            validation["data_modeling"] = {
                "resource_count": len(dm_resources.resources),
                "tool_count": len(dm_tools.tools),
                "example_call_ok": bool(call_tool_text(dm_examples)),
            }

    async with stdio_client(cypher) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            cy_tools = await s.list_tools()
            cy_read = await s.call_tool("read_neo4j_cypher", {"query": "RETURN 1 AS ok"})
            validation["cypher"] = {
                "tools": [t.name for t in cy_tools.tools],
                "read_probe": call_tool_text(cy_read),
            }

    return validation


async def run_cypher_write(session: ClientSession, query: str, params: dict[str, Any] | None = None) -> str:
    result = await session.call_tool("write_neo4j_cypher", {"query": query, "params": params or {}})
    return call_tool_text(result)


async def run_cypher_read(session: ClientSession, query: str, params: dict[str, Any] | None = None) -> Any:
    result = await session.call_tool("read_neo4j_cypher", {"query": query, "params": params or {}})
    text = call_tool_text(result)
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [{"_raw": text}]


async def load_graph(
    creds: dict[str, str],
    custodians: list[CustodianRow],
    md_cards_by_custodian_id: dict[str, str],
    datasets_by_custodian_id: dict[str, list[dict[str, str]]],
    connections_accepted: list[dict[str, Any]],
    connections_review: list[dict[str, Any]],
    source_metadata: dict[str, str],
) -> dict[str, Any]:
    cypher = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-cypher@0.5.3", "--transport", "stdio"],
        env=mcp_subprocess_env(creds),
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kg_loaded_at = datetime.now(timezone.utc).isoformat()
    source_props = {**source_metadata, "kgLoadedAt": kg_loaded_at}

    # Build node rows
    custodian_nodes: list[dict[str, Any]] = []
    custodian_types: list[dict[str, str]] = []
    jurisdictions: list[dict[str, str]] = []
    process_lines: list[dict[str, str]] = []
    pathway_steps: list[dict[str, Any]] = []
    source_urls: list[dict[str, str]] = []
    cust_source_urls: list[dict[str, str]] = []

    dataset_nodes_map: dict[str, dict[str, Any]] = {}
    cust_dataset_rels: list[dict[str, Any]] = []

    for c in custodians:
        row = c.row
        subject = (row.get("Subject") or "").strip()
        line_id = f"line:{c.custodian_id}"
        md_card = (row.get("Full Pathway Card (Markdown)") or "").strip() or md_cards_by_custodian_id.get(c.custodian_id, "")

        custodian_nodes.append(
            {
                "id": c.custodian_id,
                "props": {
                    "name": c.name,
                    "subject": subject,
                    "primaryRole": row.get("Primary Role") or "",
                    "sector": row.get("Sector") or "",
                    "researchAccess": row.get("Research Access") or "",
                    "reverify": row.get("Reverify") or "",
                    "ethicsAndGovernanceRequirements": row.get("Ethics and Governance Requirements") or "",
                    "treSecureAccessPlatform": row.get("TRE / Secure Access Platform") or "",
                    "contactAndApplicationPortal": row.get("Contact and Application Portal") or "",
                    "indicativeTimeline": row.get("Indicative Timeline") or "",
                    "gapsVerifyWithCustodian": row.get("Gaps / Verify with Custodian") or "",
                    "fullPathwayCardMarkdown": row.get("Full Pathway Card (Markdown)") or "",
                    "mdPathwayCardMarkdown": md_card,
                    **source_props,
                },
            }
        )

        for t in split_delimited(row.get("Custodian Type") or ""):
            custodian_types.append({"custodianId": c.custodian_id, "type": normalize_custodian_type_name(t), **source_props})

        for j in split_delimited(row.get("Jurisdiction") or ""):
            jurisdictions.append({"custodianId": c.custodian_id, "jurisdiction": j, **source_props})

        process_lines.append({"lineId": line_id, "name": c.name, "custodianId": c.custodian_id, **source_props})

        for step in parse_pathway_steps(row.get("Access Pathway Steps") or ""):
            step_id = f"step:{c.custodian_id}:{step['number']}"
            pathway_steps.append(
                {
                    "lineId": line_id,
                    "stepId": step_id,
                    "stepNumber": step["number"],
                    "text": step["text"],
                    "actor": step["actor"],
                    "channel": step["channel"],
                    "timeline": step["timeline"],
                    "lane": step["lane"],
                    **source_props,
                }
            )

        urls = parse_urls(row.get("Source URLs") or "")
        for url in urls:
            source_urls.append({"url": url})
            cust_source_urls.append({"custodianId": c.custodian_id, "url": url, **source_props})

        for ds in datasets_by_custodian_id.get(c.custodian_id, []):
            ds_name = ds["name"].strip()
            if not ds_name:
                continue
            ds_id = f"dataset:{slugify(ds_name)}"
            existing = dataset_nodes_map.get(ds_id)
            if not existing:
                dataset_nodes_map[ds_id] = {
                    "id": ds_id,
                    "name": ds_name,
                    "description": ds.get("description") or "",
                    "identifiable": ds.get("identifiable") or "",
                    "linkable": ds.get("linkable") or "",
                    **source_props,
                }
            else:
                if not existing["description"] and ds.get("description"):
                    existing["description"] = ds["description"]
                if not existing["identifiable"] and ds.get("identifiable"):
                    existing["identifiable"] = ds["identifiable"]
                if not existing["linkable"] and ds.get("linkable"):
                    existing["linkable"] = ds["linkable"]
            cust_dataset_rels.append(
                {
                    "custodianId": c.custodian_id,
                    "datasetId": ds_id,
                    "source": ds.get("source") or "csv",
                    **source_props,
                }
            )

    dataset_nodes = list(dataset_nodes_map.values())
    source_urls = [{**u, **source_props} for u in {u["url"]: u for u in source_urls}.values()]
    connections_accepted = [{**edge, **source_props} for edge in connections_accepted]
    connections_review = [{**item, **source_props} for item in connections_review]

    async with stdio_client(cypher) as (rd, wr):
        async with ClientSession(rd, wr) as session:
            await session.initialize()

            # Wipe and reload
            await run_cypher_write(session, "MATCH (n) DETACH DELETE n")
            for q in CONSTRAINT_QUERIES:
                await run_cypher_write(session, q)

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (c:Custodian {id: row.id})
                SET c += row.props
                """,
                {"rows": custodian_nodes},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (t:CustodianType {name: row.type})
                SET __SOURCE_SET__
                WITH row, t
                MATCH (c:Custodian {id: row.custodianId})
                MERGE (c)-[r:HAS_TYPE]->(t)
                SET __REL_SOURCE_SET__
                """
                .replace("__SOURCE_SET__", source_set_clause("t"))
                .replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": custodian_types},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (j:Jurisdiction {name: row.jurisdiction})
                SET __SOURCE_SET__
                WITH row, j
                MATCH (c:Custodian {id: row.custodianId})
                MERGE (c)-[r:IN_JURISDICTION]->(j)
                SET __REL_SOURCE_SET__
                """
                .replace("__SOURCE_SET__", source_set_clause("j"))
                .replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": jurisdictions},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (l:ProcessLine {id: row.lineId})
                SET l.name = row.name,
                    __LINE_SOURCE_SET__
                WITH row, l
                MATCH (c:Custodian {id: row.custodianId})
                MERGE (c)-[r:OFFERS_LINE]->(l)
                SET __REL_SOURCE_SET__
                """
                .replace("__LINE_SOURCE_SET__", source_set_clause("l"))
                .replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": process_lines},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (s:PathwayStep {id: row.stepId})
                SET s.text = row.text,
                    s.stepNumber = row.stepNumber,
                    s.actor = row.actor,
                    s.channel = row.channel,
                    s.timeline = row.timeline,
                    s.lane = row.lane,
                    __STEP_SOURCE_SET__
                WITH row, s
                MATCH (l:ProcessLine {id: row.lineId})
                MERGE (l)-[r:HAS_STEP]->(s)
                SET r.order = row.stepNumber,
                    r.lane = row.lane,
                    __REL_SOURCE_SET__
                """
                .replace("__STEP_SOURCE_SET__", source_set_clause("s"))
                .replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": pathway_steps},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (d:Dataset {id: row.id})
                SET d.name = row.name,
                    d.description = row.description,
                    d.identifiable = row.identifiable,
                    d.linkable = row.linkable,
                    __DATASET_SOURCE_SET__
                """.replace("__DATASET_SOURCE_SET__", source_set_clause("d")),
                {"rows": dataset_nodes},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MATCH (c:Custodian {id: row.custodianId})
                MATCH (d:Dataset {id: row.datasetId})
                MERGE (c)-[r:HAS_DATASET]->(d)
                SET r.source = row.source,
                    __REL_SOURCE_SET__
                """.replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": cust_dataset_rels},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (s:SourceURL {url: row.url})
                SET __SOURCE_SET__
                """.replace("__SOURCE_SET__", source_set_clause("s")),
                {"rows": source_urls},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MATCH (c:Custodian {id: row.custodianId})
                MATCH (s:SourceURL {url: row.url})
                MERGE (c)-[r:HAS_SOURCE]->(s)
                SET __REL_SOURCE_SET__
                """.replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": cust_source_urls},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MATCH (a:Custodian {id: row.sourceId})
                MATCH (b:Custodian {id: row.targetId})
                MERGE (a)-[r:CONNECTED_TO]->(b)
                SET r.segment = row.segment,
                    r.rawText = row.rawText,
                    r.matchScore = row.score,
                    r.matchType = row.matchType,
                    __REL_SOURCE_SET__
                """.replace("__REL_SOURCE_SET__", source_set_clause("r")),
                {"rows": connections_accepted},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (cr:ConnectionReview {id: row.id})
                SET cr.segment = row.segment,
                    cr.rawText = row.rawText,
                    cr.candidateCustodian = row.candidateCustodian,
                    cr.score = row.score,
                    cr.matchType = row.matchType,
                    cr.status = row.status,
                    __REVIEW_SOURCE_SET__
                WITH row, cr
                MATCH (c:Custodian {id: row.sourceId})
                MERGE (c)-[hcr:HAS_CONNECTION_REVIEW]->(cr)
                SET __HCR_SOURCE_SET__
                WITH row, cr
                OPTIONAL MATCH (t:Custodian {id: row.targetId})
                FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
                    MERGE (cr)-[r:REVIEW_SUGGESTS]->(t)
                    SET r.score = row.score,
                        __REL_SOURCE_SET__
                )
                """
                .replace("__REVIEW_SOURCE_SET__", source_set_clause("cr"))
                .replace("__HCR_SOURCE_SET__", source_set_clause("hcr"))
                .replace("__REL_SOURCE_SET__", source_set_clause("r", indent=24)),
                {"rows": connections_review},
            )

            counts = await run_cypher_read(
                session,
                """
                CALL () { MATCH (c:Custodian) RETURN count(c) AS custodians }
                CALL () { MATCH (d:Dataset) RETURN count(d) AS datasets }
                CALL () { MATCH (p:PathwayStep) RETURN count(p) AS pathwaySteps }
                CALL () { MATCH (l:ProcessLine) RETURN count(l) AS processLines }
                CALL () { MATCH (u:SourceURL) RETURN count(u) AS sourceUrls }
                CALL () { MATCH ()-[r:CONNECTED_TO]->() RETURN count(r) AS connectedTo }
                CALL () { MATCH (cr:ConnectionReview) RETURN count(cr) AS connectionReviews }
                RETURN
                  custodians,
                  datasets,
                  pathwaySteps,
                  processLines,
                  sourceUrls,
                  connectedTo,
                  connectionReviews
                """,
            )

    return {
        "loaded_counts": counts[0] if counts else {},
        "input_counts": {
            "custodians": len(custodian_nodes),
            "datasets": len(dataset_nodes),
            "pathway_steps": len(pathway_steps),
            "accepted_connections": len(connections_accepted),
            "review_connections": len(connections_review),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load the AU health data knowledge graph into Neo4j Aura via MCP servers")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full local pipeline and write QA artefacts (suffixed _dryrun) without spawning MCP servers, reading credentials, or touching the database",
    )
    parser.add_argument(
        "--cred-path",
        default=None,
        help=f"Neo4j credential file path. Defaults to {DEFAULT_CRED_PATH.name} or NEO4J_CREDENTIAL_FILE.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip the pre-wipe backup export of the live graph (e.g. first-ever load into an empty instance)",
    )
    return parser.parse_args()


def build_local_data() -> dict[str, Any]:
    """Parse local sources and build everything a load needs. No credentials, MCP, or network access."""
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

    # Map markdown card titles to CSV custodians.
    title_to_custodian_id: dict[str, str] = {}
    for title, _ in cards:
        best_id = None
        best_score = 0.0
        for c in custodians:
            subject_short = extract_subject_short(c.row.get("Subject") or "")
            score = max(similarity(title, c.name), similarity(title, subject_short))
            if score > best_score:
                best_score = score
                best_id = c.custodian_id
        if best_id and best_score >= 0.55:
            title_to_custodian_id[title] = best_id

    md_cards_by_custodian_id: dict[str, str] = {}
    md_datasets_by_custodian_id: dict[str, list[dict[str, str]]] = {}
    for title, card_body in cards:
        custodian_id = title_to_custodian_id.get(title)
        if not custodian_id:
            continue
        if custodian_id not in md_cards_by_custodian_id:
            md_cards_by_custodian_id[custodian_id] = card_body
        md_datasets_by_custodian_id[custodian_id] = parse_md_dataset_rows(card_body)

    datasets_by_custodian_id: dict[str, list[dict[str, str]]] = {}
    aliases_by_id: dict[str, set[str]] = {}
    for c in custodians:
        csv_sets = parse_csv_datasets(c.row.get("Key Datasets") or "")
        md_sets = md_datasets_by_custodian_id.get(c.custodian_id, [])
        datasets_by_custodian_id[c.custodian_id] = ensure_dataset_coverage(c, md_sets + csv_sets)

        title = ""
        for t, cid in title_to_custodian_id.items():
            if cid == c.custodian_id:
                title = t
                break
        aliases_by_id[c.custodian_id] = extract_aliases(c.name, c.row.get("Subject") or "", title)

    accepted_connections, review_connections, gap_custodians = build_connection_matches(custodians, aliases_by_id, overrides)

    return {
        "custodians": custodians,
        "overrides": overrides,
        "source_metadata": source_metadata,
        "md_cards_by_custodian_id": md_cards_by_custodian_id,
        "datasets_by_custodian_id": datasets_by_custodian_id,
        "accepted_connections": accepted_connections,
        "review_connections": review_connections,
        "gap_custodians": gap_custodians,
    }


def local_input_counts(local: dict[str, Any]) -> dict[str, int]:
    dataset_ids: set[str] = set()
    pathway_step_count = 0
    for c in local["custodians"]:
        pathway_step_count += len(parse_pathway_steps(c.row.get("Access Pathway Steps") or ""))
        for ds in local["datasets_by_custodian_id"].get(c.custodian_id, []):
            ds_name = ds["name"].strip()
            if ds_name:
                dataset_ids.add(f"dataset:{slugify(ds_name)}")
    return {
        "custodians": len(local["custodians"]),
        "datasets": len(dataset_ids),
        "pathway_steps": pathway_step_count,
        "accepted_connections": len(local["accepted_connections"]),
        "review_connections": len(local["review_connections"]),
    }


def write_review_csv(path: Path, review_connections: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "id",
            "sourceId",
            "sourceName",
            "rawText",
            "segment",
            "candidateCustodian",
            "targetId",
            "score",
            "matchType",
            "status",
            *SOURCE_METADATA_FIELDS,
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_connections)


def run_dry_run(local: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_review_csv(DRYRUN_REVIEW_CSV, local["review_connections"])
    DRYRUN_GAP_JSON.write_text(json.dumps(local["gap_custodians"], indent=2), encoding="utf-8")

    counts = local_input_counts(local)
    summary = {
        "dryRun": True,
        "input_counts": counts,
        "matching": {
            "override_rule_count": len(local["overrides"]),
            "gap_custodian_count": len(local["gap_custodians"]),
        },
        "source": local["source_metadata"],
        "artifacts": {
            "review_csv": str(DRYRUN_REVIEW_CSV),
            "override_csv": str(OVERRIDE_PATH),
            "gap_json": str(DRYRUN_GAP_JSON),
            "summary_json": str(DRYRUN_SUMMARY_JSON),
        },
    }
    DRYRUN_SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(
        "Dry run complete (no MCP servers spawned, no credentials read, no database contact): "
        f"{counts['custodians']} custodians, {counts['datasets']} datasets, "
        f"{counts['pathway_steps']} pathway steps, {counts['accepted_connections']} accepted connections, "
        f"{counts['review_connections']} review items."
    )


def backup_live_graph(cred_path: Path) -> dict[str, Any]:
    backup_dir = BACKUP_ROOT / ("prewipe_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    print(f"Backing up live graph to {backup_dir} before wipe...")
    try:
        manifest = export_from_neo4j(export_dir=backup_dir, cred_path=cred_path)
    except (OSError, ValueError, Neo4jExportError) as exc:
        raise SystemExit(
            "Pre-wipe backup failed; aborting before any database writes.\n"
            f"  Reason: {exc}\n"
            "  Pass --skip-backup to proceed without a backup (e.g. first-ever load into an empty instance)."
        ) from exc
    backup_summary = manifest.get("summary", {})
    node_count = backup_summary.get("nodeCount", 0)
    relationship_count = backup_summary.get("relationshipCount", 0)
    if node_count == 0:
        print("Backup complete: live graph is empty (0 nodes exported).")
    else:
        print(f"Backup complete: {node_count} nodes, {relationship_count} relationships exported.")
    return {
        "status": "completed",
        "path": str(backup_dir),
        "nodeCount": node_count,
        "relationshipCount": relationship_count,
    }


async def main() -> None:
    args = parse_args()

    # Local phase: parse sources and build all rows/matches. Safe to run offline.
    local = build_local_data()

    if args.dry_run:
        run_dry_run(local)
        return

    # Network phase: backup, validate MCP servers, then wipe-and-reload.
    cred_path = resolve_credential_path(args.cred_path)
    creds = parse_credentials(cred_path)

    if args.skip_backup:
        backup_info = {"status": "skipped", "reason": "--skip-backup flag set"}
        print("Skipping pre-wipe backup (--skip-backup).")
    else:
        backup_info = backup_live_graph(cred_path)

    validation = await validate_servers(creds)
    load_summary = await load_graph(
        creds=creds,
        custodians=local["custodians"],
        md_cards_by_custodian_id=local["md_cards_by_custodian_id"],
        datasets_by_custodian_id=local["datasets_by_custodian_id"],
        connections_accepted=local["accepted_connections"],
        connections_review=local["review_connections"],
        source_metadata=local["source_metadata"],
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_review_csv(REVIEW_CSV, local["review_connections"])

    GAP_JSON.write_text(json.dumps(local["gap_custodians"], indent=2), encoding="utf-8")

    summary = {
        "validation": validation,
        "backup": backup_info,
        "load": load_summary,
        "matching": {
            "override_rule_count": len(local["overrides"]),
            "gap_custodian_count": len(local["gap_custodians"]),
        },
        "source": local["source_metadata"],
        "artifacts": {
            "review_csv": str(REVIEW_CSV),
            "override_csv": str(OVERRIDE_PATH),
            "gap_json": str(GAP_JSON),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
