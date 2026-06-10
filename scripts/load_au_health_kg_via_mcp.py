import asyncio
import csv
import hashlib
import json
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
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
GAP_JSON = OUT_DIR / "gap_custodians.json"
SOURCE_METADATA_FIELDS = (
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
)

MOJIBAKE_EN_DASH = "\u00e2\u20ac\u201c"
MOJIBAKE_EM_DASH = "\u00e2\u20ac\u201d"
DASH_VARIANTS = ("\u2013", "\u2014", MOJIBAKE_EN_DASH, MOJIBAKE_EM_DASH)
STEP_SPLIT_PATTERN = r"\s+(?:\u2013|\u2014|" + re.escape(MOJIBAKE_EN_DASH) + "|" + re.escape(MOJIBAKE_EM_DASH) + r"|-)\s+"
FUZZY_ACCEPT_THRESHOLD = 0.90
GENERIC_ACRONYM_ALIASES = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}

NOT_A_CUSTODIAN_PATTERNS = (
    "family cancer centres",
    "university",
    "universities",
    "research institution",
    "research institutions",
    "medical research institute",
    "medical research institutes",
    "clinical trials network",
    "clinical trials networks",
    "clinical network",
    "clinical networks",
    "aaf",
    "australian access federation",
    "funding bodies",
    "insurance commission",
    "department of transport",
    "main roads wa",
    "other acchos",
)

STRUCTURAL_NOTE_PATTERNS = (
    "other data custodians",
    "other commonwealth agencies",
    "other state and territory",
    "other state territory",
    "state and territory health authorities",
    "state and federal data custodians",
    "australian state and federal data custodians",
    "australian government data custodians",
    "verify with custodian",
    "not explicitly mentioned",
    "not explicitly stated",
)

GAP_ENTITY_PATTERNS = {
    "victorian comprehensive cancer centre": "Victorian Comprehensive Cancer Centre (VCCC) Data Connect",
    "vccc data connect": "Victorian Comprehensive Cancer Centre (VCCC) Data Connect",
}

SEEDED_GAP_CUSTODIANS = [
    {
        "sourceId": "custodian:victorian-cancer-registry",
        "sourceName": "Victorian Cancer Registry",
        "segment": "Victorian Comprehensive Cancer Centre (VCCC) Data Connect",
        "gapName": "Victorian Comprehensive Cancer Centre (VCCC) Data Connect",
    }
]

EXTRA_ALIASES_BY_NAME = {
    "Australian Commission on Safety and Quality in Health Care": {"ACSQHC"},
    "Australian Bureau of Statistics": {"ABS"},
    "Australian Institute of Health and Welfare": {"AIHW"},
    "Australian Institute of Health and Welfare Data Integration Services Centre": {"AIHW DISC", "AIHW Data Integration Services", "Dataplace"},
    "Australian Government Department of Health and Aged Care": {"Department of Health and Aged Care", "DoHAC"},
    "Australian Research Data Commons": {"ARDC", "HeSANDA", "Health Data Australia"},
    "Centre for Health Record Linkage": {"CHeReL"},
    "National Aboriginal Community Controlled Health Organisation": {"NACCHO"},
    "Population Health Research Network": {"PHRN"},
    "Queensland Health": {"Data Linkage Queensland", "DLQ", "SALUD", "Statistical Analysis and Linkage Unit"},
    "Department of Social Services": {"DSS", "DOMINO"},
    "Secure Unified Research Environment": {"SURE"},
    "Tasmanian Department of Health / Tasmanian Data Linkage Unit": {"Tasmanian DoH", "TDLU"},
    "Victorian Agency for Health Information": {"VAHI", "Department of Health and Human Services Victoria", "DHHS Victoria"},
}

SPECIAL_TYPES_BY_NAME = {
    "APRA": "Statistical Publisher",
    "ARDC": "Data Discovery Service",
    "NACCHO / Aboriginal Community Controlled Health Organisations (ACCHOs)": "Governance Body",
}

SPECIAL_PRIMARY_ROLES_BY_NAME = {
    "APRA": (
        "APRA is a statistical publisher for private health insurance industry reporting. "
        "It publishes aggregate private health insurance statistics for public download and does not operate "
        "a researcher-facing application process for individual-level data access."
    ),
    "ARDC": (
        "ARDC operates Health Data Australia (HeSANDA) as a national health data discovery service. "
        "It helps researchers find datasets and identify the holding custodian, but does not itself hold or release "
        "research data directly."
    ),
    "NACCHO / Aboriginal Community Controlled Health Organisations (ACCHOs)": (
        "NACCHO is the national peak body for the Aboriginal Community Controlled Health Organisation sector. "
        "It serves as both a data governance body for Indigenous health research and an indirect data custodian "
        "through its member ACCHOs, with a central role in consent, ethics, sovereignty, and sector-wide reporting."
    ),
    "Department of Social Services": (
        "DSS is the Commonwealth custodian of welfare, disability, and social services administrative data. "
        "Key datasets include DOMINO, payment and programme data, NDIS-related holdings via NDIA, and aged care "
        "program data used in policy and linked-data research."
    ),
}

SPECIAL_ACCESS_STEPS_BY_NAME = {
    "APRA": (
        "1. Download published statistics - Researcher - APRA private health insurance statistics pages - 1-2 weeks"
    ),
    "ARDC": (
        "1. Search HeSANDA catalogue - Researcher - Health Data Australia portal search - 1-2 weeks\n"
        "2. Identify holding custodian - Researcher - Review dataset metadata, access conditions, and contact details - 1-2 weeks\n"
        "3. Follow custodian access pathway - Researcher - Apply directly to the identified custodian - 1-4 weeks"
    ),
    "Department of Social Services": (
        "1. Initial inquiry - Researcher - Contact DSS Data Governance team or confirm whether AIHW Data Integration Services is the correct intermediary - 1-2 weeks\n"
        "2. Project and governance submission - Researcher - Submit research proposal, governance materials, and data requirements - 1-4 weeks\n"
        "3. Ethics and custodian review - Researcher/Custodian - Obtain HREC approval and DSS data governance approval where required - 4-12 weeks\n"
        "4. Data preparation and provision - Custodian - DSS or AIHW prepares approved extracts for secure access - 2-12 weeks"
    ),
}

SPECIAL_CONNECTIONS_BY_NAME = {
    "Department of Health and Aged Care": [
        "Australian Institute of Health and Welfare (AIHW) (for NIHSI/NHDH, GTD data)",
        "Services Australia (for Medicare statistics, MBS/PBS data)",
    ],
    "TGA": [
        "Services Australia (PBS adverse event linkage and pharmacovigilance context)",
        "AIHW (therapeutic goods reporting and linked health data context)",
        "Department of Health and Aged Care (regulatory policy and portfolio oversight)",
    ],
    "Cancer Institute NSW": [
        "NSW Health - Ministry of Health NSW (Cancer Institute NSW is a statutory body within the NSW Health portfolio)",
    ],
    "Victorian Cancer Registry": [
        "Australian Institute of Health and Welfare (AIHW) (for compiling national cancer figures)",
        "VAHI (Victorian Agency for Health Information) (Victorian health system reporting and governance alignment)",
    ],
    "Queensland Health": [
        "Australian Institute of Health and Welfare (AIHW) (national hospital data reporting)",
        "QCIF (secure infrastructure used by Queensland researchers working with Queensland Health data)",
        "PHRN (through Data Linkage Queensland / SALUD for linkage)",
        "Cancer Institute NSW (cross-state cancer registry comparison work)",
    ],
    "QCIF": [
        "Queensland Health (secure research infrastructure for Queensland Health data users)",
        "PHRN (national linkage network peer infrastructure)",
        "SURE - Secure Unified Research Environment (TRE infrastructure peer)",
    ],
    "WA Health / Data Linkage Services WA": [
        "Australian Institute of Health and Welfare (AIHW) (cross-jurisdictional research and reporting)",
        "Population Health Research Network (PHRN) (national linkage network membership)",
    ],
    "SA Health / SA NT DataLink": [
        "Services Australia (for MBS, PBS, and Centrelink data used in linked projects)",
        "Population Health Research Network (PHRN) (national linkage network membership)",
    ],
    "ABS DataLab": [
        "AIHW (linked data projects via AIHW Data Integration Services)",
        "Services Australia (MBS, PBS, and Centrelink linkage in approved projects)",
        "PHRN (national data linkage ecosystem)",
        "Department of Health and Aged Care (Commonwealth health data access context)",
    ],
    "AIHW Data Integration Services": [
        "Services Australia (for MBS/PBS data)",
        "AIHW (host agency and data integration service operator)",
    ],
    "MedicineInsight (NPS MedicineWise)": [
        "NHMRC / HRECs (ethics approval and governance requirements for research use)",
        "Department of Health and Aged Care (primary care policy reporting)",
        "PHN Cooperative / Primary Health Insights (PHN-level data aggregation and service planning)",
        "Services Australia (MBS/PBS cross-reference in primary care analysis)",
    ],
    "NHMRC / HRECs": [
        "AIHW (HREC approval is commonly required for AIHW data access)",
        "Services Australia (HREC approval is commonly required for linked MBS/PBS access)",
    ],
    "AIATSIS": [
        "AIHW (national health data linkage and reporting context)",
        "Australian Bureau of Statistics (ABS) (national statistical linkage context)",
        "NACCHO / Aboriginal Community Controlled Health Organisations (ACCHOs) (Indigenous data governance alignment)",
    ],
    "NACCHO / Aboriginal Community Controlled Health Organisations (ACCHOs)": [
        "AIHW (national Indigenous health reporting and linkage)",
        "Australian Bureau of Statistics (ABS) (population and community linkage context)",
        "NSW Health - Ministry of Health NSW (policy alignment and linked data projects)",
        "VAHI (Victorian Agency for Health Information) (policy alignment and linked data projects)",
        "Queensland Health (policy alignment and linked data projects)",
        "WA Health / Data Linkage Services WA (policy alignment and linked data projects)",
        "SA Health / SA NT DataLink (policy alignment and linked data projects)",
        "ACT Health (policy alignment and linked data projects)",
        "NT Health / NT Health Research Governance Office (policy alignment and linked data projects)",
        "Tasmanian Department of Health / Tasmanian Data Linkage Unit (TDLU) (policy alignment and linked data projects)",
    ],
    "ARDC": [
        "AIHW (Health Data Australia catalogue includes AIHW collections)",
        "Australian Bureau of Statistics (ABS) (ABS datasets are discoverable through Health Data Australia)",
        "NHMRC / HRECs (research data management and governance alignment)",
    ],
    "AIHW": [
        "Department of Social Services (DSS) (DOMINO accessible via AIHW Data Integration Services)",
    ],
    "Private Hospital Data Bureau (PHDB) via AIHW / Department of Health": [
        "Department of Social Services (DSS) (DOMINO upstream provider for linked work via AIHW)",
        "Australian Institute of Health and Welfare (AIHW) (PHDB management and access coordination)",
        "Department of Health and Aged Care (policy and stewardship context)",
    ],
}

SPECIAL_DATASETS_BY_NAME = {
    "APRA": [
        {
            "name": "Private health insurance statistics",
            "description": "Published aggregate private health insurance tables and industry statistics.",
            "identifiable": "No",
            "linkable": "No (aggregate only)",
            "source": "remediation",
        }
    ],
    "ARDC": [
        {
            "name": "Health Data Australia (HeSANDA) catalogue",
            "description": "Metadata catalogue for Australian health datasets discoverable through ARDC infrastructure.",
            "identifiable": "No",
            "linkable": "No",
            "source": "remediation",
        }
    ],
    "NACCHO / Aboriginal Community Controlled Health Organisations (ACCHOs)": [
        {
            "name": "NACCHO Member Organisation Health Data",
            "description": "Aggregated primary care data from ACCHO member services.",
            "identifiable": "Yes (de-identified for reporting)",
            "linkable": "Yes (via AIHW Data Integration Services)",
            "source": "remediation",
        },
        {
            "name": "QAIHC Health Data Collections",
            "description": "Queensland Aboriginal and Islander Health Council member data.",
            "identifiable": "Yes (de-identified)",
            "linkable": "Yes (verify with custodian)",
            "source": "remediation",
        },
        {
            "name": "AMSANT Health Data",
            "description": "Aboriginal Medical Services Alliance NT member data.",
            "identifiable": "Yes (de-identified)",
            "linkable": "Yes (verify with custodian)",
            "source": "remediation",
        },
        {
            "name": "Close the Gap data",
            "description": "National progress data on Indigenous health targets.",
            "identifiable": "No",
            "linkable": "No (aggregate only)",
            "source": "remediation",
        },
    ],
    "Department of Social Services": [
        {
            "name": "DOMINO",
            "description": "Data Over Multiple Individual Occurrences covering income support and welfare payments.",
            "identifiable": "Yes",
            "linkable": "Yes (via AIHW Data Integration Services)",
            "source": "remediation",
        },
        {
            "name": "DSS Payment and Programme Data",
            "description": "Administrative data on Commonwealth welfare payments and program participation.",
            "identifiable": "Yes",
            "linkable": "Yes",
            "source": "remediation",
        },
        {
            "name": "NDIS participant data",
            "description": "Participant-level NDIS administrative data managed with NDIA involvement.",
            "identifiable": "Yes",
            "linkable": "Yes",
            "source": "remediation",
        },
    ],
}

LINKAGE_PLATFORM_BY_NAME = {
    "Queensland Health": "Data Linkage Queensland",
    "WA Health / Data Linkage Services WA": "Data Linkage Services WA",
    "SA Health / SA NT DataLink": "SA NT DataLink",
    "Tasmanian Department of Health / Tasmanian Data Linkage Unit (TDLU)": "Tasmanian Data Linkage Unit",
    "ACT Health": "CHeReL",
    "Centre for Victorian Data Linkage (CVDL)": "Centre for Victorian Data Linkage",
    "CHeReL": "CHeReL",
    "PHRN": "PHRN",
    "AIHW": "AIHW Data Integration Services",
    "AIHW Data Integration Services": "AIHW Data Integration Services",
    "ABS DataLab": "ABS DataLab",
}


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


def replace_dash_variants(value: str) -> str:
    out = value or ""
    for dash in DASH_VARIANTS:
        out = out.replace(dash, "-")
    return out


def normalize_text(value: str) -> str:
    value = replace_dash_variants(value or "")
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


def path_for_metadata(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def file_modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def extract_register_metadata(md_text: str) -> dict[str, str]:
    title = ""
    version = ""
    generated = ""
    custodians_documented = ""

    title_match = re.search(r"^#\s+(.+)$", md_text, flags=re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        version_match = re.search(r"Version\s+([A-Za-z0-9._-]+)", title)
        if version_match:
            version = version_match.group(1)

    generated_match = re.search(r"\*\*Generated:\*\*\s*(.+?)\s*$", md_text, flags=re.MULTILINE)
    if generated_match:
        generated = generated_match.group(1).strip()

    custodian_match = re.search(r"\*\*Custodians documented:\*\*\s*(\d+)", md_text, flags=re.MULTILINE)
    if custodian_match:
        custodians_documented = custodian_match.group(1)

    return {
        "sourceRegisterTitle": title,
        "sourceRegisterVersion": version,
        "sourceRegisterGenerated": generated,
        "sourceRegisterCustodianCount": custodians_documented,
    }


def build_source_metadata(
    md_text: str,
    *,
    custodian_row_count: int = 0,
    markdown_card_count: int = 0,
    override_rule_count: int = 0,
) -> dict[str, str]:
    return {
        **extract_register_metadata(md_text),
        "sourceCsvPath": path_for_metadata(CSV_PATH),
        "sourceMarkdownPath": path_for_metadata(MD_PATH),
        "sourceCsvModifiedAt": file_modified_at(CSV_PATH),
        "sourceMarkdownModifiedAt": file_modified_at(MD_PATH),
        "sourceCsvSha256": file_sha256(CSV_PATH),
        "sourceMarkdownSha256": file_sha256(MD_PATH),
        "sourceCustodianRowCount": str(custodian_row_count),
        "sourceMarkdownCardCount": str(markdown_card_count),
        "sourceOverrideRuleCount": str(override_rule_count),
        "sourceGitCommit": current_git_commit(),
        "sourceProvenanceStatus": "baseline_curated",
    }


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
    parts = re.split(r"\s+/\s+|[;,]\s*", replace_dash_variants(text))
    return [p.strip() for p in parts if p.strip()]


def normalize_custodian_type_name(value: str) -> str:
    value = replace_dash_variants(value)
    value = re.sub(r"\bState\s*-\s*([A-Za-z]{2,3})\b", lambda m: f"State - {m.group(1).upper()}", value)
    return re.sub(r"\s+", " ", value).strip()


def looks_like_placeholder(value: str) -> bool:
    norm = normalize_text(value)
    if not norm:
        return True
    placeholder_terms = (
        "verify with custodian",
        "not specified",
        "to be verified",
        "n a",
        "not applicable",
        "timeline varies",
        "varies by",
        "as agreed",
    )
    return any(term in norm for term in placeholder_terms)


def infer_step_timeline(text: str, actor: str, channel: str, timeline: str) -> str:
    if timeline and not looks_like_placeholder(timeline):
        return timeline.strip()

    basis = normalize_text(" ".join([text, actor, channel]))
    if any(term in basis for term in ("linkage", "linked data", "data linkage")):
        return "3-6 months"
    if any(term in basis for term in ("ethic", "hrec")):
        return "4-12 weeks"
    if any(
        term in basis
        for term in (
            "onboarding",
            "register and activate account",
            "account setup",
            "activate account",
            "safe onboarding",
        )
    ):
        return "1-2 weeks"
    if any(
        term in basis
        for term in (
            "decision",
            "approval",
            "review",
            "feasibility",
            "governance",
            "board",
            "risk assessment",
        )
    ):
        return "2-8 weeks"
    if any(
        term in basis
        for term in (
            "provision",
            "grant access",
            "transfer",
            "extract",
            "supply",
            "download published statistics",
        )
    ):
        return "2-12 weeks"
    if any(term in basis for term in ("submit", "application", "proposal", "request", "expression of interest", "eoi")):
        return "1-4 weeks"
    if any(
        term in basis
        for term in (
            "initial inquiry",
            "initial enquiry",
            "contact",
            "discover",
            "search",
            "check publicly available",
            "review our data collections",
            "identify holding custodian",
        )
    ):
        return "1-2 weeks"
    if any(term in basis for term in ("close project", "destroy data", "progress report", "final report")):
        return "1-2 weeks"
    return "2-8 weeks"


def parse_urls(text: str) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"https?://[^\s)]+", text)))


def build_step_record(number: int, text: str, actor: str = "", channel: str = "", timeline: str = "") -> dict[str, Any]:
    lane_basis = f"{text} {actor}".lower()
    lane = "Custodian"
    if any(k in lane_basis for k in ["researcher", "applicant"]):
        lane = "Researcher"
    elif any(k in lane_basis for k in ["hrec", "ethic", "committee", "governance", "approval"]):
        lane = "EthicsRegulatory"

    return {
        "number": number,
        "text": text.strip(),
        "actor": actor.strip(),
        "channel": channel.strip(),
        "timeline": infer_step_timeline(text, actor, channel, timeline),
        "lane": lane,
    }


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
        parts = re.split(STEP_SPLIT_PATTERN, body)
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
        steps.append(build_step_record(num, text, actor, channel, timeline))
    if steps:
        return steps

    compact = re.sub(r"\s+", " ", replace_dash_variants(step_text)).strip()
    for match in re.finditer(r"Step\s*(\d+)\s*:\s*(.*?)(?=\s*Step\s*\d+\s*:|$)", compact, flags=re.IGNORECASE):
        num = int(match.group(1))
        body = match.group(2).strip(" |")

        text = body
        actor = ""
        channel = ""
        timeline = ""

        text_match = re.match(r"^(.*?)(?=\s*\|\s*Actor\s*:|\s*\|\s*Form/Portal\s*:|\s*\|\s*Duration\s*:|$)", body, flags=re.IGNORECASE)
        if text_match:
            text = text_match.group(1).strip(" |")

        actor_match = re.search(r"\|\s*Actor\s*:\s*(.*?)(?=\s*\|\s*Form/Portal\s*:|\s*\|\s*Duration\s*:|$)", body, flags=re.IGNORECASE)
        if actor_match:
            actor = actor_match.group(1).strip(" |")

        channel_match = re.search(r"\|\s*Form/Portal\s*:\s*(.*?)(?=\s*\|\s*Duration\s*:|$)", body, flags=re.IGNORECASE)
        if channel_match:
            channel = channel_match.group(1).strip(" |")

        timeline_match = re.search(r"\|\s*Duration\s*:\s*(.*)$", body, flags=re.IGNORECASE)
        if timeline_match:
            timeline = timeline_match.group(1).strip(" |")

        steps.append(build_step_record(num, text, actor, channel, timeline))
    return steps


def parse_csv_datasets(key_datasets: str) -> list[dict[str, str]]:
    if not key_datasets:
        return []
    cleaned = re.sub(r"\s*\n\s*", ";", key_datasets).strip()
    pipe_matches = list(
        re.finditer(
            (
                r"(?:^|;\s*)"
                r"(?P<name>[^|;\n]+?)\|"
                r"(?P<description>[^|\n]+?)\|"
                r"(?P<identifiable>[^|\n]+?)\|"
                r"(?P<linkable>.*?)(?=(?:;\s*[^|;\n]+?\|[^|\n]+?\|[^|\n]+?\|)|$)"
            ),
            cleaned,
            flags=re.IGNORECASE,
        )
    )
    if pipe_matches:
        out: list[dict[str, str]] = []
        for match in pipe_matches:
            name = match.group("name").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "description": match.group("description").strip(),
                    "identifiable": match.group("identifiable").strip(),
                    "linkable": match.group("linkable").strip(" ;"),
                    "source": "csv",
                }
            )
        if out:
            return out
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
    legacy_matches = list(re.finditer(r"^## Pathway Card:\s*(.+)$", md_text, flags=re.MULTILINE))
    if legacy_matches:
        for i, match in enumerate(legacy_matches):
            title = match.group(1).strip()
            start = match.end()
            end = legacy_matches[i + 1].start() if i + 1 < len(legacy_matches) else len(md_text)
            cards.append((title, md_text[start:end].strip()))
        return cards

    section_matches = list(re.finditer(r"^##\s+(.+)$", md_text, flags=re.MULTILINE))
    for i, match in enumerate(section_matches):
        title = match.group(1).strip()
        start = match.end()
        end = section_matches[i + 1].start() if i + 1 < len(section_matches) else len(md_text)
        body = md_text[start:end].strip()
        if not re.search(r"^\|\s*\*\*Full Name\*\*\s*\|", body, flags=re.MULTILINE):
            continue
        cards.append((title, body))
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


def build_full_pathway_card_markdown(row: dict[str, str], datasets: list[dict[str, str]]) -> str:
    lines = [
        f"## Pathway Card: {row.get('Custodian Name', '').strip()}",
        "",
        f"**Custodian Type:** {row.get('Custodian Type', '').strip()}",
        "",
        f"**Jurisdiction:** {row.get('Jurisdiction', '').strip()}",
        "",
        f"**Primary Role:** {row.get('Primary Role', '').strip()}",
        "",
        "**Key Data Holdings:**",
        "| Dataset Name | Description | Identifiable? | Linkable? |",
        "|---|---|---|---|",
    ]
    for ds in datasets:
        lines.append(
            f"| {ds.get('name', '').strip()} | {ds.get('description', '').strip()} | "
            f"{ds.get('identifiable', '').strip()} | {ds.get('linkable', '').strip()} |"
        )
    lines.extend(
        [
            "",
            "**Data Access Pathway - Step by Step:**",
            row.get("Access Pathway Steps", "").strip(),
            "",
            "**Ethics and Governance Requirements:**",
            row.get("Ethics and Governance Requirements", "").strip(),
            "",
            "**Trusted Research Environment (TRE) / Secure Access:**",
            row.get("TRE / Secure Access Platform", "").strip(),
            "",
            "**Contact and Application Portal:**",
            row.get("Contact and Application Portal", "").strip(),
            "",
            "**Indicative Timeline:**",
            row.get("Indicative Timeline", "").strip(),
            "",
            "**Connections to Other Custodians / Pathways:**",
            row.get("Connections to Other Custodians", "").strip(),
            "",
            "**Known Gaps / Verify with Custodian:**",
            row.get("Gaps / Verify with Custodian", "").strip(),
            "",
            "**Source URLs:**",
            row.get("Source URLs", "").strip(),
        ]
    )
    return "\n".join(lines).strip()


def infer_dataset_identifiable(custodian: CustodianRow, dataset: dict[str, str]) -> str:
    current = (dataset.get("identifiable") or "").strip()
    if current and (dataset.get("source") == "remediation" or "verify with custodian" not in normalize_text(current)):
        return current

    basis = normalize_text(
        " ".join(
            [
                dataset.get("name") or "",
                dataset.get("description") or "",
                custodian.row.get("Primary Role") or "",
                custodian.row.get("Custodian Type") or "",
            ]
        )
    )
    if any(term in basis for term in ("aggregate", "aggregated", "statistics", "statistical", "dashboard", "table", "catalogue", "catalog", "metadata")):
        return "No"
    if "de identified" in basis:
        return "No (de-identified)"
    if any(
        term in basis
        for term in (
            "patient",
            "participant",
            "person",
            "people",
            "individual",
            "register",
            "hospital",
            "admitted",
            "clinical",
            "encounter",
            "medicare",
            "pbs",
            "claim",
            "payment",
            "programme",
            "program",
            "death",
            "morbidity",
            "perinatal",
            "screening",
            "notifiable",
        )
    ):
        return "Yes"
    if "linkage" in basis or "integrat" in basis:
        return "Yes (for linkage)"
    if normalize_text(custodian.row.get("Custodian Type") or "") in {"statistical publisher", "data discovery service"}:
        return "No"
    if "tre sde" in normalize_text(custodian.row.get("Custodian Type") or ""):
        return "Yes (indirectly)"
    return "De-identified (verify with custodian)"


def infer_dataset_linkable(custodian: CustodianRow, dataset: dict[str, str], identifiable: str) -> str:
    current = (dataset.get("linkable") or "").strip()
    if current and (dataset.get("source") == "remediation" or "verify with custodian" not in normalize_text(current)):
        return current

    basis = normalize_text(
        " ".join(
            [
                dataset.get("name") or "",
                dataset.get("description") or "",
                custodian.row.get("Primary Role") or "",
                custodian.row.get("Connections to Other Custodians") or "",
            ]
        )
    )
    if any(term in basis for term in ("aggregate", "aggregated", "statistics", "statistical", "dashboard", "table", "catalogue", "catalog", "metadata")):
        return "No (aggregate only)"

    platform = LINKAGE_PLATFORM_BY_NAME.get(custodian.name)
    if platform:
        return f"Yes (via {platform})"
    if any(term in basis for term in ("linkage", "linked", "integrated")):
        return "Yes"
    if identifiable.startswith("No"):
        return "No"
    return "Yes"


def dedupe_datasets(datasets: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: dict[str, dict[str, str]] = {}
    for dataset in datasets:
        name = (dataset.get("name") or "").strip()
        if not name:
            continue
        key = normalize_text(name)
        existing = deduped.get(key)
        if not existing:
            deduped[key] = dataset.copy()
            continue
        for field in ("description", "identifiable", "linkable"):
            if not existing.get(field) and dataset.get(field):
                existing[field] = dataset[field]
    return list(deduped.values())


def ensure_dataset_coverage(custodian: CustodianRow, datasets: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched = [dataset.copy() for dataset in datasets]
    for dataset in SPECIAL_DATASETS_BY_NAME.get(custodian.name, []):
        enriched.append(dataset.copy())

    if not enriched:
        enriched.append(
            {
                "name": f"{custodian.name} data holdings",
                "description": "(inferred from custodian role - verify)",
                "identifiable": "",
                "linkable": "",
                "source": "inferred",
            }
        )

    finalized: list[dict[str, str]] = []
    for dataset in dedupe_datasets(enriched):
        identifiable = infer_dataset_identifiable(custodian, dataset)
        linkable = infer_dataset_linkable(custodian, dataset, identifiable)
        finalized.append(
            {
                "name": (dataset.get("name") or "").strip(),
                "description": (dataset.get("description") or "").strip(),
                "identifiable": identifiable,
                "linkable": linkable,
                "source": dataset.get("source") or "csv",
            }
        )
    return finalized


def build_synthetic_dss_row(template_keys: list[str]) -> CustodianRow:
    row = {key: "" for key in template_keys}
    row["Subject"] = "Department of Social Services (DSS)"
    row["Custodian Name"] = "Department of Social Services"
    row["Custodian Type"] = "Commonwealth"
    row["Jurisdiction"] = "Commonwealth"
    row["Primary Role"] = SPECIAL_PRIMARY_ROLES_BY_NAME["Department of Social Services"]
    row["Key Datasets"] = "DOMINO, DSS Payment and Programme Data, NDIS participant data"
    row["Access Pathway Steps"] = SPECIAL_ACCESS_STEPS_BY_NAME["Department of Social Services"]
    row["TRE / Secure Access Platform"] = "Most research access is mediated through AIHW Data Integration Services or another approved secure environment."
    row["Contact and Application Portal"] = "DSS Data Governance team (specific contact to verify with custodian)."
    row["Indicative Timeline"] = "Initial inquiry: 1-2 weeks; Governance and ethics review: 4-12 weeks; Data provision: 2-12 weeks."
    row["Connections to Other Custodians"] = (
        "Australian Institute of Health and Welfare (AIHW) (DOMINO accessible via AIHW Data Integration Services); "
        "Services Australia (income support data overlap and operational alignment); "
        "Department of Health and Aged Care (aged care policy and program linkage context)"
    )
    row["Gaps / Verify with Custodian"] = "Confirm the current DSS research data access contact point and any NDIA-specific approval requirements."
    row["Source URLs"] = ""
    dss_row = CustodianRow(custodian_id="custodian:department-of-social-services", name="Department of Social Services", row=row)
    datasets = ensure_dataset_coverage(dss_row, [])
    row["Full Pathway Card (Markdown)"] = build_full_pathway_card_markdown(row, datasets)
    return dss_row


def apply_iteration2_remediations(custodians: list[CustodianRow]) -> list[CustodianRow]:
    if not custodians:
        return []

    remediated: list[CustodianRow] = []
    template_keys = list(custodians[0].row.keys())

    for custodian in custodians:
        row = custodian.row.copy()
        name = custodian.name
        row["Custodian Type"] = normalize_custodian_type_name(SPECIAL_TYPES_BY_NAME.get(name, row.get("Custodian Type") or ""))
        if name in SPECIAL_PRIMARY_ROLES_BY_NAME:
            row["Primary Role"] = SPECIAL_PRIMARY_ROLES_BY_NAME[name]
        if name in SPECIAL_ACCESS_STEPS_BY_NAME:
            row["Access Pathway Steps"] = SPECIAL_ACCESS_STEPS_BY_NAME[name]
        if name in SPECIAL_CONNECTIONS_BY_NAME:
            row["Connections to Other Custodians"] = "; ".join(SPECIAL_CONNECTIONS_BY_NAME[name])
        remediated.append(CustodianRow(custodian_id=custodian.custodian_id, name=name, row=row))

    existing_ids = {custodian.custodian_id for custodian in remediated}
    dss_row = build_synthetic_dss_row(template_keys)
    if dss_row.custodian_id not in existing_ids:
        remediated.append(dss_row)

    final_rows: list[CustodianRow] = []
    for custodian in remediated:
        datasets = ensure_dataset_coverage(custodian, parse_csv_datasets(custodian.row.get("Key Datasets") or ""))
        row = custodian.row.copy()
        if custodian.name in SPECIAL_DATASETS_BY_NAME or custodian.name in SPECIAL_PRIMARY_ROLES_BY_NAME:
            row["Full Pathway Card (Markdown)"] = build_full_pathway_card_markdown(row, datasets)
        final_rows.append(CustodianRow(custodian_id=custodian.custodian_id, name=custodian.name, row=row))
    return final_rows


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
            if token in GENERIC_ACRONYM_ALIASES:
                continue
            aliases.add(token)
    aliases.update(EXTRA_ALIASES_BY_NAME.get(name, set()))
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    id_to_name = {c.custodian_id: c.name for c in custodians}
    accepted: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = [gap.copy() for gap in SEEDED_GAP_CUSTODIANS]

    for c in custodians:
        raw = (c.row.get("Connections to Other Custodians") or "").strip()
        if not raw:
            continue

        segments = [s.strip(" .") for s in re.split(r";|\n", raw) if s.strip(" .")]
        if not segments:
            segments = [raw]

        for idx, seg in enumerate(segments, start=1):
            seg_norm = normalize_text(seg)
            leading_seg_norm = normalize_text(re.split(r"[:(]", seg, maxsplit=1)[0])

            gap_name = next((name for pattern, name in GAP_ENTITY_PATTERNS.items() if pattern in seg_norm), "")
            if gap_name:
                gaps.append({"sourceId": c.custodian_id, "sourceName": c.name, "segment": seg, "gapName": gap_name})
                review.append(
                    {
                        "id": f"review:{c.custodian_id}:{idx}:{slugify(seg)[:40]}:gap",
                        "sourceId": c.custodian_id,
                        "sourceName": c.name,
                        "rawText": raw,
                        "segment": seg,
                        "candidateCustodian": "",
                        "targetId": "",
                        "score": 0.0,
                        "matchType": "gap_custodian",
                        "status": "rejected",
                    }
                )
                continue

            if any(pattern in seg_norm for pattern in NOT_A_CUSTODIAN_PATTERNS):
                review.append(
                    {
                        "id": f"review:{c.custodian_id}:{idx}:{slugify(seg)[:40]}:not-custodian",
                        "sourceId": c.custodian_id,
                        "sourceName": c.name,
                        "rawText": raw,
                        "segment": seg,
                        "candidateCustodian": "",
                        "targetId": "",
                        "score": 0.0,
                        "matchType": "not_a_custodian",
                        "status": "rejected",
                    }
                )
                continue

            if any(pattern in seg_norm for pattern in STRUCTURAL_NOTE_PATTERNS):
                review.append(
                    {
                        "id": f"review:{c.custodian_id}:{idx}:{slugify(seg)[:40]}:structural",
                        "sourceId": c.custodian_id,
                        "sourceName": c.name,
                        "rawText": raw,
                        "segment": seg,
                        "candidateCustodian": "",
                        "targetId": "",
                        "score": 0.0,
                        "matchType": "structural_note",
                        "status": "rejected",
                    }
                )
                continue

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
                            "status": "rejected",
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
                leading_name_hit = bool(full_name_norm and leading_seg_norm == full_name_norm)
                alias_hit = None
                alias_hit_len = 0
                leading_alias_hit = None
                for alias in aliases:
                    alias_norm = normalize_text(alias)
                    if len(alias_norm) < 3:
                        continue
                    if leading_seg_norm == alias_norm:
                        leading_alias_hit = alias
                    if f" {alias_norm} " in f" {seg_norm} ":
                        if len(alias_norm) > alias_hit_len:
                            alias_hit = alias
                            alias_hit_len = len(alias_norm)

                if leading_name_hit:
                    score = 1.02
                    match_type = "name_leading"
                elif leading_alias_hit is not None:
                    score = 1.01
                    match_type = "alias_leading"
                elif full_name_hit:
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
            if best["match_type"] in {"name_leading", "alias_leading"}:
                ambiguous = False
            has_verify_placeholder = "verify with custodian" in seg_norm
            accepted_flag = (
                (best["match_type"] in {"name_leading", "alias_leading", "name_exact", "alias_exact"} and not ambiguous and not has_verify_placeholder)
                or (best["score"] >= FUZZY_ACCEPT_THRESHOLD and not ambiguous and not has_verify_placeholder)
            )
            review_required = (
                not accepted_flag
                and best["match_type"] in {"name_leading", "alias_leading", "name_exact", "alias_exact", "alias_short"}
                and not has_verify_placeholder
            )
            status = "accepted" if accepted_flag else ("review_required" if review_required else "rejected")

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
    deduped_gaps: dict[tuple[str, str], dict[str, str]] = {}
    for gap in gaps:
        deduped_gaps[(gap["sourceId"], gap["gapName"])] = gap
    return list(dedup.values()), review, list(deduped_gaps.values())


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
    source_metadata: dict[str, str],
) -> dict[str, Any]:
    cypher = StdioServerParameters(
        command="uvx",
        args=["mcp-neo4j-cypher@0.5.3", "--transport", "stdio"],
        env={**os.environ, **creds},
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


async def main() -> None:
    creds = parse_credentials(CRED_PATH)
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

    validation = await validate_servers(creds)
    load_summary = await load_graph(
        creds=creds,
        custodians=custodians,
        md_cards_by_custodian_id=md_cards_by_custodian_id,
        datasets_by_custodian_id=datasets_by_custodian_id,
        connections_accepted=accepted_connections,
        connections_review=review_connections,
        source_metadata=source_metadata,
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
            *SOURCE_METADATA_FIELDS,
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_connections)

    GAP_JSON.write_text(json.dumps(gap_custodians, indent=2), encoding="utf-8")

    summary = {
        "validation": validation,
        "load": load_summary,
        "matching": {
            "override_rule_count": len(overrides),
            "gap_custodian_count": len(gap_custodians),
        },
        "source": source_metadata,
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
