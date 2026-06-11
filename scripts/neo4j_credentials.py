import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_ENV_VAR = "NEO4J_CREDENTIAL_FILE"
DEFAULT_CREDENTIAL_FILENAME = "Neo4j-credentials.txt"
DEFAULT_CRED_PATH = ROOT / DEFAULT_CREDENTIAL_FILENAME
LEGACY_CREDENTIAL_PATTERNS = ("Neo4j-credentials-*.txt", "Neo4j-*-Created-*.txt")
REQUIRED_KEYS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE")


def default_credential_candidates() -> list[Path]:
    candidates = [DEFAULT_CRED_PATH]
    for pattern in LEGACY_CREDENTIAL_PATTERNS:
        candidates.extend(sorted(ROOT.glob(pattern)))
    return list(dict.fromkeys(candidates))


def resolve_credential_path(path: str | Path | None = None) -> Path:
    raw_path = str(path).strip() if path else os.environ.get(CREDENTIAL_ENV_VAR, "").strip()
    if raw_path:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate.resolve()

    for candidate in default_credential_candidates():
        if candidate.exists():
            return candidate.resolve()

    candidate = DEFAULT_CRED_PATH
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def parse_credentials(path: str | Path | None = None) -> dict[str, str]:
    credential_path = resolve_credential_path(path)
    creds: dict[str, str] = {}
    text = credential_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = re.match(r"^(NEO4J_[A-Z_]+)=(.+)$", line.strip())
        if match:
            creds[match.group(1)] = match.group(2)

    missing = [key for key in REQUIRED_KEYS if key not in creds]
    if missing:
        raise ValueError(f"Missing credentials in {credential_path}: {missing}")
    return creds
