# AU Health Data Map: Raw Data to Knowledge Graph to Platform

This repository converts curated custodian pathway content into a Neo4j knowledge graph, then publishes map-ready data for platform consumption.

The process has two delivery layers:

1. Knowledge graph load into Neo4j Aura (`scripts/load_au_health_kg_via_mcp.py`)
2. Frontend payload/API publication (`scripts/export_map_frontend_payload.py`, `scripts/serve_map_api.py`) when those files are present

## 1) Inputs and folder layout

- `raw_data/pathway_cards.csv`
  - Primary structured source for each custodian card.
- `raw_data/AU_Health_Data_Pathway_Register.md`
  - Long-form source; used to extract per-custodian card markdown and detailed dataset tables.
- `config/connection_alias_overrides.csv`
  - Rule file to force accept/reject/review specific custodian connection matches.
- `Neo4j-e0662ca0-Created-2026-02-27.txt`
  - Neo4j connection settings parsed by scripts.
- `output/`
  - Generated QA and load artifacts.

## 2) Prerequisites

- Python 3.10+ (3.11 recommended)
- `uv` / `uvx` installed and available in `PATH`
- Network access to the target Neo4j Aura instance
- Python packages:
  - `mcp` (for MCP client calls)
  - `neo4j` (required by frontend payload exporter script)

Example install:

```powershell
python -m pip install mcp neo4j
```

## 3) Configure the platform target (Neo4j Aura)

`scripts/load_au_health_kg_via_mcp.py` reads only these keys from `Neo4j-e0662ca0-Created-2026-02-27.txt`:

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE`

Important:

- Keep this file out of public repos for production use.
- Rotate credentials if they were exposed.
- Script path is hardcoded; if the file name/path changes, update `CRED_PATH` in the script.

## 4) Run the raw-data to graph pipeline

From repo root:

```powershell
python .\scripts\load_au_health_kg_via_mcp.py
```

What this run does, in order:

1. Reads credentials and validates required keys.
2. Reads custodian rows from `raw_data/pathway_cards.csv`.
3. Loads connection override rules from `config/connection_alias_overrides.csv`.
4. Parses markdown cards from `raw_data/AU_Health_Data_Pathway_Register.md`.
5. Maps markdown card titles to CSV custodians using fuzzy similarity.
6. Builds unified dataset lists per custodian:
   - Table-derived rows from markdown
   - Fallback list parsing from CSV `Key Datasets`
7. Builds aliases for connection matching:
   - Custodian name
   - Subject short name
   - Card title
   - Acronyms and parenthetical aliases
8. Parses pathway steps from `Access Pathway Steps`:
   - Extracts step number, step text, actor, channel, timeline
   - Assigns lane (`Researcher`, `EthicsRegulatory`, `Custodian`)
9. Parses and deduplicates source URLs.
10. Builds custodian-to-custodian connection matches:
   - Applies manual overrides first (`force_accept`, `force_reject`, `review_only`)
   - Uses exact/alias/fuzzy matching otherwise
   - Sends uncertain/ambiguous matches to review
11. Validates MCP servers:
   - `mcp-neo4j-data-modeling@0.8.2`
   - `mcp-neo4j-cypher@0.5.3`
12. Loads graph to Neo4j via MCP write tool.
13. Writes QA artifacts to `output/`.

## 5) Graph model created in Neo4j

Node labels:

- `Custodian`
- `CustodianType`
- `Jurisdiction`
- `Dataset`
- `ProcessLine`
- `PathwayStep`
- `SourceURL`
- `ConnectionReview`

Relationship types:

- `(:Custodian)-[:HAS_TYPE]->(:CustodianType)`
- `(:Custodian)-[:IN_JURISDICTION]->(:Jurisdiction)`
- `(:Custodian)-[:OFFERS_LINE]->(:ProcessLine)`
- `(:ProcessLine)-[:HAS_STEP {order, lane}]->(:PathwayStep)`
- `(:Custodian)-[:HAS_DATASET {source}]->(:Dataset)`
- `(:Custodian)-[:HAS_SOURCE]->(:SourceURL)`
- `(:Custodian)-[:CONNECTED_TO {segment, rawText, matchScore, matchType}]->(:Custodian)`
- `(:Custodian)-[:HAS_CONNECTION_REVIEW]->(:ConnectionReview)`
- `(:ConnectionReview)-[:REVIEW_SUGGESTS {score}]->(:Custodian)` (optional when target exists)

Load behavior:

- Full replace each run: `MATCH (n) DETACH DELETE n`
- Constraints recreated with `IF NOT EXISTS`

Operational implication: every run overwrites the database contents.

## 6) Connection matching and review workflow

Connection text is read from CSV column `Connections to Other Custodians` and split into segments.

Decision flow:

1. Override rules are applied first.
2. If no override applies, best match is selected from aliases and fuzzy score.
3. Edge accepted when confidence is high and non-ambiguous.
4. Otherwise item is written to review queue.

Accepted edges become `CONNECTED_TO`.
All evaluated candidates are logged as `ConnectionReview` nodes and exported to CSV for manual QA.

## 7) Output artifacts (QA and audit)

After a successful run:

- `output/kg_load_summary.json`
  - MCP validation status
  - Input counts and loaded graph counts
  - Artifact paths
- `output/connection_match_review.csv`
  - Review log with confidence, match type, and status

Latest sample summary in this repo shows:

- 32 custodians
- 180 datasets
- 180 pathway steps
- 36 accepted `CONNECTED_TO` edges
- 57 connection review records

## 8) Send data to the platform

### A) Neo4j platform (primary)

The loader script already sends data to the target Neo4j platform by writing directly through MCP (`write_neo4j_cypher`) using Aura credentials.

Verification options:

1. Open Neo4j Browser in Aura and run:

```cypher
MATCH (c:Custodian) RETURN count(c) AS custodians;
```

2. Compare counts with `output/kg_load_summary.json`.

### B) Frontend platform payload/API (map consumers)

This repo tracks the following map-delivery files:

- `scripts/export_map_frontend_payload.py`
- `scripts/serve_map_api.py`
- `queries/map_frontend_queries.cypher`

If they exist in your working tree, publish map payload as:

```powershell
python .\scripts\export_map_frontend_payload.py
python .\scripts\serve_map_api.py --host 127.0.0.1 --port 8787
```

Then consume endpoints:

- `/health`
- `/api/map`
- `/api/map/summary`
- `/api/map/lines`
- `/api/map/lines/{lineId}`
- `/api/map/lines/{lineId}/details`
- `/api/map/lines/{lineId}/datasets`

The exporter writes `output/frontend/map_bundle.json`, which is the platform bundle for downstream UI/API use.

If these files are currently deleted locally, restore before running:

```powershell
git checkout -- scripts/export_map_frontend_payload.py scripts/serve_map_api.py queries/map_frontend_queries.cypher
```

## 9) Re-run checklist

1. Update `raw_data/pathway_cards.csv` and/or `raw_data/AU_Health_Data_Pathway_Register.md`.
2. Update `config/connection_alias_overrides.csv` for new known matching edge cases.
3. Run loader script.
4. Review `output/connection_match_review.csv` and adjust overrides.
5. Re-run loader until review quality is acceptable.
6. Export/serve frontend payload (if frontend scripts are in use).

## 10) Troubleshooting

- `Missing credentials`:
  - Ensure all required `NEO4J_*` keys exist in the credential file.
- `uvx not found`:
  - Install `uv` and ensure it is in `PATH`.
- MCP validation fails:
  - Confirm network access and Aura credentials.
- Graph is empty after run:
  - Check script logs for failed writes after the initial wipe step.
- Frontend bundle missing:
  - Run `scripts/export_map_frontend_payload.py` and confirm `output/frontend/map_bundle.json` exists.
