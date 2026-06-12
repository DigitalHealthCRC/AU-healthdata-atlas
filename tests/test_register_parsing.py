"""Regression tests for scripts/register_parsing.py.

These pin CURRENT behavior (including a few known-noisy quirks, called out
inline) - they are not aspirational.
"""

import pytest

from register_parsing import (
    MOJIBAKE_EM_DASH,
    MOJIBAKE_EN_DASH,
    build_step_record,
    dedupe_datasets,
    extract_aliases,
    extract_md_cards,
    extract_register_metadata,
    extract_subject_short,
    infer_step_timeline,
    load_connection_overrides,
    looks_like_placeholder,
    normalize_custodian_type_name,
    normalize_text,
    parse_csv_datasets,
    parse_md_dataset_rows,
    parse_pathway_steps,
    parse_urls,
    replace_dash_variants,
    similarity,
    slugify,
    split_delimited,
)


# ---------------------------------------------------------------------------
# parse_pathway_steps
# ---------------------------------------------------------------------------


class TestParsePathwaySteps:
    def test_numbered_steps_with_hyphen_separators(self):
        text = (
            "1. Submit application - Researcher - Online portal - 2-4 weeks\n"
            "2. Ethics review - HREC - Committee meeting - 4-8 weeks\n"
            "3. Data extraction and delivery - Custodian - Secure transfer - 2-6 weeks"
        )
        steps = parse_pathway_steps(text)
        assert [s["number"] for s in steps] == [1, 2, 3]
        assert steps[0] == {
            "number": 1,
            "text": "Submit application",
            "actor": "Researcher",
            "channel": "Online portal",
            "timeline": "2-4 weeks",
            "lane": "Researcher",
        }
        assert steps[1]["actor"] == "HREC"
        assert steps[1]["lane"] == "EthicsRegulatory"
        assert steps[2]["lane"] == "Custodian"
        assert steps[2]["timeline"] == "2-6 weeks"

    @pytest.mark.parametrize("dash", ["–", "—", MOJIBAKE_EN_DASH, MOJIBAKE_EM_DASH])
    def test_dash_variants_split_into_fields(self, dash):
        text = f"1. Submit application {dash} Researcher {dash} Portal {dash} 1-2 weeks"
        steps = parse_pathway_steps(text)
        assert len(steps) == 1
        assert steps[0]["text"] == "Submit application"
        assert steps[0]["actor"] == "Researcher"
        assert steps[0]["channel"] == "Portal"
        assert steps[0]["timeline"] == "1-2 weeks"

    def test_two_part_line_gets_actor_and_inferred_timeline(self):
        steps = parse_pathway_steps("1. Submit application - Researcher")
        assert len(steps) == 1
        assert steps[0]["actor"] == "Researcher"
        assert steps[0]["channel"] == ""
        # No explicit timeline -> inferred from the "submit/application" terms.
        assert steps[0]["timeline"] == "1-4 weeks"

    def test_three_part_line_has_no_timeline_field(self):
        steps = parse_pathway_steps("1. Initial inquiry - Researcher - Email")
        assert steps[0]["channel"] == "Email"
        # inferred: "initial inquiry" bucket
        assert steps[0]["timeline"] == "1-2 weeks"

    def test_extra_dash_separated_parts_are_joined_into_timeline(self):
        steps = parse_pathway_steps("1. Apply now - Researcher - Portal - 2-4 weeks - subject to review")
        assert steps[0]["timeline"] == "2-4 weeks - subject to review"

    def test_compact_step_n_pipe_format_fallback(self):
        # This is the ACSQHC-style format that the old audit failed to parse.
        text = (
            "Step 1: Check publicly available data | Actor: Researcher | "
            "Form/Portal: ACSQHC website | Duration: 1-2 weeks "
            "Step 2: Submit enquiry | Actor: Researcher | Form/Portal: Email form | Duration: 2-4 weeks"
        )
        steps = parse_pathway_steps(text)
        assert [s["number"] for s in steps] == [1, 2]
        assert steps[0]["text"] == "Check publicly available data"
        assert steps[0]["actor"] == "Researcher"
        assert steps[0]["channel"] == "ACSQHC website"
        assert steps[0]["timeline"] == "1-2 weeks"
        assert steps[0]["lane"] == "Researcher"
        assert steps[1]["text"] == "Submit enquiry"
        assert steps[1]["channel"] == "Email form"
        assert steps[1]["timeline"] == "2-4 weeks"

    def test_compact_format_without_duration_infers_timeline(self):
        steps = parse_pathway_steps("Step 1: Submit application | Actor: Researcher")
        assert len(steps) == 1
        assert steps[0]["actor"] == "Researcher"
        assert steps[0]["timeline"] == "1-4 weeks"

    def test_empty_and_garbage_input(self):
        assert parse_pathway_steps("") == []
        assert parse_pathway_steps("No structured steps documented here.") == []

    def test_non_numbered_lines_are_ignored(self):
        steps = parse_pathway_steps("Notes about the process:\n1. Apply - Researcher - Portal - 1-2 weeks")
        assert len(steps) == 1
        assert steps[0]["number"] == 1


class TestLaneAssignment:
    def test_researcher_keyword_wins_over_ethics_keywords(self):
        record = build_step_record(1, "Researcher obtains HREC approval")
        assert record["lane"] == "Researcher"

    def test_applicant_maps_to_researcher_lane(self):
        record = build_step_record(1, "Applicant lodges request")
        assert record["lane"] == "Researcher"

    def test_approval_keyword_maps_to_ethics_lane_even_for_custodian_actor(self):
        # Pin current behavior: "approval" in the text trumps the Custodian actor.
        record = build_step_record(1, "Final approval of data extract", actor="Custodian")
        assert record["lane"] == "EthicsRegulatory"

    def test_default_lane_is_custodian(self):
        record = build_step_record(1, "Data extract prepared and supplied", actor="Data custodian")
        assert record["lane"] == "Custodian"


# ---------------------------------------------------------------------------
# extract_aliases
# ---------------------------------------------------------------------------


class TestExtractAliases:
    def test_acronym_and_parenthetical_extraction(self):
        aliases = extract_aliases("Therapeutic Goods Administration (TGA)", "", "")
        assert aliases == {"Therapeutic Goods Administration (TGA)", "TGA"}

    def test_subject_short_and_title_are_included(self):
        aliases = extract_aliases("Foo Agency", "Foo Bar (FB)", "Foo Title")
        assert {"Foo Agency", "Foo Bar", "FB", "Foo Title"} <= aliases

    def test_generic_state_acronyms_excluded_from_caps_token_scan(self):
        assert extract_aliases("ACT Health", "", "") == {"ACT Health"}

    def test_state_acronym_still_leaks_in_via_parenthetical_branch(self):
        # Pin current behavior (known-noisy): the GENERIC_ACRONYM_ALIASES
        # exclusion only applies to the bare-caps-token scan, NOT to the
        # parenthetical extraction, so "(NSW)" still becomes an alias.
        aliases = extract_aliases("Cancer Council (NSW)", "", "")
        assert aliases == {"Cancer Council (NSW)", "NSW"}

    def test_extra_aliases_by_name_are_merged(self):
        aliases = extract_aliases("Australian Bureau of Statistics", "", "")
        assert aliases == {"Australian Bureau of Statistics", "ABS"}

    def test_long_parentheticals_over_40_chars_are_ignored(self):
        aliases = extract_aliases(
            "Shortname (An Extremely Long Parenthetical Expansion Of The Name)", "", ""
        )
        assert "An Extremely Long Parenthetical Expansion Of The Name" not in aliases


# ---------------------------------------------------------------------------
# parse_csv_datasets
# ---------------------------------------------------------------------------


class TestParseCsvDatasets:
    def test_pipe_format(self):
        text = "NDDA|National drug data|Yes|Yes (via AIHW); APC|Admitted patient care|Yes|Yes"
        out = parse_csv_datasets(text)
        assert out == [
            {
                "name": "NDDA",
                "description": "National drug data",
                "identifiable": "Yes",
                "linkable": "Yes (via AIHW)",
                "source": "csv",
            },
            {
                "name": "APC",
                "description": "Admitted patient care",
                "identifiable": "Yes",
                "linkable": "Yes",
                "source": "csv",
            },
        ]

    def test_pipe_format_with_newline_separators(self):
        out = parse_csv_datasets("Alpha Set|First|Yes|No\nBeta Set|Second|No|No")
        assert [d["name"] for d in out] == ["Alpha Set", "Beta Set"]
        assert out[0]["linkable"] == "No"

    def test_parenthetical_fallback(self):
        out = parse_csv_datasets("Dataset A (first description), Dataset B (second description)")
        assert out == [
            {"name": "Dataset A", "description": "first description", "identifiable": "", "linkable": "", "source": "csv"},
            {"name": "Dataset B", "description": "second description", "identifiable": "", "linkable": "", "source": "csv"},
        ]

    def test_plain_comma_fallback_splits_before_capitals(self):
        out = parse_csv_datasets("NDDA, APC Data, Mortality Register")
        assert [d["name"] for d in out] == ["NDDA", "APC Data", "Mortality Register"]
        assert all(d["description"] == "" for d in out)

    def test_empty_input(self):
        assert parse_csv_datasets("") == []


# ---------------------------------------------------------------------------
# parse_md_dataset_rows / extract_md_cards / extract_register_metadata
# ---------------------------------------------------------------------------


class TestParseMdDatasetRows:
    def test_parses_table_rows(self):
        card = "\n".join(
            [
                "Some intro",
                "| Dataset Name | Description | Identifiable? | Linkable? |",
                "|---|---|---|---|",
                "| NDDA | National drug data | Yes | Yes (via AIHW) |",
                "| Partial | only three |",
                "| APC | Admitted patient care | Yes | Yes |",
                "",
                "After the table",
            ]
        )
        rows = parse_md_dataset_rows(card)
        assert [r["name"] for r in rows] == ["NDDA", "APC"]
        assert rows[0] == {
            "name": "NDDA",
            "description": "National drug data",
            "identifiable": "Yes",
            "linkable": "Yes (via AIHW)",
            "source": "md",
        }

    def test_no_table_returns_empty(self):
        assert parse_md_dataset_rows("No table in this card at all.") == []


class TestExtractMdCards:
    def test_current_format_requires_full_name_row(self):
        md = "\n".join(
            [
                "# Register Title",
                "",
                "Intro text.",
                "",
                "## Australian Institute of Health and Welfare",
                "| Field | Value |",
                "|---|---|",
                "| **Full Name** | Australian Institute of Health and Welfare |",
                "Card body A.",
                "",
                "## Methodology",
                "Not a custodian card.",
                "",
                "## Cancer Institute NSW",
                "| **Full Name** | Cancer Institute NSW |",
                "Card body B.",
            ]
        )
        cards = extract_md_cards(md)
        assert [title for title, _ in cards] == [
            "Australian Institute of Health and Welfare",
            "Cancer Institute NSW",
        ]
        assert "Card body A." in cards[0][1]

    def test_legacy_pathway_card_format(self):
        md = "\n".join(
            [
                "## Pathway Card: AIHW",
                "",
                "Body A text.",
                "",
                "## Pathway Card: ABS",
                "",
                "Body B text.",
            ]
        )
        cards = extract_md_cards(md)
        assert cards == [("AIHW", "Body A text."), ("ABS", "Body B text.")]

    def test_empty_text(self):
        assert extract_md_cards("") == []


class TestExtractRegisterMetadata:
    def test_extracts_title_version_generated_and_count(self):
        md = "\n".join(
            [
                "# AU Health Data Pathway Register - Version 1.4",
                "",
                "**Generated:** 2026-05-30",
                "**Custodians documented:** 58",
            ]
        )
        meta = extract_register_metadata(md)
        assert meta == {
            "sourceRegisterTitle": "AU Health Data Pathway Register - Version 1.4",
            "sourceRegisterVersion": "1.4",
            "sourceRegisterGenerated": "2026-05-30",
            "sourceRegisterCustodianCount": "58",
        }

    def test_missing_fields_are_empty_strings(self):
        meta = extract_register_metadata("plain text, no headings")
        assert meta == {
            "sourceRegisterTitle": "",
            "sourceRegisterVersion": "",
            "sourceRegisterGenerated": "",
            "sourceRegisterCustodianCount": "",
        }


# ---------------------------------------------------------------------------
# Small text utilities
# ---------------------------------------------------------------------------


class TestParseUrls:
    def test_dedup_and_sort(self):
        text = "Intro https://example.org/b text (https://example.org/a) and https://example.org/b"
        assert parse_urls(text) == ["https://example.org/a", "https://example.org/b"]

    def test_closing_paren_terminates_token_but_trailing_dot_is_kept(self):
        # Pin current behavior: the [^\s)]+ tokenization stops at ')' but
        # keeps trailing sentence punctuation like '.'.
        assert parse_urls("See https://example.org/page.") == ["https://example.org/page."]

    def test_empty(self):
        assert parse_urls("") == []


class TestSplitDelimited:
    def test_splits_on_semicolon_comma_and_spaced_slash(self):
        assert split_delimited("Commonwealth; State - NSW, Territory / Other") == [
            "Commonwealth",
            "State - NSW",
            "Territory",
            "Other",
        ]

    def test_unspaced_slash_is_not_split(self):
        assert split_delimited("NHMRC/HRECs") == ["NHMRC/HRECs"]

    def test_empty(self):
        assert split_delimited("") == []


class TestNormalizeTextAndSlugify:
    def test_replace_dash_variants(self):
        assert replace_dash_variants("x – y — z") == "x - y - z"
        assert replace_dash_variants(f"a{MOJIBAKE_EN_DASH}b{MOJIBAKE_EM_DASH}c") == "a-b-c"

    def test_normalize_text_folds_dashes_accents_and_punctuation(self):
        assert normalize_text("Café—Data") == "cafe data"
        assert normalize_text("  A&B  (C) ") == "a b c"
        assert normalize_text(f"A{MOJIBAKE_EN_DASH}B") == "a b"

    def test_slugify(self):
        assert slugify("AIHW – Data Linkage!") == "aihw-data-linkage"

    def test_similarity_uses_normalized_text(self):
        assert similarity("AIHW", "aihw") == 1.0
        assert similarity("abc", "xyz") == 0.0


class TestExtractSubjectShort:
    def test_strips_parenthetical(self):
        assert extract_subject_short("Department of Health (DoH)") == "Department of Health"

    def test_plain_and_empty(self):
        assert extract_subject_short("Plain Subject") == "Plain Subject"
        assert extract_subject_short("") == ""


class TestLooksLikePlaceholder:
    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "Verify with custodian",
            "N/A",
            "Not specified",
            "To be verified",
            "Not applicable",
            "Timeline varies",
            "Varies by project",
            "As agreed",
        ],
    )
    def test_placeholders(self, value):
        assert looks_like_placeholder(value) is True

    @pytest.mark.parametrize("value", ["2-4 weeks", "Approximately 6 months", "Submit form"])
    def test_real_values(self, value):
        assert looks_like_placeholder(value) is False

    def test_known_noisy_n_a_substring_match(self):
        # Pin current behavior (known-noisy): the "n a" placeholder term is a
        # plain substring check against normalized text, so any phrase whose
        # normalization contains "n a" (e.g. "Plan ahead" -> "plan ahead")
        # is treated as a placeholder.
        assert looks_like_placeholder("Plan ahead") is True


class TestNormalizeCustodianTypeName:
    def test_uppercases_state_suffix(self):
        assert normalize_custodian_type_name("State - nsw") == "State - NSW"
        assert normalize_custodian_type_name("State-nsw") == "State - NSW"

    def test_dash_variant_folded_first(self):
        assert normalize_custodian_type_name("State – vic") == "State - VIC"

    def test_whitespace_collapse(self):
        assert normalize_custodian_type_name("  Commonwealth   Agency ") == "Commonwealth Agency"


class TestDedupeDatasets:
    def test_merges_by_normalized_name_and_fills_missing_fields(self):
        datasets = [
            {"name": "NDDA", "description": "", "identifiable": "Yes", "linkable": ""},
            {"name": "ndda", "description": "Drug data", "identifiable": "No", "linkable": "Yes"},
            {"name": "", "description": "skipped - no name"},
        ]
        out = dedupe_datasets(datasets)
        assert len(out) == 1
        merged = out[0]
        # First occurrence wins; later duplicates only fill empty fields.
        assert merged["name"] == "NDDA"
        assert merged["identifiable"] == "Yes"
        assert merged["description"] == "Drug data"
        assert merged["linkable"] == "Yes"


class TestInferStepTimeline:
    def test_explicit_timeline_wins(self):
        assert infer_step_timeline("anything", "", "", " 6 weeks ") == "6 weeks"

    def test_placeholder_timeline_is_replaced(self):
        assert infer_step_timeline("Data linkage project", "", "", "Verify with custodian") == "3-6 months"

    def test_keyword_buckets(self):
        assert infer_step_timeline("Data linkage application", "", "", "") == "3-6 months"
        assert infer_step_timeline("Obtain HREC clearance", "", "", "") == "4-12 weeks"
        assert infer_step_timeline("Submit application", "", "", "") == "1-4 weeks"
        assert infer_step_timeline("Initial inquiry", "", "", "") == "1-2 weeks"

    def test_review_bucket_outranks_submit_bucket(self):
        # Pin current behavior: the decision/approval/review bucket is checked
        # BEFORE the submit/application bucket, so "Submit application for
        # review" lands on 2-8 weeks rather than 1-4 weeks.
        assert infer_step_timeline("Submit application for review", "", "", "") == "2-8 weeks"

    def test_default_bucket(self):
        assert infer_step_timeline("Mystery step", "", "", "") == "2-8 weeks"


# ---------------------------------------------------------------------------
# load_connection_overrides
# ---------------------------------------------------------------------------


class TestLoadConnectionOverrides:
    def test_loads_valid_rules_and_skips_invalid(self, tmp_path):
        path = tmp_path / "overrides.csv"
        path.write_text(
            "source_custodian_id,pattern,action,target_custodian_id,notes\n"
            "custodian:a,beta institute,force_accept,custodian:b,note1\n"
            ",gamma,force_reject,,note2\n"
            "custodian:a,delta,bogus_action,custodian:d,skipped-bad-action\n"
            "custodian:a,,force_accept,custodian:d,skipped-empty-pattern\n"
            "custodian:a,Epsilon Data,review_only,,note3\n",
            encoding="utf-8",
        )
        rules = load_connection_overrides(path)
        assert [r.action for r in rules] == ["force_accept", "force_reject", "review_only"]
        first = rules[0]
        assert first.source_custodian_id == "custodian:a"
        assert first.pattern == "beta institute"
        assert first.pattern_norm == "beta institute"
        assert first.target_custodian_id == "custodian:b"
        assert first.notes == "note1"
        # pattern_norm is the normalized form of the pattern text
        assert rules[2].pattern_norm == "epsilon data"
        assert rules[1].source_custodian_id == ""

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_connection_overrides(tmp_path / "nope.csv") == []
