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
- Local Neo4j credential file
  - Credential files are local secrets and are not tracked. Set `NEO4J_CREDENTIAL_FILE`, pass `--cred-path` where supported, or keep an ignored local credential file in the repo root.
- `output/`
  - Generated QA and load artefacts. Historical March 2026 generated outputs were moved to `archive/2026-06-11-repo-cleanup/`.

## 2) Prerequisites

- Python 3.10+ (3.11 recommended)
- `uv` / `uvx` installed and available in `PATH`
- Network access to the target Neo4j Aura instance

Install project dependencies into the project-local `.venv`:

```powershell
uv sync
```

Do not install project dependencies globally with `pip`.

## 3) Configure the platform target (Neo4j Aura)

The Neo4j scripts read only these keys from the resolved local credential file:

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE`

Credential path resolution:

1. `--cred-path` for scripts that expose the option, such as `scripts/export_kg_snapshot.py`.
2. `NEO4J_CREDENTIAL_FILE`.
3. The ignored repo-root default `Neo4j-credentials.txt`.
4. Existing ignored legacy local files matching `Neo4j-credentials-*.txt` or `Neo4j-*-Created-*.txt`.

Important:

- Keep this file out of public repos for production use.
- Rotate credentials if they were exposed.
- Credential files matching `Neo4j-credentials.txt`, `Neo4j-*-Created-*.txt`, and `Neo4j-credentials-*.txt` are ignored.

## 4) Run the raw-data to graph pipeline

From repo root:

```powershell
uv run python .\scripts\load_au_health_kg_via_mcp.py
```

Options:

```powershell
# Offline rehearsal: runs the full local parse/match pipeline and writes QA artefacts
# (suffixed _dryrun) without spawning MCP servers, reading credentials, or touching the database
uv run python .\scripts\load_au_health_kg_via_mcp.py --dry-run

# Explicit credential file (same convention as export_kg_snapshot.py)
uv run python .\scripts\load_au_health_kg_via_mcp.py --cred-path .\Neo4j-credentials.txt

# Skip the pre-wipe backup export (e.g. first-ever load into an empty instance)
uv run python .\scripts\load_au_health_kg_via_mcp.py --skip-backup
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
11. Exports a pre-wipe backup of the live graph to `output/kg_exports/prewipe_<UTC timestamp>/` (skip with `--skip-backup`; the load aborts before any database writes if the backup fails).
12. Validates MCP servers:
   - `mcp-neo4j-data-modeling@0.8.2`
   - `mcp-neo4j-cypher@0.5.3`
13. Loads graph to Neo4j via MCP write tool.
14. Writes QA artefacts to `output/`.

With `--dry-run`, the run stops after step 10: it writes `output/connection_match_review_dryrun.csv`, `output/gap_custodians_dryrun.json`, and `output/kg_load_summary_dryrun.json` (with `"dryRun": true`), prints input counts, and never contacts MCP servers or the database.

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

Load behaviour:

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

Intentional exclusions:

- References to collective groups or sectors such as `State and Territory Health Authorities`, `Primary Health Networks (PHNs)`, `ACCHOs`, and `Private Health Insurers` are not converted to `CONNECTED_TO` when there is no single target custodian node.
- References to partner organisations or external institutions not represented as custodian nodes, such as `RACGP`, `Reserve Bank of Australia`, `University of Queensland`, `Bureau of Health Information`, `Registry of Births Deaths and Marriages`, and `ICSPR`, are explicitly rejected in `config/connection_alias_overrides.csv`.
- These exclusions still appear in `output/connection_match_review.csv` after a live loader run for auditability, but they are expected rejects rather than unresolved matching failures.

## 7) Output artefacts (QA and audit)

After a successful live load run:

- `output/kg_load_summary.json`
  - MCP validation status
  - Input counts and loaded graph counts
  - Artefact paths
- `output/connection_match_review.csv`
  - Review log with confidence, match type, and status
- `output/source_audit/source_audit.csv`
  - Baseline refresh review queue generated from the current local source files.
- `output/source_audit/source_audit.json`
  - Machine-readable summary, dataset baseline, source evidence register, and manual review items.
- `output/source_audit/source_claims.jsonl`
  - Claim-level baseline records for custodian fields, datasets, pathway checks, and source URLs.

The archived March 2026 live-run summary in `archive/2026-06-11-repo-cleanup/output/kg_load_summary.json` recorded:

- 33 custodians
- 231 datasets
- 160 stored pathway steps (`163` parsed input steps before graph deduplication)
- 96 accepted `CONNECTED_TO` edges
- 107 connection review records

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
uv run python .\scripts\export_map_frontend_payload.py
uv run python .\scripts\serve_map_api.py --host 127.0.0.1 --port 8787
```

`serve_map_api.py` runs in the foreground; stop it with `Ctrl+C`.

Then consume endpoints:

- `/health`
- `/api/map`
- `/api/map/summary`
- `/api/map/lines`
- `/api/map/lines/{lineId}`
- `/api/map/lines/{lineId}/details`
- `/api/map/lines/{lineId}/datasets`

The exporter writes `output/frontend/map_bundle.json`, which is the platform bundle for downstream UI/API use.

Historical frontend and KG export snapshots are archived under `archive/2026-06-11-repo-cleanup/`; regenerate active copies when needed instead of treating the archived files as current data.

If these files are currently deleted locally, restore before running:

```powershell
git checkout -- scripts/export_map_frontend_payload.py scripts/serve_map_api.py queries/map_frontend_queries.cypher
```

### C) Atlas viewer (static, database-free)

`frontend/atlas/` is a self-contained interactive viewer (network map, metro-style pathway diagrams, dataset explorer) with zero external dependencies. It does not need Neo4j: the data bundle is reconstructed from the local curated sources.

Regenerate the data bundle (writes `frontend/atlas/data/atlas_data.json` and `atlas_data.js`):

```powershell
uv run python .\scripts\export_atlas_bundle.py
```

Options: `--kg-json <path>` to reuse an existing `output/kg_exports/<ts>/kg.json`, `--source-mode auto` to prefer live Neo4j with clean fallback to source reconstruction.

Open the viewer either way:

- Double-click `frontend\atlas\index.html` (works directly from `file://`), or
- `uv run python -m http.server 8788 --directory frontend\atlas` and browse to `http://127.0.0.1:8788/`.

## 9) Source audit and refresh workflow

Before a deep data refresh, generate the local baseline audit:

```powershell
uv run python .\scripts\build_source_audit.py --check
```

This writes:

- `output/source_audit/source_audit.csv`
- `output/source_audit/source_audit.json`
- `output/source_audit/source_claims.jsonl`

Use these files as the review queue for AI deep-search output. The audit identifies missing required fields, placeholder language, rows with no numbered access steps, parsed baseline datasets, current source URLs, and source domains. The JSONL file is claim-level so each field, dataset, and URL can be assessed against evidence separately. It does not contact external websites.

For a database-free snapshot of the graph that would be produced from local source files:

```powershell
uv run python .\scripts\export_kg_snapshot.py --source-mode source
```

Use `--source-mode auto` to prefer live Neo4j and fall back to source reconstruction:

```powershell
uv run python .\scripts\export_kg_snapshot.py --source-mode auto
```

## 10) Re-run checklist

1. Update `raw_data/pathway_cards.csv` and/or `raw_data/AU_Health_Data_Pathway_Register.md`.
2. Update `config/connection_alias_overrides.csv` for new known matching edge cases.
3. Run `uv run python .\scripts\build_source_audit.py --check`.
4. Run `uv run python .\scripts\export_kg_snapshot.py --source-mode source`.
5. Review `output/source_audit/source_audit.csv`, then adjust source data and overrides.
6. Run `uv run python .\scripts\load_au_health_kg_via_mcp.py` only after the review gate is acceptable.
7. Review `output/connection_match_review.csv` after the live load.
8. Export/serve frontend payload if frontend scripts are in use.

## 11) Provenance fields

Loader and snapshot exports attach baseline source metadata to core graph records:

- `sourceRegisterTitle`
- `sourceRegisterVersion`
- `sourceRegisterGenerated`
- `sourceRegisterCustodianCount`
- `sourceCsvPath`
- `sourceMarkdownPath`
- `sourceCsvModifiedAt`
- `sourceMarkdownModifiedAt`
- `sourceCsvSha256`
- `sourceMarkdownSha256`
- `sourceCustodianRowCount`
- `sourceMarkdownCardCount`
- `sourceOverrideRuleCount`
- `sourceGitCommit`
- `sourceProvenanceStatus`
- `kgLoadedAt`

These fields are intended to support deep-search refresh reviews and downstream display of data freshness. They currently describe the local curated source files, not live webpage access dates.

`output/frontend/map_bundle.json` includes `schemaVersion` and a top-level `source` block when exported from a graph loaded with these provenance fields.

## 12) Troubleshooting

- `Missing credentials`:
  - Ensure all required `NEO4J_*` keys exist in the credential file selected by `--cred-path`, `NEO4J_CREDENTIAL_FILE`, the ignored repo-root default, or a legacy ignored local credential file.
- `uvx not found`:
  - Install `uv` and ensure it is in `PATH`.
- MCP validation fails:
  - Confirm network access and Aura credentials.
- Load aborts with `Pre-wipe backup failed`:
  - The loader exports the live graph to `output/kg_exports/prewipe_<timestamp>/` before wiping and aborts if that export fails; fix connectivity/credentials and re-run, or pass `--skip-backup` to proceed without a backup (an empty database is not a failure — it backs up as 0 nodes).
- Graph is empty after run:
  - Check script logs for failed writes after the initial wipe step.
- Frontend bundle missing:
  - Run `uv run python .\scripts\export_map_frontend_payload.py` and confirm `output/frontend/map_bundle.json` exists.
