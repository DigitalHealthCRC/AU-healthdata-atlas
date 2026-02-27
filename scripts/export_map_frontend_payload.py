import json
import re
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
CRED_PATH = ROOT / "Neo4j-e0662ca0-Created-2026-02-27.txt"
OUT_DIR = ROOT / "output" / "frontend"
OUT_FILE = OUT_DIR / "map_bundle.json"


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
        raise ValueError(f"Missing credentials in {path}: {missing}")
    return creds


def run_query(session, query: str, params: dict | None = None) -> list[dict]:
    result = session.run(query, params or {})
    return [r.data() for r in result]


def main() -> None:
    creds = parse_credentials(CRED_PATH)

    driver = GraphDatabase.driver(
        creds["NEO4J_URI"],
        auth=(creds["NEO4J_USERNAME"], creds["NEO4J_PASSWORD"]),
    )

    with driver.session(database=creds["NEO4J_DATABASE"]) as session:
        lines = run_query(
            session,
            """
            MATCH (c:Custodian)-[:OFFERS_LINE]->(l:ProcessLine)
            OPTIONAL MATCH (l)-[hs:HAS_STEP]->(s:PathwayStep)
            RETURN
              l.id AS lineId,
              l.name AS lineName,
              c.id AS custodianId,
              c.name AS custodianName,
              count(s) AS stepCount
            ORDER BY custodianName
            """,
        )

        lanes = run_query(
            session,
            """
            MATCH (:ProcessLine)-[hs:HAS_STEP]->(s:PathwayStep)
            WITH coalesce(s.lane, hs.lane, 'Custodian') AS lane
            RETURN
              lane,
              count(*) AS stepCount,
              CASE lane
                WHEN 'Researcher' THEN 1
                WHEN 'EthicsRegulatory' THEN 2
                WHEN 'Custodian' THEN 3
                ELSE 99
              END AS laneOrder
            ORDER BY laneOrder
            """,
        )

        branches = run_query(
            session,
            """
            MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
            MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)-[h1:HAS_STEP]->(s1:PathwayStep)
            MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)-[h2:HAS_STEP]->(s2:PathwayStep)
            WHERE h1.order = 1 AND h2.order = 1 AND l1.id <> l2.id
            RETURN
              s1.id AS fromStepId,
              s2.id AS toStepId,
              l1.id AS fromLineId,
              l2.id AS toLineId,
              r.segment AS reasonSegment,
              r.matchType AS matchType,
              r.matchScore AS matchScore
            ORDER BY coalesce(r.matchScore, 0.0) DESC
            """,
        )

        line_payloads: list[dict] = []
        for line in lines:
            line_id = line["lineId"]

            steps = run_query(
                session,
                """
                MATCH (l:ProcessLine {id: $lineId})-[hs:HAS_STEP]->(s:PathwayStep)
                RETURN
                  s.id AS id,
                  hs.order AS stepOrder,
                  coalesce(s.lane, hs.lane, 'Custodian') AS lane,
                  s.text AS title,
                  s.actor AS actor,
                  s.channel AS channel,
                  s.timeline AS timeline
                ORDER BY stepOrder, id
                """,
                {"lineId": line_id},
            )

            chain_edges = run_query(
                session,
                """
                MATCH (l:ProcessLine {id: $lineId})-[h1:HAS_STEP]->(s1:PathwayStep)
                MATCH (l)-[h2:HAS_STEP]->(s2:PathwayStep)
                WHERE h2.order = h1.order + 1
                RETURN
                  s1.id AS fromStepId,
                  s2.id AS toStepId,
                  h1.order AS fromOrder,
                  h2.order AS toOrder
                ORDER BY fromOrder, toOrder
                """,
                {"lineId": line_id},
            )

            details_rows = run_query(
                session,
                """
                MATCH (l:ProcessLine {id: $lineId})<-[:OFFERS_LINE]-(c:Custodian)
                OPTIONAL MATCH (c)-[:HAS_SOURCE]->(u:SourceURL)
                RETURN
                  c.id AS custodianId,
                  c.name AS custodianName,
                  c.primaryRole AS primaryRole,
                  c.ethicsAndGovernanceRequirements AS ethicsAndGovernanceRequirements,
                  c.treSecureAccessPlatform AS treSecureAccessPlatform,
                  c.contactAndApplicationPortal AS contactAndApplicationPortal,
                  c.indicativeTimeline AS indicativeTimeline,
                  c.gapsVerifyWithCustodian AS gapsVerifyWithCustodian,
                  collect(DISTINCT u.url) AS sourceUrls
                """,
                {"lineId": line_id},
            )
            details = details_rows[0] if details_rows else {}

            datasets = run_query(
                session,
                """
                MATCH (l:ProcessLine {id: $lineId})<-[:OFFERS_LINE]-(c:Custodian)-[:HAS_DATASET]->(d:Dataset)
                RETURN
                  d.id AS datasetId,
                  d.name AS datasetName,
                  d.description AS datasetDescription,
                  d.identifiable AS identifiable,
                  d.linkable AS linkable
                ORDER BY datasetName
                """,
                {"lineId": line_id},
            )

            line_payloads.append(
                {
                    "lineId": line_id,
                    "lineName": line["lineName"],
                    "stepCount": line["stepCount"],
                    "custodianId": line["custodianId"],
                    "custodianName": line["custodianName"],
                    "steps": steps,
                    "chainEdges": chain_edges,
                    "details": details,
                    "datasets": datasets,
                }
            )

        payload = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "lineCount": len(lines),
                "laneCount": len(lanes),
                "branchCount": len(branches),
            },
            "lanes": lanes,
            "branches": branches,
            "lines": line_payloads,
        }

    driver.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {OUT_FILE}")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
