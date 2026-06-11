# KG Generation — Iteration 2 Remediation Prompt
**For:** OpenAI Codex / GPT-4o code generation
**Context:** Australian Health Data Access Knowledge Graph (654 nodes, 846 relationships)
**Prepared from:** Automated accuracy assessment of `kg_exports/20260302_100851` + analysis of `connection_match_review.csv`

---

## Background for the Model

You are improving the second iteration of an Australian health data access knowledge graph. The graph was generated from web-researched pathway cards for 32 health data custodians. A fuzzy matching pipeline was run to extract `CONNECTED_TO` relationships between custodians. The analysis below identifies all detected issues — some are addressed by the matching pipeline, some are upstream LLM extraction problems, and some are data normalisation bugs. Your task is to fix all of them in the next generation pass.

---

## ISSUE GROUP A — Connection Matching Failures (Fuzzy Pipeline Scope)

These issues were *attempted* by the fuzzy matching pipeline but remain unresolved. The `connection_match_review.csv` file contains 15 `review_required` entries and 7 `override_force_reject` entries that were not converted to accepted `CONNECTED_TO` edges.

---

### A1 — Six custodians remain isolated (zero accepted CONNECTED_TO edges)

The following custodians have no accepted inter-custodian connections in the graph despite all being meaningfully connected to other custodians in the Australian health data ecosystem. The fuzzy pipeline attempted extraction for each but failed due to vague source text, wrong candidate proposals, or force-rejection of placeholder segments.

**Required fix:** During the LLM extraction pass for each custodian's "Connections to Other Custodians" field, the prompt must explicitly instruct the model to enumerate *specific named custodians* from the known custodian list (provided as context) rather than accepting generic phrases like "other data custodians" or "state and federal data custodians". If the source text is vague, the model must infer connections from the custodian's known operational role and dataset holdings.

**Correct connections to add for each isolated custodian:**

| Custodian | Missing connections (ground truth) | Basis |
|---|---|---|
| **TGA** | Services Australia (PBS adverse event linkage), AIHW (therapeutic goods reporting), Department of Health and Aged Care (regulatory policy) | TGA holds the Database of Adverse Event Notifications (DAEN) and the ARTG; PBS data for pharmacovigilance comes via Services Australia |
| **Queensland Health** | AIHW (national hospital data reporting), QCIF (HPC/data infrastructure), PHRN (data linkage), Cancer Institute NSW (cross-state cancer registry comparisons) | Queensland Health operates the Statistical Analysis and Linkage Unit (SALUD/DLQ); the review file shows a `review_required` entry with score 0.51 for "Statistical Analysis and Linkage Unit (Data Linkage Queensland)" — this should be accepted as a connection to PHRN, not SA Health |
| **QCIF** | Queensland Health (HPC infrastructure for QH data), PHRN (national linkage network), SURE (TRE infrastructure peer) | QCIF provides the Wiener HPC facility used by Queensland Health researchers; the AAF and "state/federal custodians" segments were correctly force-rejected as non-custodian entities |
| **ABS DataLab** | AIHW (linked data projects via AIHW Data Integration Services), Services Australia (MBS/PBS/Centrelink linkage), PHRN (national data linkage), Department of Health and Aged Care | ABS DataLab is the secure environment for ABS microdata; it regularly hosts linked projects with AIHW and Services Australia data |
| **MedicineInsight (NPS MedicineWise)** | NHMRC / HRECs (ethics approval for research use), Department of Health and Aged Care (primary care policy reporting), PHN Cooperative (PHN-level data aggregation), Services Australia (MBS/PBS cross-reference) | MedicineInsight is a GP practice data network; all research use requires HREC approval; data is used for DoH primary care policy |
| **ARDC** | AIHW (Health Data Australia catalogue includes AIHW collections), ABS (ABS datasets discoverable via HeSANDA), NHMRC (research data management policy alignment) | ARDC's Health Data Australia (HeSANDA) portal catalogues datasets from AIHW, ABS, and NHMRC-funded projects; the fuzzy pipeline incorrectly proposed WA Health as the candidate |

---

### A2 — Fifteen review_required entries need resolution

The following `review_required` entries from `connection_match_review.csv` must be resolved in the next iteration. For each, the correct action is specified:

| Source custodian | Segment text | Fuzzy candidate proposed | Score | Correct action |
|---|---|---|---|---|
| Victorian Cancer Registry | "Family Cancer Centres — to assess cancer risk" | Cancer Institute NSW | 0.48 | **Reject** — Family Cancer Centres are clinical services, not a custodian in this graph |
| Victorian Cancer Registry | "Department of Health and Human Services (Victoria)" | Dept of Health and Aged Care | 0.63 | **Reject and remap** — this refers to VAHI/Victorian DoH, not the Commonwealth DoH; add connection to VAHI instead |
| Victorian Cancer Registry | "Victorian Comprehensive Cancer Centre (VCCC) Data Connect" | NACCHO | 0.48 | **Reject** — VCCC is not in the custodian list; note as a gap for future inclusion |
| Queensland Health | "Statistical Analysis and Linkage Unit (Data Linkage Queensland, DLQ)" | SA Health / SA NT DataLink | 0.51 | **Reject candidate, accept connection to PHRN** — DLQ is Queensland's data linkage unit, a PHRN member; correct target is PHRN |
| WA Health | "Department of Transport, Main Roads WA, Insurance Commission of WA" | Tasmanian DoH | 0.47 | **Reject** — these are non-health administrative data providers, not custodians in this graph |
| SA Health / SA NT DataLink | "Australian Government data custodians (for MBS, PBS, Centrelink, Aged Care, NDIS)" | Services Australia | 0.86 | **Accept** — score 0.86 is sufficient; Services Australia holds MBS/PBS/Centrelink data |
| NHMRC / HRECs | "Research institutions/universities — HRECs are often affiliated with these institutions" | Cancer Institute NSW | 0.37 | **Reject** — universities are not custodians in this graph; this is a structural note, not a custodian connection |
| NHMRC / HRECs | "Funding bodies — May require HREC approval as a condition of funding" | NT Health | 0.34 | **Reject** — this is a generic statement about HREC requirements, not a specific custodian connection |
| AIATSIS | "Other Indigenous community organisations and research bodies" | NHMRC / HRECs | 0.45 | **Reject candidate, accept connection to NACCHO** — the correct connection is NACCHO, which represents ACCHOs; AIATSIS and NACCHO have a formal data governance relationship |
| NACCHO | "State and Territory Health Departments (for linked data, policy alignment)" | Tasmanian DoH | 0.48 | **Reject candidate, add multiple connections** — this segment implies connections to all state health departments; add connections to NSW Health, VAHI, Queensland Health, WA Health, SA Health, ACT Health, NT Health, Tasmanian DoH |
| NACCHO | "Other ACCHOs (for multi-site studies or aggregated data)" | CHeReL | 0.43 | **Reject** — "other ACCHOs" refers to NACCHO member organisations, not a specific custodian; this is an internal network reference |
| ARDC | "Data providers (universities, medical research institutes, clinical trials networks)" | WA Health | 0.40 | **Reject** — these are data contributors to HeSANDA, not custodians in this graph |
| AIHW | "Department of Social Services (DSS) for DOMINO data" | (force_rejected) | 0.0 | **Add DSS as a new custodian node** OR **add a note to AIHW's pathway card** that DSS is an upstream data provider for DOMINO; DSS is a legitimate Commonwealth data custodian not currently in the graph |
| Cancer Institute NSW | "Not explicitly stated, but potential connections with other NSW Health entities" | (force_rejected) | 0.0 | **Add connection to NSW Health — Ministry of Health NSW** — Cancer Institute NSW is a statutory body under NSW Health; add this connection explicitly |
| TGA | "(verify with custodian)" | (force_rejected) | 0.0 | **Remove this review entry** — the source text was a placeholder; connections should be inferred from TGA's known role (see A1 above) |

---

### A3 — Fuzzy matching threshold and candidate selection improvements

The pipeline is proposing geographically or alphabetically proximate custodians as fuzzy candidates when the segment text refers to a different entity. Specific improvements needed:

1. **Raise the acceptance threshold from the apparent ~0.85 to 0.90** for fuzzy matches. The accepted `CONNECTED_TO` edges all score ≥ 0.96, but several `review_required` entries at 0.51–0.63 are being proposed with wrong candidates. A higher threshold would prevent these false positives from entering the review queue.

2. **Add a custodian alias dictionary** to the matching pipeline. Several failures occur because the segment text uses an informal name or abbreviation not in the custodian's primary name field. Required aliases to add:
   - "Data Linkage Queensland" / "DLQ" / "SALUD" → Queensland Health
   - "Dataplace" → AIHW Data Integration Services
   - "HeSANDA" → ARDC
   - "DOMINO" → Department of Social Services (new node) or AIHW
   - "VCCC Data Connect" → (not in graph — flag as gap)
   - "AAF" / "Australian Access Federation" → (not a custodian — always reject)
   - "Department of Health and Human Services Victoria" → VAHI

3. **Add a `NOT_A_CUSTODIAN` rejection list** to the pipeline for entities that appear in connection text but should never be matched to a custodian node: universities, research institutes, clinical networks, AAF, funding bodies, insurance commissions, transport departments.

---

## ISSUE GROUP B — LLM Extraction Quality (Upstream of Matching Pipeline)

These issues exist in the node content generated during the initial LLM extraction pass and are not addressed by the fuzzy matching pipeline.

---

### B1 — Timeline fields: 75.6% contain placeholders (CRITICAL)

**Observed:** 136 of 180 `PathwayStep` nodes have `timeline = "(verify with custodian)"` instead of a real duration estimate.

**Root cause:** The extraction prompt did not provide sufficient guidance on how to handle missing timeline data, defaulting to a placeholder instead of making a reasoned estimate from available evidence.

**Required fix for the extraction prompt:** Add the following instruction to the PathwayStep extraction section:

> "For the `timeline` field, provide the best available estimate based on: (1) explicit statements in the source text, (2) comparable steps at similar Australian government agencies, or (3) general knowledge of Australian government administrative processes. Use ranges where appropriate (e.g., '2–4 weeks', '3–6 months'). Only use '(verify with custodian)' if the step is genuinely unique with no comparable reference point. Do NOT default to '(verify with custodian)' for standard steps such as ethics review, data access decision, or data provision."

**Reference timelines to embed in the prompt as defaults** (based on accepted evidence from the 44 steps that do have real timelines):

| Step type | Default timeline if not specified |
|---|---|
| Initial inquiry / expression of interest | 1–2 weeks |
| Application / form submission | 1–4 weeks |
| HREC / ethics review (standard) | 4–12 weeks (quarterly meetings common) |
| HREC / ethics review (expedited) | 2–4 weeks |
| Data custodian access decision | 2–8 weeks |
| Data preparation and provision | 2–12 weeks |
| TRE onboarding / account setup | 1–2 weeks |
| Data linkage (PHRN/CHeReL) | 3–6 months |
| Full end-to-end (simple request) | 3–6 months |
| Full end-to-end (complex linked data) | 12–24 months |

---

### B2 — Dataset `identifiable` and `linkable` fields: 40% empty

**Observed:** 72 of 180 Dataset nodes have empty `identifiable` and `linkable` fields. A further 26 `identifiable` and 23 `linkable` values contain "(verify with custodian)" rather than a classification.

**Required fix:** Add the following instruction to the Dataset node extraction section:

> "For `identifiable`, classify as one of: 'Yes', 'Yes (for linkage)', 'Yes (with justification)', 'Yes (indirectly)', 'No', 'No (de-identified)', 'De-identified (verify with custodian)'. Use the Five Safes framework as a guide: if the dataset contains names, Medicare numbers, addresses, or DOB, classify as 'Yes'. If the dataset is a published aggregate statistical table, classify as 'No'. Do NOT leave this field empty."
>
> "For `linkable`, classify as one of: 'Yes', 'Yes (via [linkage unit])', 'No', 'No (aggregate only)'. If the custodian is a member of PHRN or operates a data linkage unit, default to 'Yes (via [linkage unit name])' unless the source text explicitly states otherwise."

---

### B3 — NACCHO has zero Dataset nodes

**Observed:** NACCHO / Aboriginal Community Controlled Health Organisations has 0 `HAS_DATASET` relationships despite being a significant data governance body.

**Required fix:** Add the following datasets to NACCHO's node during extraction:

| Dataset name | Description | Identifiable | Linkable |
|---|---|---|---|
| NACCHO Member Organisation Health Data | Aggregated primary care data from ACCHO member services | Yes (de-identified for reporting) | Yes (via AIHW Data Integration Services) |
| QAIHC Health Data Collections | Queensland Aboriginal and Islander Health Council member data | Yes (de-identified) | Yes (verify with custodian) |
| AMSANT Health Data | Aboriginal Medical Services Alliance NT member data | Yes (de-identified) | Yes (verify with custodian) |
| Close the Gap data | National progress data on Indigenous health targets | No (aggregate) | No |

Additionally, update NACCHO's `primaryRole` to clarify it is both a **data governance body** (consent and ethics oversight for Indigenous health research) and an **indirect data custodian** (through its member ACCHOs). The current description understates the governance role.

---

## ISSUE GROUP C — Node Classification and Taxonomy Bugs

These are structural issues in how nodes are typed and classified.

---

### C1 — NSW CustodianType taxonomy duplication (BUG)

**Observed:** Two separate `CustodianType` nodes exist for NSW:
- `State — NSW` (with Unicode em-dash U+2014)
- `State - NSW` (with ASCII hyphen-minus U+002D)

This causes NSW custodians to be split across two type nodes, breaking any type-filtered Cypher query.

**Required fix:** Normalise all `CustodianType` node names to use a consistent separator. Use the format `State - {abbreviation}` (ASCII hyphen, spaces either side) for all state types. Apply a deduplication step after node creation that merges any type nodes with names that differ only in dash character. The Cypher fix for the existing graph is:

```cypher
MATCH (t:CustodianType)
SET t.name = replace(replace(t.name, '—', '-'), '–', '-')
WITH t
MATCH (t2:CustodianType)
WHERE t.name = t2.name AND id(t) <> id(t2)
MATCH (c:Custodian)-[r:HAS_TYPE]->(t2)
MERGE (c)-[:HAS_TYPE]->(t)
DELETE r, t2
```

---

### C2 — APRA misclassified as a research data custodian

**Observed:** APRA (Australian Prudential Regulation Authority) is included as a `Custodian` node at the same level as AIHW and Services Australia. APRA publishes **aggregate statistical tables** on private health insurance — it does not hold individual-level data accessible to researchers.

**Required fix:** Either:
- **(Preferred)** Add a new `CustodianType` node: `Statistical Publisher` and reclassify APRA under this type. Update APRA's pathway card to state explicitly: *"APRA does not accept data access applications. Its PHI statistics are published as aggregate tables available for free download. No application process is required."* Remove or simplify the pathway steps to a single step: "Download published statistics from APRA website."
- **(Alternative)** Remove APRA from the custodian list and add a note in the AIHW and Department of Health pathway cards that APRA PHI statistics are a complementary public resource.

---

### C3 — ARDC misclassified as a data custodian

**Observed:** ARDC (Australian Research Data Commons) is typed as a `Custodian` but is in fact a **metadata catalogue and discovery infrastructure provider**. Researchers use ARDC's Health Data Australia (HeSANDA) portal to *find* datasets, then apply to the actual holding custodian.

**Required fix:** Add a new `CustodianType` node: `Data Discovery Service` and reclassify ARDC under this type. Update ARDC's pathway card to state: *"ARDC does not hold or release data directly. Use Health Data Australia (healthdata.edu.au) to discover datasets, then follow the access pathway of the identified custodian."* The pathway steps should be: (1) Search HeSANDA catalogue → (2) Identify custodian → (3) Follow custodian's access pathway.

---

## ISSUE GROUP D — Missing Custodian (Gap)

### D1 — Department of Social Services (DSS) is missing from the custodian list

**Observed:** The AIHW pathway card references DSS as the source of DOMINO (Data Over Multiple Individual Occurrences) data. The connection review file shows this segment was force-rejected because DSS is not in the custodian list. DSS is a legitimate Commonwealth data custodian holding significant welfare and social services data that is frequently linked with health data.

**Required fix:** Add a new `Custodian` node for DSS with the following minimum content:

- **Name:** Department of Social Services
- **Short name:** DSS
- **Jurisdiction:** Commonwealth
- **Type:** Commonwealth
- **Primary role:** DSS is the Commonwealth custodian of welfare, disability, and social services administrative data. Key datasets include DOMINO (income support and welfare payments), NDIS data (via NDIA), and aged care program data.
- **Key datasets:** DOMINO, DSS Payment and Programme Data, NDIS participant data (via NDIA)
- **Connections:** AIHW (DOMINO accessible via AIHW Data Integration Services), Services Australia (income support data overlap), Department of Health and Aged Care (aged care policy)
- **Access pathway:** Data requests via DSS Data Governance team; most research access is via AIHW Data Integration Services as the linkage intermediary

---

## Summary: Issue Resolution Matrix

The table below shows which issues are addressed by the existing fuzzy matching pipeline and which require changes to the upstream LLM extraction prompt or post-processing logic.

| Issue | Category | Addressed by fuzzy pipeline? | Fix location |
|---|---|---|---|
| A1 — 6 isolated custodians | Connection extraction | Attempted but failed | LLM extraction prompt (connection field) |
| A2 — 15 review_required entries | Connection matching | Partially — needs human rules | Matching pipeline decision rules |
| A3 — Threshold and alias improvements | Matching pipeline | No | Matching pipeline config |
| B1 — 75.6% timeline placeholders | Node content | No | LLM extraction prompt (PathwayStep) |
| B2 — 40% empty identifiable/linkable | Node content | No | LLM extraction prompt (Dataset) |
| B3 — NACCHO zero datasets | Node content | No | LLM extraction prompt (Dataset) |
| C1 — NSW type duplication bug | Taxonomy | No | Post-processing deduplication step |
| C2 — APRA misclassification | Node type | No | Custodian type assignment logic |
| C3 — ARDC misclassification | Node type | No | Custodian type assignment logic |
| D1 — DSS missing from custodian list | Coverage gap | No | Custodian seed list |

---

## Recommended Prompt Additions for Iteration 2

Add the following system-level instructions to the KG generation prompt:

```
CUSTODIAN TYPE RULES:
- If the custodian publishes only aggregate statistical tables with no individual-level data access process, classify as CustodianType = "Statistical Publisher" (e.g., APRA).
- If the custodian operates a metadata catalogue or data discovery portal but does not hold or release data itself, classify as CustodianType = "Data Discovery Service" (e.g., ARDC/HeSANDA).
- If the custodian is a peak body or governance organisation that oversees data held by member organisations, classify as CustodianType = "Governance Body" and note the member organisations that hold the actual data.

TIMELINE RULES:
- Never leave the timeline field empty or set it to "(verify with custodian)" for standard process steps.
- Use the reference timeline table provided to assign default estimates where source text is silent.
- Always express timelines as ranges (e.g., "2–4 weeks") rather than point estimates.

CONNECTION EXTRACTION RULES:
- Only extract connections to custodians that appear in the provided custodian seed list.
- If the source text mentions a generic category (e.g., "state and federal data custodians", "research institutions"), do not extract a connection — instead flag it as a structural note.
- If the source text mentions a named entity not in the custodian list (e.g., "Department of Social Services", "VCCC"), add it to a "gap_custodians" list for review rather than force-rejecting.
- Always prefer a specific named custodian over a generic category when both appear in the same segment.

DATASET RULES:
- Every custodian must have at least one Dataset node. If the source text does not name specific datasets, infer from the custodian's known role and add a note "(inferred from custodian role — verify)".
- The identifiable and linkable fields must never be left empty. Use the classification rules provided.
```
