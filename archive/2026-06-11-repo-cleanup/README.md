# 2026-06-11 Repository Cleanup Archive

This archive keeps stale generated artefacts and one-off working snippets out of the active project paths while preserving them for traceability.

## What moved here

- `output/connection_match_review.csv`
- `output/gap_custodians.json`
- `output/kg_load_summary.json`
- `output/frontend/map_bundle.json`
- `output/kg_exports.zip`
- `output/kg_exports/20260302_100851/`
- `output/kg_exports/20260302_141907/`
- `output/kg_exports/20260302_142018/`
- `queries/ACT_test.cypher`
- `raw_data/KG_Iteration2_Codex_Prompt.md`

These files are historical March 2026 graph/export snapshots or temporary development prompts and queries. They should not be treated as the current source of truth for the map.

## What stayed active

- `raw_data/pathway_cards.csv`
- `raw_data/AU_Health_Data_Pathway_Register.md`
- `config/connection_alias_overrides.csv`
- `scripts/*.py`
- `queries/map_frontend_queries.cypher`
- `output/source_audit/`

The active source data and refresh audit remain in their original locations. New graph loads, frontend bundles, and KG snapshots should be regenerated from the active source files when needed.

## Credential handling

Neo4j credential files were not copied into this archive. They are local secrets and are ignored by `.gitignore`.

During this cleanup, the previously tracked `Neo4j-e0662ca0-Created-2026-02-27.txt` credential file was removed from Git tracking. The local file may still exist in a checkout for private use, but it should not be committed. If those credentials were ever shared outside a trusted private context, rotate them.

Scripts now resolve credentials in this order:

1. Explicit `--cred-path` where the script supports it.
2. `NEO4J_CREDENTIAL_FILE`.
3. Local ignored default file `Neo4j-credentials.txt`.
4. Existing ignored legacy local files matching `Neo4j-credentials-*.txt` or `Neo4j-*-Created-*.txt`.

## Regenerating active artefacts

Use the local source files to rebuild generated artefacts:

```powershell
uv run python .\scripts\build_source_audit.py --check
uv run python .\scripts\export_kg_snapshot.py --source-mode source
```

Only run the live Neo4j loader after reviewing the source audit, because it replaces the graph contents:

```powershell
uv run python .\scripts\load_au_health_kg_via_mcp.py
uv run python .\scripts\export_map_frontend_payload.py
```

The frontend exporter recreates `output/frontend/map_bundle.json`; the snapshot exporter recreates a timestamped folder under `output/kg_exports/`.
