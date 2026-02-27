import asyncio
import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "raw_data" / "pathway_cards.csv"
MD_PATH = ROOT / "raw_data" / "AU_Health_Data_Pathway_Register.md"
CRED_PATH = ROOT / "Neo4j-e0662ca0-Created-2026-02-27.txt"
OVERRIDE_PATH = ROOT / "config" / "connection_alias_overrides.csv"
OUT_DIR = ROOT / "output"
REVIEW_CSV = OUT_DIR / "connection_match_review.csv"
SUMMARY_JSON = OUT_DIR / "kg_load_summary.json"


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


@dataclass
class CustodianRow:
    custodian_id: str
    name: str
    row: dict[str, str]


@dataclass
class ConnectionOverrideRule:
    source_custodian_id: str
    pattern: str
    pattern_norm: str
    action: str
    target_custodian_id: str
    notes: str


def normalize_text(value: str) -> str:
    value = value or ""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str) -> str:
    s = normalize_text(value)
    return re.sub(r"\s+", "-", s).strip("-")


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def parse_credentials(path: Path) -> dict[str, str]:
    creds: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r"^(NEO4J_[A-Z_]+)=(.+)$", line.strip())
        if m:
            creds[m.group(1)] = m.group(2)
    required = ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"]
    missing = [k for k in required if k not in creds]
    if missing:
        raise ValueError(f"Missing credentials: {missing}")
    return creds


def read_csv_rows(path: Path) -> list[CustodianRow]:
    out: list[CustodianRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Custodian Name") or "").strip()
            if not name:
                continue
            custodian_id = f"custodian:{slugify(name)}"
            out.append(CustodianRow(custodian_id=custodian_id, name=name, row=row))
    return out


def extract_subject_short(subject: str) -> str:
    if not subject:
        return ""
    return subject.split("(")[0].strip()


def split_delimited(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[/,;]\s*", text)
    return [p.strip() for p in parts if p.strip()]


def parse_urls(text: str) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"https?://[^\s)]+", text)))


def parse_pathway_steps(step_text: str) -> list[dict[str, Any]]:
    if not step_text:
        return []
    steps: list[dict[str, Any]] = []
    for line in step_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if not m:
            continue
        num = int(m.group(1))
        body = m.group(2).strip()
        parts = re.split(r"\s+[—-]\s+", body)
        text = body
        actor = ""
        channel = ""
        timeline = ""
        if len(parts) >= 4:
            text = parts[0].strip()
            actor = parts[1].strip()
            channel = parts[2].strip()
            timeline = " - ".join(p.strip() for p in parts[3:])
        elif len(parts) == 3:
            text = parts[0].strip()
            actor = parts[1].strip()
            channel = parts[2].strip()
        elif len(parts) == 2:
            text = parts[0].strip()
            actor = parts[1].strip()

        lane_basis = f"{text} {actor}".lower()
        lane = "Custodian"
        if any(k in lane_basis for k in ["researcher", "applicant"]):
            lane = "Researcher"
        elif any(k in lane_basis for k in ["hrec", "ethic", "committee", "governance", "approval"]):
            lane = "EthicsRegulatory"

        steps.append(
            {
                "number": num,
                "text": text,
                "actor": actor,
                "channel": channel,
                "timeline": timeline,
                "lane": lane,
            }
        )
    return steps


def parse_csv_datasets(key_datasets: str) -> list[dict[str, str]]:
    if not key_datasets:
        return []
    cleaned = key_datasets.replace("\n", " ").strip()
    if ")," in cleaned:
        chunks = cleaned.split("),")
        entries: list[str] = []
        for idx, chunk in enumerate(chunks):
            chunk = chunk.strip()
            if not chunk:
                continue
            if idx < len(chunks) - 1:
                chunk = chunk + ")"
            entries.append(chunk)
    else:
        entries = [c.strip() for c in re.split(r",\s+(?=[A-Z0-9(])", cleaned) if c.strip()]

    out: list[dict[str, str]] = []
    for entry in entries:
        m = re.match(r"^(.*?)\s*\((.*)\)\s*$", entry)
        if m:
            name = m.group(1).strip()
            desc = m.group(2).strip()
        else:
            name = entry.strip()
            desc = ""
        if not name:
            continue
        out.append({"name": name, "description": desc, "identifiable": "", "linkable": "", "source": "csv"})
    return out


def extract_md_cards(md_text: str) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = []
    matches = list(re.finditer(r"^## Pathway Card:\s*(.+)$", md_text, flags=re.MULTILINE))
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        cards.append((title, md_text[start:end].strip()))
    return cards


def parse_md_dataset_rows(card_text: str) -> list[dict[str, str]]:
    lines = card_text.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\|\s*Dataset Name\s*\|\s*Description\s*\|", line.strip()):
            idx = i + 2
            break
    if idx is None:
        return []

    out: list[dict[str, str]] = []
    i = idx
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("|"):
            break
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) >= 4 and cols[0] and "---" not in cols[0]:
            out.append(
                {
                    "name": cols[0],
                    "description": cols[1],
                    "identifiable": cols[2],
                    "linkable": cols[3],
                    "source": "md",
                }
            )
        i += 1
    return out


def extract_aliases(name: str, subject: str, title: str) -> set[str]:
    aliases = {name.strip()}
    subject_short = extract_subject_short(subject)
    if subject_short:
        aliases.add(subject_short)
    if title:
        aliases.add(title)
    for source in [name, subject, title]:
        if not source:
            continue
        for token in re.findall(r"\(([A-Za-z0-9/&\-\s]+)\)", source):
            token = token.strip()
            if 2 <= len(token) <= 40:
                aliases.add(token)
        for token in re.findall(r"\b[A-Z]{2,10}\b", source):
            aliases.add(token)
    return {a for a in aliases if a}


def load_connection_overrides(path: Path) -> list[ConnectionOverrideRule]:
    if not path.exists():
        return []

    rules: list[ConnectionOverrideRule] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = (row.get("action") or "").strip().lower()
            if action not in {"force_accept", "force_reject", "review_only"}:
                continue
            pattern = (row.get("pattern") or "").strip()
            pattern_norm = normalize_text(pattern)
            if not pattern_norm:
                continue
            rules.append(
                ConnectionOverrideRule(
                    source_custodian_id=(row.get("source_custodian_id") or "").strip(),
                    pattern=pattern,
                    pattern_norm=pattern_norm,
                    action=action,
                    target_custodian_id=(row.get("target_custodian_id") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return rules


def build_connection_matches(
    custodians: list[CustodianRow],
    id_to_aliases: dict[str, set[str]],
    overrides: list[ConnectionOverrideRule],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    id_to_name = {c.custodian_id: c.name for c in custodians}
    accepted: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for c in custodians:
        raw = (c.row.get("Connections to Other Custodians") or "").strip()
        if not raw:
            continue

        segments = [s.strip(" .") for s in re.split(r";|\n", raw) if s.strip(" .")]
        if not segments:
            segments = [raw]

        for idx, seg in enumerate(segments, start=1):
            seg_norm = normalize_text(seg)
            matched_rules = [
                r
                for r in overrides
                if (not r.source_custodian_id or r.source_custodian_id == c.custodian_id) and r.pattern_norm in seg_norm
            ]

            if matched_rules:
                reject_rules = [r for r in matched_rules if r.action == "force_reject"]
                if reject_rules:
                    rule = reject_rules[0]
                    review_id = f"review:{c.custodian_id}:{idx}:{slugify(seg)[:40]}:override-reject"
                    review.append(
                        {
                            "id": review_id,
                            "sourceId": c.custodian_id,
                            "sourceName": c.name,
                            "rawText": raw,
                            "segment": seg,
                            "candidateCustodian": "",
                            "targetId": "",
                            "score": 0.0,
                            "matchType": "override_force_reject",
                            "status": "review_required",
                        }
                    )
                    continue

                handled = False
                for r_idx, rule in enumerate([r for r in matched_rules if r.action in {"force_accept", "review_only"}], start=1):
                    target_id = rule.target_custodian_id
                    candidate_name = id_to_name.get(target_id, "")
                    if rule.action == "force_accept" and target_id:
                        accepted.append(
                            {
                                "sourceId": c.custodian_id,
                                "targetId": target_id,
                                "rawText": raw,
                                "segment": seg,
                                "score": 1.0,
                                "matchType": "override_force_accept",
                            }
                        )
                        status = "accepted"
                        score = 1.0
                        match_type = "override_force_accept"
                        handled = True
                    else:
                        status = "review_required"
                        score = 0.0
                        match_type = "override_review_only"
                        handled = True

                    review_id = f"review:{c.custodian_id}:{idx}:{r_idx}:{slugify(seg)[:30]}:override"
                    review.append(
                        {
                            "id": review_id,
                            "sourceId": c.custodian_id,
                            "sourceName": c.name,
                            "rawText": raw,
                            "segment": seg,
                            "candidateCustodian": candidate_name,
                            "targetId": target_id,
                            "score": score,
                            "matchType": match_type,
                            "status": status,
                        }
                    )

                if handled:
                    continue

            best = None
            second_score = 0.0

            for target in custodians:
                if target.custodian_id == c.custodian_id:
                    continue
                aliases = id_to_aliases[target.custodian_id]

                full_name_norm = normalize_text(target.name)
                full_name_hit = bool(full_name_norm and f" {full_name_norm} " in f" {seg_norm} ")
                alias_hit = None
                alias_hit_len = 0
                for alias in aliases:
                    alias_norm = normalize_text(alias)
                    if len(alias_norm) < 3:
                        continue
                    if f" {alias_norm} " in f" {seg_norm} ":
                        if len(alias_norm) > alias_hit_len:
                            alias_hit = alias
                            alias_hit_len = len(alias_norm)

                if full_name_hit:
                    score = 1.0
                    match_type = "name_exact"
                elif alias_hit is not None:
                    # Short acronym-only hits are weaker and should generally require review.
                    if alias_hit_len < 5:
                        score = 0.86
                        match_type = "alias_short"
                    else:
                        score = 0.96
                        match_type = "alias_exact"
                else:
                    ratio_name = similarity(seg, target.name)
                    ratio_alias = max((similarity(seg, a) for a in aliases), default=0.0)
                    score = max(ratio_name, ratio_alias)
                    match_type = "fuzzy"

                if best is None or score > best["score"]:
                    if best is not None:
                        second_score = best["score"]
                    best = {
                        "target_id": target.custodian_id,
                        "target_name": target.name,
                        "score": score,
                        "match_type": match_type,
                    }
                elif score > second_score:
                    second_score = score

            if best is None:
                continue

            ambiguous = second_score >= 0.8 and (best["score"] - second_score) < 0.03
            has_verify_placeholder = "verify with custodian" in seg_norm
            accepted_flag = (
                (best["match_type"] in {"name_exact", "alias_exact"} and not ambiguous and not has_verify_placeholder)
                or (best["score"] >= 0.9 and not ambiguous and not has_verify_placeholder)
            )
            status = "accepted" if accepted_flag else "review_required"

            review_id = f"review:{c.custodian_id}:{idx}:{slugify(seg)[:40]}"
            review.append(
                {
                    "id": review_id,
                    "sourceId": c.custodian_id,
                    "sourceName": c.name,
                    "rawText": raw,
                    "segment": seg,
                    "candidateCustodian": best["target_name"],
                    "targetId": best["target_id"],
                    "score": round(float(best["score"]), 4),
                    "matchType": best["match_type"],
                    "status": status,
                }
            )

            if accepted_flag:
                accepted.append(
                    {
                        "sourceId": c.custodian_id,
                        "targetId": best["target_id"],
                        "rawText": raw,
                        "segment": seg,
                        "score": round(float(best["score"]), 4),
                        "matchType": best["match_type"],
                    }
                )

    # Deduplicate accepted edges by source-target pair, keep highest score
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in accepted:
        key = (edge["sourceId"], edge["targetId"])
        if key not in dedup or edge["score"] > dedup[key]["score"]:
            dedup[key] = edge
    return list(dedup.values()), review


def call_tool_text(result: Any) -> str:
    # CallToolResult content is list[TextContent]
    if not getattr(result, "content", None):
        return ""
    first = result.content[0]
    return getattr(first, "text", "")


async def validate_servers(creds: dict[str, str]) -> dict[str, Any]:
    data_modeling = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"],
    )
    cypher = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-cypher@0.5.3", "--transport", "stdio"],
        env={**os.environ, **creds},
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
) -> dict[str, Any]:
    cypher = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-cypher@0.5.3", "--transport", "stdio"],
        env={**os.environ, **creds},
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

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
        md_card = md_cards_by_custodian_id.get(c.custodian_id, "")

        custodian_nodes.append(
            {
                "id": c.custodian_id,
                "props": {
                    "name": c.name,
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
            }
        )

        for t in split_delimited(row.get("Custodian Type") or ""):
            custodian_types.append({"custodianId": c.custodian_id, "type": t})

        for j in split_delimited(row.get("Jurisdiction") or ""):
            jurisdictions.append({"custodianId": c.custodian_id, "jurisdiction": j})

        process_lines.append({"lineId": line_id, "name": c.name, "custodianId": c.custodian_id})

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
                }
            )

        urls = parse_urls(row.get("Source URLs") or "")
        for url in urls:
            source_urls.append({"url": url})
            cust_source_urls.append({"custodianId": c.custodian_id, "url": url})

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
                }
            )

    dataset_nodes = list(dataset_nodes_map.values())
    source_urls = list({u["url"]: u for u in source_urls}.values())

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
                WITH row, t
                MATCH (c:Custodian {id: row.custodianId})
                MERGE (c)-[:HAS_TYPE]->(t)
                """,
                {"rows": custodian_types},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (j:Jurisdiction {name: row.jurisdiction})
                WITH row, j
                MATCH (c:Custodian {id: row.custodianId})
                MERGE (c)-[:IN_JURISDICTION]->(j)
                """,
                {"rows": jurisdictions},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (l:ProcessLine {id: row.lineId})
                SET l.name = row.name
                WITH row, l
                MATCH (c:Custodian {id: row.custodianId})
                MERGE (c)-[:OFFERS_LINE]->(l)
                """,
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
                    s.lane = row.lane
                WITH row, s
                MATCH (l:ProcessLine {id: row.lineId})
                MERGE (l)-[r:HAS_STEP]->(s)
                SET r.order = row.stepNumber, r.lane = row.lane
                """,
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
                    d.linkable = row.linkable
                """,
                {"rows": dataset_nodes},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MATCH (c:Custodian {id: row.custodianId})
                MATCH (d:Dataset {id: row.datasetId})
                MERGE (c)-[r:HAS_DATASET]->(d)
                SET r.source = row.source
                """,
                {"rows": cust_dataset_rels},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MERGE (s:SourceURL {url: row.url})
                """,
                {"rows": source_urls},
            )

            await run_cypher_write(
                session,
                """
                UNWIND $rows AS row
                MATCH (c:Custodian {id: row.custodianId})
                MATCH (s:SourceURL {url: row.url})
                MERGE (c)-[:HAS_SOURCE]->(s)
                """,
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
                    r.matchType = row.matchType
                """,
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
                    cr.status = row.status
                WITH row, cr
                MATCH (c:Custodian {id: row.sourceId})
                MERGE (c)-[:HAS_CONNECTION_REVIEW]->(cr)
                WITH row, cr
                OPTIONAL MATCH (t:Custodian {id: row.targetId})
                FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END |
                    MERGE (cr)-[r:REVIEW_SUGGESTS]->(t)
                    SET r.score = row.score
                )
                """,
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


async def main() -> None:
    creds = parse_credentials(CRED_PATH)
    custodians = read_csv_rows(CSV_PATH)
    overrides = load_connection_overrides(OVERRIDE_PATH)
    md_text = MD_PATH.read_text(encoding="utf-8")
    cards = extract_md_cards(md_text)

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
        md_cards_by_custodian_id[custodian_id] = card_body
        md_datasets_by_custodian_id[custodian_id] = parse_md_dataset_rows(card_body)

    datasets_by_custodian_id: dict[str, list[dict[str, str]]] = {}
    aliases_by_id: dict[str, set[str]] = {}
    for c in custodians:
        csv_sets = parse_csv_datasets(c.row.get("Key Datasets") or "")
        md_sets = md_datasets_by_custodian_id.get(c.custodian_id, [])
        datasets_by_custodian_id[c.custodian_id] = md_sets + csv_sets

        title = ""
        for t, cid in title_to_custodian_id.items():
            if cid == c.custodian_id:
                title = t
                break
        aliases_by_id[c.custodian_id] = extract_aliases(c.name, c.row.get("Subject") or "", title)

    accepted_connections, review_connections = build_connection_matches(custodians, aliases_by_id, overrides)

    validation = await validate_servers(creds)
    load_summary = await load_graph(
        creds=creds,
        custodians=custodians,
        md_cards_by_custodian_id=md_cards_by_custodian_id,
        datasets_by_custodian_id=datasets_by_custodian_id,
        connections_accepted=accepted_connections,
        connections_review=review_connections,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_CSV.open("w", encoding="utf-8", newline="") as f:
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
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_connections)

    summary = {
        "validation": validation,
        "load": load_summary,
        "matching": {
            "override_rule_count": len(overrides),
        },
        "artifacts": {
            "review_csv": str(REVIEW_CSV),
            "override_csv": str(OVERRIDE_PATH),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
