"""Regression tests for build_connection_matches in scripts/register_parsing.py.

Uses small synthetic CustodianRow fixtures. These pin CURRENT behavior,
including precedence quirks (called out inline).
"""

import pytest

from register_parsing import (
    FUZZY_ACCEPT_THRESHOLD,
    SEEDED_GAP_CUSTODIANS,
    ConnectionOverrideRule,
    CustodianRow,
    build_connection_matches,
    normalize_text,
    slugify,
)


def make_custodian(name: str, connections: str = "") -> CustodianRow:
    return CustodianRow(
        custodian_id=f"custodian:{slugify(name)}",
        name=name,
        row={"Connections to Other Custodians": connections},
    )


def make_rule(pattern: str, action: str, target_id: str = "", source_id: str = "") -> ConnectionOverrideRule:
    return ConnectionOverrideRule(
        source_custodian_id=source_id,
        pattern=pattern,
        pattern_norm=normalize_text(pattern),
        action=action,
        target_custodian_id=target_id,
        notes="",
    )


def aliases_for(custodians: list[CustodianRow], extra: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    out = {c.custodian_id: {c.name} for c in custodians}
    for cid, names in (extra or {}).items():
        out[cid] |= names
    return out


BETA = "Beta Data Institute"
BETA_ID = f"custodian:{slugify(BETA)}"


def run(connections: str, overrides=None, extra_aliases=None, targets=(BETA,)):
    custodians = [make_custodian("Alpha Health Agency", connections)]
    custodians += [make_custodian(t) for t in targets]
    return build_connection_matches(custodians, aliases_for(custodians, extra_aliases), overrides or [])


ALPHA_ID = "custodian:alpha-health-agency"


def test_fuzzy_accept_threshold_constant():
    assert FUZZY_ACCEPT_THRESHOLD == 0.90


class TestExactAndLeadingMatches:
    def test_exact_name_inside_segment_is_accepted(self):
        accepted, review, gaps = run("Works closely with Beta Data Institute on projects")
        assert len(accepted) == 1
        edge = accepted[0]
        assert edge["sourceId"] == ALPHA_ID
        assert edge["targetId"] == BETA_ID
        assert edge["matchType"] == "name_exact"
        assert edge["score"] == 1.0
        assert [r["status"] for r in review] == ["accepted"]
        assert review[0]["candidateCustodian"] == BETA
        # gaps always contain the seeded VCCC entry
        assert gaps == SEEDED_GAP_CUSTODIANS

    def test_leading_name_match_scores_above_exact(self):
        accepted, review, _ = run("Beta Data Institute (linkage partner)")
        assert accepted[0]["matchType"] == "name_leading"
        assert accepted[0]["score"] == 1.02
        assert review[0]["status"] == "accepted"

    def test_accepted_edges_deduped_by_pair_keeping_highest_score(self):
        accepted, review, _ = run(
            "Beta Data Institute (primary); Collaboration with Beta Data Institute ongoing"
        )
        assert len(accepted) == 1
        assert accepted[0]["score"] == 1.02
        assert accepted[0]["matchType"] == "name_leading"
        # but both segments produced review entries
        assert [r["status"] for r in review] == ["accepted", "accepted"]


class TestFuzzyMatching:
    def test_fuzzy_at_exactly_threshold_is_accepted(self):
        # similarity("abcdefghijklmnopqrxy", "abcdefghijklmnopqrst") == 2*18/40 == 0.90
        accepted, review, _ = run("abcdefghijklmnopqrxy", targets=("abcdefghijklmnopqrst",))
        assert len(accepted) == 1
        assert accepted[0]["matchType"] == "fuzzy"
        assert accepted[0]["score"] == 0.9
        assert review[0]["status"] == "accepted"

    def test_fuzzy_below_threshold_is_rejected_not_reviewed(self):
        accepted, review, _ = run("Zzz Unrelated Entity")
        assert accepted == []
        assert len(review) == 1
        assert review[0]["matchType"] == "fuzzy"
        assert review[0]["status"] == "rejected"
        assert review[0]["score"] < FUZZY_ACCEPT_THRESHOLD

    def test_ambiguous_fuzzy_tie_is_rejected_even_above_threshold(self):
        accepted, review, _ = run(
            "Data Linkage Unit Alphx",
            targets=("Data Linkage Unit Alpha", "Data Linkage Unit Alphb"),
        )
        assert accepted == []
        assert len(review) == 1
        assert review[0]["matchType"] == "fuzzy"
        assert review[0]["status"] == "rejected"
        assert review[0]["score"] >= FUZZY_ACCEPT_THRESHOLD

    def test_short_acronym_alias_goes_to_review(self):
        accepted, review, _ = run(
            "Linked with BDI partners",
            extra_aliases={BETA_ID: {"BDI"}},
        )
        assert accepted == []
        assert len(review) == 1
        assert review[0]["matchType"] == "alias_short"
        assert review[0]["status"] == "review_required"
        assert review[0]["score"] == 0.86
        assert review[0]["targetId"] == BETA_ID


class TestOverrideRules:
    def test_force_accept_creates_edge_without_fuzzy_matching(self):
        rule = make_rule("national registry partners", "force_accept", target_id=BETA_ID)
        accepted, review, _ = run("Shares data with the national registry partners", overrides=[rule])
        assert len(accepted) == 1
        assert accepted[0]["matchType"] == "override_force_accept"
        assert accepted[0]["score"] == 1.0
        assert accepted[0]["targetId"] == BETA_ID
        assert len(review) == 1
        assert review[0]["matchType"] == "override_force_accept"
        assert review[0]["status"] == "accepted"
        assert review[0]["candidateCustodian"] == BETA

    def test_force_reject_wins_even_over_exact_name_match(self):
        rule = make_rule("beta data institute", "force_reject")
        accepted, review, _ = run("Beta Data Institute collaboration", overrides=[rule])
        assert accepted == []
        assert len(review) == 1
        assert review[0]["matchType"] == "override_force_reject"
        assert review[0]["status"] == "rejected"

    def test_review_only_suppresses_exact_match_acceptance(self):
        rule = make_rule("beta data institute", "review_only", target_id=BETA_ID)
        accepted, review, _ = run("Works with Beta Data Institute", overrides=[rule])
        assert accepted == []
        assert len(review) == 1
        assert review[0]["matchType"] == "override_review_only"
        assert review[0]["status"] == "review_required"
        assert review[0]["candidateCustodian"] == BETA
        assert review[0]["score"] == 0.0

    def test_rule_scoped_to_other_source_is_ignored(self):
        rule = make_rule("beta data institute", "force_reject", source_id="custodian:someone-else")
        accepted, review, _ = run("Beta Data Institute collaboration", overrides=[rule])
        # The scoped rule does not apply, so normal matching accepts the name.
        assert len(accepted) == 1
        assert accepted[0]["matchType"] == "name_exact"


class TestPatternRejections:
    def test_not_a_custodian_pattern_rejects_segment(self):
        accepted, review, _ = run("University of Sydney research collaboration")
        assert accepted == []
        assert review[0]["matchType"] == "not_a_custodian"
        assert review[0]["status"] == "rejected"

    def test_not_a_custodian_check_precedes_overrides(self):
        # Pin current behavior: NOT_A_CUSTODIAN/STRUCTURAL_NOTE pattern checks
        # run BEFORE override rules, so a force_accept override cannot rescue
        # a segment that hits one of those patterns.
        rule = make_rule("university of sydney", "force_accept", target_id=BETA_ID)
        accepted, review, _ = run("University of Sydney research collaboration", overrides=[rule])
        assert accepted == []
        assert review[0]["matchType"] == "not_a_custodian"

    def test_structural_note_pattern_rejects_segment(self):
        accepted, review, _ = run("Other data custodians as required")
        assert accepted == []
        assert review[0]["matchType"] == "structural_note"
        assert review[0]["status"] == "rejected"

    def test_verify_with_custodian_is_a_structural_note(self):
        # "verify with custodian" appears in STRUCTURAL_NOTE_PATTERNS, so such
        # segments are rejected before the dedicated verify-placeholder logic
        # in the matching loop is ever reached.
        accepted, review, _ = run("Beta Data Institute (verify with custodian)")
        assert accepted == []
        assert review[0]["matchType"] == "structural_note"


class TestSegmentationAndGaps:
    def test_segments_split_on_semicolons_and_trailing_dots_stripped(self):
        accepted, review, _ = run("Beta Data Institute; University partners.")
        assert len(accepted) == 1
        assert {r["matchType"] for r in review} == {"name_leading", "not_a_custodian"}
        assert any(r["segment"] == "University partners" for r in review)

    def test_gap_entity_recorded_and_deduped(self):
        accepted, review, gaps = run(
            "VCCC Data Connect partnership; Victorian Comprehensive Cancer Centre program"
        )
        assert accepted == []
        assert all(r["matchType"] == "gap_custodian" and r["status"] == "rejected" for r in review)
        # seeded gap + one deduped gap for this source
        assert len(gaps) == 2
        added = [g for g in gaps if g["sourceId"] == ALPHA_ID]
        assert len(added) == 1
        assert added[0]["gapName"] == "Victorian Comprehensive Cancer Centre (VCCC) Data Connect"

    def test_no_connections_yields_only_seeded_gaps(self):
        custodians = [make_custodian("Alpha Health Agency")]
        accepted, review, gaps = build_connection_matches(custodians, aliases_for(custodians), [])
        assert accepted == []
        assert review == []
        assert gaps == SEEDED_GAP_CUSTODIANS
