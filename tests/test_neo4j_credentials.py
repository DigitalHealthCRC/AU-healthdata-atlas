"""Tests for scripts/neo4j_credentials.py.

These never read the real credential files in the repo root (they must pass
on CI machines where no Neo4j-*.txt exists): every test either passes an
explicit tmp_path file or monkeypatches ROOT/DEFAULT_CRED_PATH to tmp_path.
"""

import pytest

import neo4j_credentials as nc


@pytest.fixture(autouse=True)
def _no_env_credential_file(monkeypatch):
    monkeypatch.delenv(nc.CREDENTIAL_ENV_VAR, raising=False)


def write_credentials(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestParseCredentials:
    def test_all_keys_parsed(self, tmp_path):
        cred = write_credentials(
            tmp_path / "creds.txt",
            [
                "NEO4J_URI=neo4j+s://example.databases.neo4j.io",
                "NEO4J_USERNAME=neo4j",
                "NEO4J_PASSWORD=p@ss=word",
                "NEO4J_DATABASE=neo4j",
                "AURA_INSTANCEID=ignored-not-neo4j-prefixed",
                "NEO4J_EXTRA=kept",
                "",
                "# comment line ignored",
            ],
        )
        creds = nc.parse_credentials(cred)
        assert creds["NEO4J_URI"] == "neo4j+s://example.databases.neo4j.io"
        assert creds["NEO4J_USERNAME"] == "neo4j"
        # value may contain '=': only the first '=' separates key from value
        assert creds["NEO4J_PASSWORD"] == "p@ss=word"
        assert creds["NEO4J_DATABASE"] == "neo4j"
        # non-NEO4J_ keys are ignored, but extra NEO4J_ keys are kept
        assert "AURA_INSTANCEID" not in creds
        assert creds["NEO4J_EXTRA"] == "kept"

    def test_missing_keys_raise_value_error_listing_them(self, tmp_path):
        cred = write_credentials(tmp_path / "creds.txt", ["NEO4J_URI=neo4j+s://x"])
        with pytest.raises(ValueError) as excinfo:
            nc.parse_credentials(cred)
        message = str(excinfo.value)
        assert "Missing credentials" in message
        for key in ("NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"):
            assert key in message


class TestResolveCredentialPath:
    def test_explicit_path_wins_over_env_var(self, tmp_path, monkeypatch):
        explicit = tmp_path / "explicit.txt"
        env_file = tmp_path / "env.txt"
        monkeypatch.setenv(nc.CREDENTIAL_ENV_VAR, str(env_file))
        assert nc.resolve_credential_path(explicit) == explicit.resolve()

    def test_env_var_used_when_no_explicit_path(self, tmp_path, monkeypatch):
        env_file = tmp_path / "env.txt"
        monkeypatch.setenv(nc.CREDENTIAL_ENV_VAR, str(env_file))
        assert nc.resolve_credential_path() == env_file.resolve()

    def test_relative_explicit_path_resolved_against_repo_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nc, "ROOT", tmp_path)
        assert nc.resolve_credential_path("subdir/creds.txt") == (tmp_path / "subdir" / "creds.txt").resolve()

    def test_default_file_found_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nc, "ROOT", tmp_path)
        monkeypatch.setattr(nc, "DEFAULT_CRED_PATH", tmp_path / nc.DEFAULT_CREDENTIAL_FILENAME)
        default = write_credentials(tmp_path / nc.DEFAULT_CREDENTIAL_FILENAME, ["NEO4J_URI=x"])
        assert nc.resolve_credential_path() == default.resolve()

    def test_legacy_pattern_used_when_default_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nc, "ROOT", tmp_path)
        monkeypatch.setattr(nc, "DEFAULT_CRED_PATH", tmp_path / nc.DEFAULT_CREDENTIAL_FILENAME)
        legacy = write_credentials(tmp_path / "Neo4j-credentials-old.txt", ["NEO4J_URI=x"])
        assert nc.resolve_credential_path() == legacy.resolve()

    def test_falls_back_to_default_path_when_nothing_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(nc, "ROOT", tmp_path)
        monkeypatch.setattr(nc, "DEFAULT_CRED_PATH", tmp_path / nc.DEFAULT_CREDENTIAL_FILENAME)
        resolved = nc.resolve_credential_path()
        assert resolved == (tmp_path / nc.DEFAULT_CREDENTIAL_FILENAME).resolve()
        assert not resolved.exists()
