import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from register_parsing import (
    CSV_PATH,
    MD_PATH,
    extract_md_cards,
    extract_register_metadata,
    file_modified_at,
    looks_like_placeholder,
    parse_csv_datasets,
    parse_pathway_steps,
    parse_urls,
    read_csv_rows,
    slugify,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "output" / "source_audit"

CORE_FIELDS = [
    "Custodian Name",
    "Short Name",
    "Custodian Type",
    "Jurisdiction",
    "Sector",
    "Research Access",
    "Reverify",
    "Primary Role",
    "Key Datasets",
    "Access Pathway Steps",
    "Ethics and Governance Requirements",
    "TRE / Secure Access Platform",
    "Contact and Application Portal",
    "Indicative Timeline",
    "Connections to Other Custodians",
    "Source URLs",
    "Classification Note",
]

REQUIRED_FIELDS = [
    "Custodian Name",
    "Custodian Type",
    "Jurisdiction",
    "Primary Role",
    "Key Datasets",
    "Access Pathway Steps",
    "Contact and Application Portal",
    "Source URLs",
]


def register_metadata_summary(md_text: str) -> dict[str, str]:
    metadata = extract_register_metadata(md_text)
    return {
        "register_title": metadata["sourceRegisterTitle"],
        "register_version": metadata["sourceRegisterVersion"],
        "register_generated": metadata["sourceRegisterGenerated"],
        "custodians_documented": metadata["sourceRegisterCustodianCount"],
    }


def path_for_claim(field_name: str) -> str:
    if field_name == "Full Pathway Card (Markdown)":
        return "raw_data/AU_Health_Data_Pathway_Register.md"
    return "raw_data/pathway_cards.csv"


def priority_for_issue(issue_type: str, field_name: str) -> str:
    if issue_type in {"missing_required", "no_source_urls"}:
        return "P0"
    if field_name in {"Access Pathway Steps", "Contact and Application Portal", "Key Datasets"}:
        return "P1"
    if issue_type in {"placeholder", "blank_optional"}:
        return "P2"
    return "P3"


def make_audit_row(
    *,
    entity_type: str,
    entity_id: str,
    entity_name: str,
    field_name: str,
    current_value: str,
    issue_type: str,
    source_urls: list[str],
    notes: str = "",
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "field_name": field_name,
        "current_value": current_value,
        "issue_type": issue_type,
        "review_priority": priority_for_issue(issue_type, field_name),
        "source_urls": "; ".join(source_urls),
        "source_url_count": len(source_urls),
        "candidate_value": "",
        "evidence_status": "baseline_current" if issue_type == "ok" else "needs_refresh",
        "confidence": "",
        "notes": notes,
    }


def make_claim_record(
    *,
    run_id: str,
    custodian_id: str,
    custodian_name: str,
    custodian_row: dict[str, str],
    claim_id: str,
    entity_type: str,
    field_name: str,
    current_value: str,
    local_source_file: str,
    source_urls: list[str],
    status: str,
    change_type: str = "none",
    confidence: float = 0.0,
    needs_human_review: bool = False,
    quality_flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "custodian": {
            "id": custodian_id,
            "name": custodian_name,
            "short_name": custodian_row.get("Short Name") or "",
            "type": custodian_row.get("Custodian Type") or "",
            "jurisdiction": custodian_row.get("Jurisdiction") or "",
        },
        "claim": {
            "claim_id": claim_id,
            "entity_type": entity_type,
            "field": field_name,
            "current_value": current_value,
            "local_source_file": local_source_file,
        },
        "source": {
            "urls": source_urls,
            "source_role": "existing" if source_urls else "new_source_needed",
            "publisher": "",
            "title": "",
            "published_at": "",
            "updated_at": "",
            "accessed_at": "",
            "http_status": "",
        },
        "assessment": {
            "status": status,
            "confidence": confidence,
            "change_type": change_type,
            "proposed_value": "",
            "needs_human_review": needs_human_review,
        },
        "evidence": [],
        "quality_flags": quality_flags or [],
    }


def build_audit() -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not CSV_PATH.exists():
        errors.append(f"Missing CSV input: {CSV_PATH}")
    if not MD_PATH.exists():
        errors.append(f"Missing markdown input: {MD_PATH}")
    if errors:
        return {}, [], errors

    custodians = read_csv_rows(CSV_PATH)
    md_text = MD_PATH.read_text(encoding="utf-8")
    register_metadata = register_metadata_summary(md_text)
    md_cards = extract_md_cards(md_text)

    run_id = f"source-audit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    audit_rows: list[dict[str, Any]] = []
    claim_records: list[dict[str, Any]] = []
    dataset_updates: list[dict[str, Any]] = []
    source_evidence: dict[str, dict[str, Any]] = {}
    manual_review_items: list[dict[str, Any]] = []
    duplicate_name_counts = Counter(custodian.name for custodian in custodians)
    duplicate_names = sorted(name for name, count in duplicate_name_counts.items() if name and count > 1)
    if duplicate_names:
        errors.append(f"Duplicate custodian names: {', '.join(duplicate_names)}")

    field_issue_counts: Counter[str] = Counter()
    source_domains: Counter[str] = Counter()

    for custodian in custodians:
        row = custodian.row
        custodian_name = custodian.name
        custodian_id = custodian.custodian_id
        source_urls = parse_urls(row.get("Source URLs") or "")
        datasets = parse_csv_datasets(row.get("Key Datasets") or "")
        step_numbers = [step["number"] for step in parse_pathway_steps(row.get("Access Pathway Steps") or "")]

        if not source_urls:
            audit_rows.append(
                make_audit_row(
                    entity_type="custodian",
                    entity_id=custodian_id,
                    entity_name=custodian_name,
                    field_name="Source URLs",
                    current_value="",
                    issue_type="no_source_urls",
                    source_urls=[],
                    notes="No source URL evidence is attached to this custodian.",
                )
            )
            field_issue_counts["no_source_urls"] += 1

        for url in source_urls:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().removeprefix("www.")
            source_domains[domain] += 1
            claim_records.append(
                make_claim_record(
                    run_id=run_id,
                    custodian_id=custodian_id,
                    custodian_name=custodian_name,
                    custodian_row=row,
                    claim_id=f"{custodian_id}.source-url.{slugify(url)[:80]}",
                    entity_type="source_url",
                    field_name="Source URLs",
                    current_value=url,
                    local_source_file="raw_data/pathway_cards.csv",
                    source_urls=[url],
                    status="confirmed",
                    confidence=0.5,
                )
            )
            source_evidence.setdefault(
                url,
                {
                    "source_id": f"source:{slugify(url)[:80]}",
                    "entity": custodian_name,
                    "field_supported": "Source URLs",
                    "url": url,
                    "title": "",
                    "publisher": domain,
                    "published_or_updated_date": "",
                    "accessed_date": "",
                    "evidence_summary": "Existing baseline source URL from pathway_cards.csv.",
                    "reliability": "needs_review",
                    "notes": "",
                },
            )

        for field_name in CORE_FIELDS:
            value = (row.get(field_name) or "").strip()
            if field_name in REQUIRED_FIELDS and not value:
                issue_type = "missing_required"
            elif not value:
                issue_type = "blank_optional"
            elif looks_like_placeholder(value):
                issue_type = "placeholder"
            else:
                issue_type = "ok"

            quality_flags = [issue_type] if issue_type != "ok" else []
            claim_records.append(
                make_claim_record(
                    run_id=run_id,
                    custodian_id=custodian_id,
                    custodian_name=custodian_name,
                    custodian_row=row,
                    claim_id=f"{custodian_id}.{slugify(field_name)}",
                    entity_type="custodian",
                    field_name=field_name,
                    current_value=value,
                    local_source_file=path_for_claim(field_name),
                    source_urls=source_urls,
                    status="confirmed" if issue_type == "ok" else "new_source_needed",
                    confidence=0.5 if issue_type == "ok" else 0.0,
                    needs_human_review=issue_type != "ok",
                    quality_flags=quality_flags,
                )
            )

            field_issue_counts[issue_type] += 1
            if issue_type != "ok":
                audit_rows.append(
                    make_audit_row(
                        entity_type="custodian",
                        entity_id=custodian_id,
                        entity_name=custodian_name,
                        field_name=field_name,
                        current_value=value,
                        issue_type=issue_type,
                        source_urls=source_urls,
                    )
                )

        if not datasets:
            manual_review_items.append(
                {
                    "entity": custodian_name,
                    "issue": "No datasets parsed from Key Datasets.",
                    "priority": "P1",
                    "source_urls": source_urls,
                }
            )

        if not step_numbers:
            claim_records.append(
                make_claim_record(
                    run_id=run_id,
                    custodian_id=custodian_id,
                    custodian_name=custodian_name,
                    custodian_row=row,
                    claim_id=f"{custodian_id}.access-pathway-steps.numbered-steps",
                    entity_type="pathway_step",
                    field_name="Access Pathway Steps",
                    current_value=row.get("Access Pathway Steps") or "",
                    local_source_file="raw_data/pathway_cards.csv",
                    source_urls=source_urls,
                    status="ambiguous",
                    needs_human_review=True,
                    quality_flags=["no_numbered_steps"],
                )
            )
            manual_review_items.append(
                {
                    "entity": custodian_name,
                    "issue": "No numbered access pathway steps parsed.",
                    "priority": "P1",
                    "source_urls": source_urls,
                }
            )

        for dataset_index, dataset in enumerate(datasets, start=1):
            dataset_name = dataset["name"]
            claim_records.append(
                make_claim_record(
                    run_id=run_id,
                    custodian_id=custodian_id,
                    custodian_name=custodian_name,
                    custodian_row=row,
                    claim_id=f"{custodian_id}.dataset.{dataset_index}.{slugify(dataset_name)}",
                    entity_type="dataset",
                    field_name="Key Datasets",
                    current_value=json.dumps(dataset, ensure_ascii=False, sort_keys=True),
                    local_source_file="raw_data/pathway_cards.csv",
                    source_urls=source_urls,
                    status="confirmed",
                    confidence=0.5,
                    quality_flags=[],
                )
            )
            dataset_updates.append(
                {
                    "custodian_name": custodian_name,
                    "dataset_name": dataset_name,
                    "status": "existing_baseline",
                    "description": dataset.get("description", ""),
                    "coverage": "",
                    "identifiable": dataset.get("identifiable", ""),
                    "linkable": dataset.get("linkable", ""),
                    "access_mode": "",
                    "linkage_unit_or_tre": "",
                    "evidence_url": source_urls[0] if source_urls else "",
                    "confidence": "",
                    "notes": "Baseline dataset parsed from pathway_cards.csv.",
                }
            )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "csv_path": str(CSV_PATH),
            "csv_modified_at": file_modified_at(CSV_PATH),
            "markdown_path": str(MD_PATH),
            "markdown_modified_at": file_modified_at(MD_PATH),
            **register_metadata,
        },
        "counts": {
            "custodians": len(custodians),
            "markdown_cards": len(md_cards),
            "datasets": len(dataset_updates),
            "unique_source_urls": len(source_evidence),
            "manual_review_items": len(manual_review_items),
            "audit_rows": len(audit_rows),
            "claim_records": len(claim_records),
            "source_domains": len(source_domains),
        },
        "field_issue_counts": dict(sorted(field_issue_counts.items())),
        "top_source_domains": dict(source_domains.most_common(20)),
        "manual_review_items": manual_review_items,
        "dataset_updates": dataset_updates,
        "source_evidence": sorted(source_evidence.values(), key=lambda item: item["url"]),
        "claim_records": claim_records,
    }
    return summary, audit_rows, errors


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "entity_type",
        "entity_id",
        "entity_name",
        "field_name",
        "current_value",
        "issue_type",
        "review_priority",
        "source_urls",
        "source_url_count",
        "candidate_value",
        "evidence_status",
        "confidence",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a baseline source audit for the AU Health Data Map refresh.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for source_audit.csv/json outputs.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero only for structural errors.")
    args = parser.parse_args()

    summary, audit_rows, errors = build_audit()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "source_audit.csv", audit_rows)
    write_jsonl(out_dir / "source_claims.jsonl", summary["claim_records"])
    with (out_dir / "source_audit.json").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"summary": summary, "audit_rows": audit_rows}, ensure_ascii=False, indent=2))
        handle.write("\n")

    print(json.dumps(summary["counts"], indent=2))
    print(f"Wrote: {out_dir / 'source_audit.csv'}")
    print(f"Wrote: {out_dir / 'source_claims.jsonl'}")
    print(f"Wrote: {out_dir / 'source_audit.json'}")

    if args.check:
        critical_count = sum(1 for row in audit_rows if row["review_priority"] == "P0")
        print(f"Critical audit rows: {critical_count}")


if __name__ == "__main__":
    main()
