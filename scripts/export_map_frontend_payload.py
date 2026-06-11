import json
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase

from neo4j_credentials import parse_credentials

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "frontend"
OUT_FILE = OUT_DIR / "map_bundle.json"


def run_query(session, query: str, params: dict | None = None) -> list[dict]:
    result = session.run(query, params or {})
    return [r.data() for r in result]


def main() -> None:
    creds = parse_credentials()

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
              count(s) AS stepCount,
              l.sourceRegisterGenerated AS sourceRegisterGenerated,
              l.sourceProvenanceStatus AS sourceProvenanceStatus,
              l.kgLoadedAt AS kgLoadedAt
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
              r.matchScore AS matchScore,
              r.sourceRegisterGenerated AS sourceRegisterGenerated,
              r.sourceProvenanceStatus AS sourceProvenanceStatus
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
                  s.timeline AS timeline,
                  coalesce(s.sourceRegisterGenerated, hs.sourceRegisterGenerated) AS sourceRegisterGenerated,
                  coalesce(s.sourceProvenanceStatus, hs.sourceProvenanceStatus) AS sourceProvenanceStatus,
                  coalesce(s.kgLoadedAt, hs.kgLoadedAt) AS kgLoadedAt
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
                  c.sourceRegisterTitle AS sourceRegisterTitle,
                  c.sourceRegisterVersion AS sourceRegisterVersion,
                  c.sourceRegisterGenerated AS sourceRegisterGenerated,
                  c.sourceRegisterCustodianCount AS sourceRegisterCustodianCount,
                  c.sourceCsvPath AS sourceCsvPath,
                  c.sourceMarkdownPath AS sourceMarkdownPath,
                  c.sourceCsvModifiedAt AS sourceCsvModifiedAt,
                  c.sourceMarkdownModifiedAt AS sourceMarkdownModifiedAt,
                  c.sourceCsvSha256 AS sourceCsvSha256,
                  c.sourceMarkdownSha256 AS sourceMarkdownSha256,
                  c.sourceCustodianRowCount AS sourceCustodianRowCount,
                  c.sourceMarkdownCardCount AS sourceMarkdownCardCount,
                  c.sourceOverrideRuleCount AS sourceOverrideRuleCount,
                  c.sourceGitCommit AS sourceGitCommit,
                  c.sourceProvenanceStatus AS sourceProvenanceStatus,
                  c.kgLoadedAt AS kgLoadedAt,
                  collect(DISTINCT u.url) AS sourceUrls
                """,
                {"lineId": line_id},
            )
            details = details_rows[0] if details_rows else {}

            datasets = run_query(
                session,
                """
                MATCH (l:ProcessLine {id: $lineId})<-[:OFFERS_LINE]-(c:Custodian)-[hd:HAS_DATASET]->(d:Dataset)
                RETURN
                  d.id AS datasetId,
                  d.name AS datasetName,
                  d.description AS datasetDescription,
                  d.identifiable AS identifiable,
                  d.linkable AS linkable,
                  hd.source AS dataSource,
                  coalesce(hd.sourceRegisterTitle, d.sourceRegisterTitle) AS sourceRegisterTitle,
                  coalesce(hd.sourceRegisterVersion, d.sourceRegisterVersion) AS sourceRegisterVersion,
                  coalesce(hd.sourceRegisterGenerated, d.sourceRegisterGenerated) AS sourceRegisterGenerated,
                  coalesce(hd.sourceCsvPath, d.sourceCsvPath) AS sourceCsvPath,
                  coalesce(hd.sourceMarkdownPath, d.sourceMarkdownPath) AS sourceMarkdownPath,
                  coalesce(hd.sourceCsvModifiedAt, d.sourceCsvModifiedAt) AS sourceCsvModifiedAt,
                  coalesce(hd.sourceMarkdownModifiedAt, d.sourceMarkdownModifiedAt) AS sourceMarkdownModifiedAt,
                  coalesce(hd.sourceCsvSha256, d.sourceCsvSha256) AS sourceCsvSha256,
                  coalesce(hd.sourceMarkdownSha256, d.sourceMarkdownSha256) AS sourceMarkdownSha256,
                  coalesce(hd.sourceCustodianRowCount, d.sourceCustodianRowCount) AS sourceCustodianRowCount,
                  coalesce(hd.sourceMarkdownCardCount, d.sourceMarkdownCardCount) AS sourceMarkdownCardCount,
                  coalesce(hd.sourceOverrideRuleCount, d.sourceOverrideRuleCount) AS sourceOverrideRuleCount,
                  coalesce(hd.sourceGitCommit, d.sourceGitCommit) AS sourceGitCommit,
                  coalesce(hd.sourceProvenanceStatus, d.sourceProvenanceStatus) AS sourceProvenanceStatus,
                  coalesce(hd.kgLoadedAt, d.kgLoadedAt) AS kgLoadedAt
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
                    "sourceRegisterGenerated": line.get("sourceRegisterGenerated"),
                    "sourceProvenanceStatus": line.get("sourceProvenanceStatus"),
                    "kgLoadedAt": line.get("kgLoadedAt"),
                    "steps": steps,
                    "chainEdges": chain_edges,
                    "details": details,
                    "datasets": datasets,
                }
            )

        source_keys = [
            "sourceRegisterTitle",
            "sourceRegisterVersion",
            "sourceRegisterGenerated",
            "sourceRegisterCustodianCount",
            "sourceCsvPath",
            "sourceMarkdownPath",
            "sourceCsvModifiedAt",
            "sourceMarkdownModifiedAt",
            "sourceCsvSha256",
            "sourceMarkdownSha256",
            "sourceCustodianRowCount",
            "sourceMarkdownCardCount",
            "sourceOverrideRuleCount",
            "sourceGitCommit",
            "sourceProvenanceStatus",
            "kgLoadedAt",
        ]
        source = {}
        for line_payload in line_payloads:
            details = line_payload.get("details") or {}
            source = {key: details.get(key) for key in source_keys if details.get(key)}
            if source:
                break

        payload = {
            "schemaVersion": "2026-06-source-provenance-v1",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "source": source,
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
