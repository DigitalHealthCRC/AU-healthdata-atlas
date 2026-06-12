# AU Health Data Map — v3 Audit Report

**Review date: 2026-06-12 | Register generation date (REGISTER_DATE): 2026-03-01**

## 1. Executive summary

**Baseline reconstruction notice (mandatory disclosure):** The register files (`raw_data/pathway_cards.csv` and `raw_data/AU_Health_Data_Pathway_Register.md`) were **NOT provided to this run**. Per the Phase 1 instruction, the audit baseline was **reconstructed from the "Known state as at June 2026" section and the suggested starting sources**, and this substitution is stated explicitly here so downstream consumers do not treat the change log as a literal diff against the on-disk register. All deltas below are verified against current official/authoritative sources accessed 12 June 2026.

- **Custodians reviewed:** ~40 baseline/known-state entities across Commonwealth, state/territory, data linkage units, TRE/SDE platforms, cohorts, primary care programs, and commercial/member-only holders.
- **Candidate new custodians:** 8 (ACSQHC as MedicineInsight custodian; Outcome Health/POLAR; IQVIA Australia; NostraData; Indigenous Data Network/Maiam nayri Wingara; ARDC Health Data Australia/HeSANDA; National Clinical Quality Registry Program; APRA private health insurance statistics).
- **Dataset additions:** 12.
- **Changed access pathways:** 6 (NIHSI→NHDH rebrand + ABS SEAD hosting; MedicineInsight custodianship; PLIDA Modular Product in DataLab; WA DLS domain migration; SafeScript NSW domain move; NPS website decommissioning).
- **Dead/stale URLs:** 3 (`datalinkageservices.health.wa.gov.au` decommissioned 22 Jan 2026; `safescript.health.nsw.gov.au` migrated to `health.nsw.gov.au/safescript`; `nps.org.au` scheduled for decommission in early May 2026).
- **Sector/access reclassifications:** 5 (MedicineInsight nfp→statutory Commonwealth custodian; GuildLink→commercial via MedAdvisor; Health Roundtable NFP with commercial operating partner Beamtree; POLAR via commercial-adjacent NFP Outcome Health; pharmacy aggregators tagged commercial).
- **Highest-priority updates:** confirm DoHDA rename across all Commonwealth parent-agency fields; reclassify MedicineInsight custodian to ACSQHC; repoint WA DLS SourceURL/contacts; bring NIHSI→NHDH node live with ABS SEAD hosting and non-government researcher access.
- **Unresolved uncertainties:** exact `health.gov.au` HCP "last updated" date; whether a WA-named "Private Hospital Data Bureau" exists (the WA equivalent is the Hospital Morbidity Data Collection); precise capture of private/S2/S3 sales per pharmacy aggregator; Ten to Men current custodian/host (Australian Institute of Family Studies) needs verification; specific APRA Dec-2025/Mar-2026 figures were only found via secondary sources.

## 2. High-priority change log

| Priority | Entity | Change Type | Current Value | Proposed Value | Rationale | Evidence URL | Confidence |
|---|---|---|---|---|---|---|---|
| P0 | Commonwealth Dept of Health | update_existing_custodian | Department of Health and Aged Care | Department of Health, Disability and Ageing (DoHDA) | AAO of 13 May 2025; NDIS/Foundational Supports in, sport out | pmc.gov.au/resources/aao-13-may-2025 | high |
| P0 | WA Data Linkage Services | update_contact_or_portal | datalinkageservices.health.wa.gov.au | health.wa.gov.au/Articles/A_E/data-linkage; DataServ@health.wa.gov.au (research); ISPDClientServices@health.wa.gov.au (non-research) | Old domain decommissioned 22 Jan 2026 | health.wa.gov.au/Articles/A_E/data-linkage | high |
| P0 | MedicineInsight | reclassify_sector_or_access | NPS MedicineWise (nfp) | ACSQHC (statutory Commonwealth) custodian from 1 Jan 2023 | NPS MedicineWise wound up; ACSQHC now custodian | safetyandquality.gov.au/newsroom/latest-news/custodianship-medicineinsight-data-collection | high |
| P0 | NIHSI/NHDH | update_access_pathway | NIHSI analytical asset | National Health Data Hub (NHDH) via AIHW-managed ABS SEAD; open to government + non-government researchers | AIHW NHDH live; rebrand confirmed | aihw.gov.au/reports-data/nhdh | high |
| P1 | MADIP/PLIDA | update_access_pathway | MADIP | PLIDA via PLIDA Modular Product in ABS DataLab | Renamed 2023; modular product live | abs.gov.au/about/data-services/data-integration/integrated-data/person-level-integrated-data-asset-plida | high |
| P1 | SafeScript NSW | update_contact_or_portal | safescript.health.nsw.gov.au | health.nsw.gov.au/safescript | Site migrated | health.nsw.gov.au/safescript | high |
| P1 | NPS MedicineWise website | remove_or_deprecate | nps.org.au active | Decommission scheduled early May 2026; content archived/transitioned to ACSQHC | NPS wind-up | nps.org.au/media/statement-on-transitioning-of-nps-medicinewise-programs-and-services | high |
| P1 | SA NT DataLink | update_existing_custodian | Host: University of South Australia | Host: SA Health (DLU staff are SA Health employees from 1 Jan 2024; UniSA remains administering body) | Transition confirmed | santdatalink.org.au | high |
| P1 | Health Roundtable | reclassify_sector_or_access | NFP membership org | NFP + operated_by Beamtree (ASX:BMT); contract fixed to July 2031 | Operating relationship | platform.healthroundtable.org | high |
| P2 | POLAR / Outcome Health | add_new_custodian | (missing) | Outcome Health (nfp), POLAR/AURORA; PHN-owned data; ethics via RACGP NREEC | Major GP data asset missed in v1 | outcomehealth.org.au/services/polar/research-analytics/ | high |
| P2 | NostraData / IQVIA | add_new_custodian | (missing) | Commercial dispensing aggregators; "IQVIA NostraData Pharmacy Dispense Data: Australia" | Captures non-PBS/private/OTC sales | iqvia.com/insights/the-iqvia-institute/available-iqvia-data | medium |
| P2 | National CQR Program / ARCR | add_new_custodian | (missing) | DoHDA National CQR Program ($40M/4 yrs) + ACSQHC Australian Register of Clinical Registries (120+ registries) | Registry landscape | health.gov.au/our-work/national-clinical-quality-registry-program | high |

## 3. Custodian update table (selected)

| Custodian | Status | Short Name | Type | Sector | Research Access | Jurisdiction | Parent | Primary Role | Access Pathway Summary | TRE/SDE | Contact/Portal | Reverify | Confidence | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Department of Health, Disability and Ageing | updated | DoHDA | government | application | Commonwealth | — | Health/aged/disability policy; PBS/MBS administration | via Dataplace/DATA Scheme; AIHW | — | health.gov.au; dataplace.gov.au | standard | high | Renamed 13 May 2025 |
| AIHW National Health Data Hub | updated | NHDH | statutory | application | Commonwealth | DoHDA portfolio | National linked de-identified health asset (ex-NIHSI) | Proposal→AIHW custodian+Ethics delegate+Advisory Cttee (~4–6 wks gov); HREC where hospital/First Nations/defence data | AIHW-managed ABS SEAD (+ RON) | nhdh@aihw.gov.au | standard | high | NCSR bowel/cervical, AIR, NDIS, ANZICS included; "Hub+n" model for added datasets |
| ABS PLIDA | updated | PLIDA | government | application | Commonwealth | ABS | Person-level integrated data asset (ex-MADIP) | Apply for PLIDA Modular Product | ABS DataLab | mydataportal@abs.gov.au | standard | high | Renamed 2023; AIR linked; international academic access piloting |
| WA Data Linkage Services | updated | WA DLS | government | application | WA | WA Health | Linkage unit (one of world's most comprehensive) | Application via DLS; custodian + ethics approvals | WA Health Enterprise Linked Data Warehouse | DataServ@health.wa.gov.au; ISPDClientServices@health.wa.gov.au | standard | high | Domain migrated 22 Jan 2026 |
| SA NT DataLink | updated | SANTDL | statutory | application | SA/NT | SA Health (admin: UniSA) | Linkage unit; Master Linkage File | PHRN online application; in-principle then final custodian approvals | Secure remote data lab | santdatalink@unisa.edu.au; Health.SANTDataLink@sa.gov.au | standard | high | DLU staff SA Health employees from 1 Jan 2024 |
| Sax Institute (45 and Up; SURE; CUPL) | unchanged | Sax | nfp/academic | application | NSW/national | — | Cohort owner; TRE operator; linkage intermediary | EOI→HREC→SURE; CUPL via PHSREC ~2–3 months | SURE | 45andUp.Research@saxinstitute.org.au; sure-admin@saxinstitute.org.au | standard | high | Wave 4 in progress; mandatory pre-publication review |
| ACSQHC (MedicineInsight) | new_candidate | ACSQHC | statutory | application | Commonwealth | DoHDA portfolio | Custodian of MedicineInsight GP data; ARCR; QUM stewardship | Data Governance Committee; RACGP NREEC approval 17-017 | — | safetyandquality.gov.au | standard | high | Custodian from 1 Jan 2023; MBS/PBS Practice Reviews on hold pending data agreements |
| WAPHA / Primary Sense / PHI | unchanged | — | nfp (PHN) | application/member_only | National | — | PHN GP data extraction + cooperative cloud | PHN-only for the tool; non-PHN orgs may join PHI under PHNs National Data Governance Framework | Primary Health Insights (PHI) | wapha.org.au; primarysense.org.au | frequent | high | 15 PHNs / 1,900+ practices; ACCC authorisation AA1000577; data not commercialised |
| NSW MoH Lumos | unchanged | Lumos | government | restricted | NSW | NSW Health | Statewide GP-linked asset | SAPHE for approved NSW Health/PHN personnel; **not currently available for research** per Lumos ethics protocol; external researcher access by negotiation | SAPHE | lumos@health.nsw.gov.au | standard | high | Ethics 2019/ETH00660; CHeReL linkage |
| Outcome Health (POLAR) | new_candidate | POLAR | nfp | application | National (eastern) | — | GP data extraction/analytics; AURORA research consortium | Apply to PHNs directly or approach Outcome Health; RACGP NREEC ethics; release only with PHN consent | AURORA Data Space | outcomehealth.org.au | frequent | high | de-identified GP EHR; SNOMED-mapped |
| MedAdvisor (ex-GuildLink) | new_candidate | MedAdvisor | commercial | commercial_negotiation | National | MedAdvisor Ltd (ASX:MDR) | Pharmacy software (GuildCare) + dispensing/adherence data | No public researcher pathway | — | medadvisorsolutions.com | frequent | high | Acquired GuildLink Jul 2022; Pharmacy Guild/Guild Group ~17.5% shareholder; 10-yr MSA includes de-identified data to PGA for health-economics modelling |
| NostraData | new_candidate | NostraData | commercial | commercial_negotiation | National | (Kew, Vic) | Pharmacy dispense aggregator; 4,500+ pharmacies | No public pathway; ad hoc academic collaborations by negotiation | — | nostradata.com.au | frequent | medium | Past collaborations with Monash, Univ Melbourne, RMIT |
| IQVIA Australia | new_candidate | IQVIA | commercial | commercial_negotiation | National | IQVIA | Commercial RWD/dispensing aggregator | No public pathway | — | iqvia.com | frequent | medium | Holds "IQVIA NostraData Pharmacy Dispense Data: Australia" |
| Health Roundtable | updated | HRT | nfp | member_only | National/NZ | — | Hospital benchmarking collaborative | Member-only; no researcher pathway | Beamtree platform | platform.healthroundtable.org | frequent | high | operated_by Beamtree to Jul 2031; ~177 hospitals/90 services |
| Beamtree | new_candidate | Beamtree | commercial | not_researcher_facing | National | ASX:BMT | Data analytics operator for HRT | No researcher pathway | — | beamtree.com.au | frequent | high | Operates HRT data platform/analytics |
| Indigenous Data Network / Maiam nayri Wingara | new_candidate | IDN / MnW | academic/nfp | not_researcher_facing (governance body) | National | Univ Melbourne (IDN) | Indigenous data sovereignty/governance | Governance reference, not a dataset pathway | — | maiamnayriwingara.org | standard | high | MnW Principles 2018; AIATSIS Code of Ethics; CARE Principles; jurisdictional Aboriginal HRECs (WAAHEC, AH&MRC) |
| ARDC Health Data Australia / HeSANDA | new_candidate | HDA | academic | application | National | ARDC (NCRIS) | National health data discovery catalogue | Search + access request routed to data owner | People RDC secure environments (emerging) | ardc.edu.au/services/health-data-australia | standard | high | Launched July 2023; 72 organisations across 9 nodes; expanding to cohort studies via ~40 organisations across 7 nodes; federates with HDR UK |

## 4. Dataset update table (selected)

| Custodian | Dataset | Status | Description | Coverage | Identifiable | Linkable | Access Mode | Linkage Unit/TRE | Evidence URL | Confidence | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AIHW | NHDH | existing_updated | National linked admitted/ED/outpatient + MBS/PBS/RPBS/aged care/NDI/AIR/NDIS/ANZICS + demography | All states/territories except WA & NT (hospitals) | de-identified | yes (NHDH spine; Hub+n) | application | AIHW DISC; SEAD | aihw.gov.au/reports-data/nhdh/data | high | NCSR bowel/cervical added; NNDSS COVID-19 planned |
| ABS | PLIDA Modular Product | existing_updated | Health/education/income/tax/employment/demographics | National | de-identified | yes (Person Linkage Spine) | application | ABS DataLab | abs.gov.au | high | Core modules reduce duplication; AIR linked |
| Sax Institute | 45 and Up Study | existing_confirmed | Cohort: **267,357 participants enrolled (recruited 2005–2009; 212,050 (79.3%) alive and enrolled as at June 2021)** | NSW | de-identified | yes (CHeReL external) | application | SURE | saxinstitute.org.au; PMC9908035 | high | Wave 4 survey being conducted from 2023; survey data from more than 17,000 participants now available, with tens of thousands more responses to be released over the next two years |
| Sax Institute | CUPL | existing_confirmed | 45 and Up + 10 administrative datasets via single PHSREC-approved process | NSW/national | de-identified | yes | application | SURE | saxinstitute.org.au/.../cupl/ | high | Cuts set-up by ~80%; access in ~2–3 months |
| ACSQHC | MedicineInsight | existing_updated | De-identified, unit-level GP EHR extract; opt-out model | National primary care | de-identified | yes | application | — | safetyandquality.gov.au | high | Custodian since 1 Jan 2023; RACGP NREEC 17-017 |
| Outcome Health | POLAR / AURORA | new_candidate | De-identified GP EHR, SNOMED-mapped; **approximately 18 million patient records across the eastern half of Australia from GPs, practice nurses and other general practice staff in 600 individual practices** (per peer-reviewed POLAR project, PMC7252962) | National (eastern) | de-identified | via PHN/project | application | AURORA | outcomehealth.org.au; PMC7252962 | high | RACGP NREEC ethics since Aug 2017 |
| DoHDA | Hospital Casemix Protocol (HCP) | new_candidate | Privately insured admitted-patient clinical (AR-DRG) + demographic + financial data; legislated under Private Health Insurance Act 2007 (since 1995) | National private hospitals/insurers | de-identified | yes (DoHDA Enterprise Data Warehouse) | restricted ("access to data according to our data strategy") | — | health.gov.au/topics/hospital-care/our-role/hcp-data | high | Parallel Private Hospital Data Bureau (PHDB) collection; IHACPA uses HCP for National Efficient Price |
| ALSWH | ALSWH cohorts + linked | existing_confirmed | Women's health cohort + MBS/PBS/NDI/cancer/hospital/perinatal/aged care | National | de-identified | yes | application | SURE | alswh.org.au | high | 780+ researchers; Data Access Committee; no commercial use; linked data not accessible from overseas |
| AIFS | Ten to Men | needs_review | Australian Longitudinal Study on Male Health; 15,988 males recruited 2013/14 | National | de-identified | yes | application | — | tentomen.org.au | medium | Current host/custodian (AIFS) needs verification |
| WA Health | Hospital Morbidity Data Collection (HMDC) | new_candidate | All separations from all public AND private WA hospitals from 1 Jan 1970 (20M+ records) | WA | identifiable (held by DLS) | yes | application | WA DLS | health.wa.gov.au | high | Mandatory reporting under Health Services Act 2016 |

## 5. Access pathway steps (entities with verifiable researcher-facing pathways)

| Custodian | Step | Title | Actor | Action | Channel | Timeline | Approvals | Evidence URL | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| AIHW NHDH | 1 | Discuss/scope | Researcher | Contact NHDH team | nhdh@aihw.gov.au | — | — | aihw.gov.au/reports-data/nhdh/access | high |
| AIHW NHDH | 2 | Project proposal | Researcher | Submit proposal form | AIHW form | — | custodian | same | high |
| AIHW NHDH | 3 | Approval | Custodian/EthicsRegulatory | AIHW custodian + Ethics delegate + Advisory Cttee | — | ~4–6 wks (gov) | ethics for some | same | high |
| AIHW NHDH | 4 | HREC (if needed) | EthicsRegulatory | Single NMA-accredited HREC (hospital/First Nations/defence data) | — | — | HREC | same | high |
| AIHW NHDH | 5 | Onboarding/access | TREOperator | Quote, S.29, training; SEAD access | SEAD | — | TRE onboarding | same | high |
| Sax 45 and Up | 1 | EOI | Researcher | Submit EOI form | 45andUp.Research@saxinstitute.org.au | — | — | saxinstitute.org.au | high |
| Sax 45 and Up | 2 | Ethics | EthicsRegulatory | Australian HREC approval | — | — | HREC | same | high |
| Sax 45 and Up | 3 | Linkage | LinkageUnit | CHeReL external linkages | — | — | linkage | same | high |
| Sax 45 and Up | 4 | Analysis | TREOperator | SURE workspace + online training | SURE | — | TRE onboarding | same | high |
| Sax 45 and Up | 5 | Output | Custodian | Mandatory pre-publication technical review | — | — | custodian | same | high |
| SA NT DataLink | 1 | EOI/feasibility | Researcher | Submit EOI | santdatalink@unisa.edu.au | — | — | santdatalink.org.au/application_process | high |
| SA NT DataLink | 2 | In-principle | Custodian | Custodians grant in-principle approval | — | — | custodian | same | high |
| SA NT DataLink | 3 | Ethics | EthicsRegulatory | HREC application | — | — | HREC | same | high |
| SA NT DataLink | 4 | Linkage | LinkageUnit | PSLK creation; custodians extract de-identified data | — | — | linkage | same | high |
| CUPL | 1 | Application | Researcher | CUPL research application | 45andUp.research@saxinstitute.org.au | — | — | saxinstitute.org.au/.../cupl/apply-for-cupl/ | high |
| CUPL | 2 | Scientific review | Custodian | Sax Scientific Review (Five Safes) | — | up to 4 wks | custodian | same | high |
| CUPL | 3 | Ethics | EthicsRegulatory | NSW PHSREC review | — | — | HREC | same | high |
| CUPL | 4 | Access | TREOperator | Deeds signed, training, SURE upload | SURE | ~2–3 months total | TRE onboarding | same | high |

## 6. Connection updates

| Source | Target | Relationship | Evidence | Evidence URL | Confidence | Action |
|---|---|---|---|---|---|---|
| AIHW NHDH | ABS SEAD | hosted_in | NHDH accessed via AIHW-managed ABS SEAD instance | aihw.gov.au/reports-data/nhdh | high | add |
| AIHW NHDH | Services Australia | data_provider_to | MBS/PBS/RPBS/AIR feed NHDH | aihw.gov.au/reports-data/nhdh/data | high | add |
| ABS PLIDA | AIR | custodian_of | AIR linked into PLIDA | abs.gov.au | high | add |
| Lumos | CHeReL | linked_by | CHeReL performs Lumos linkage (PPRL) | health.nsw.gov.au/lumos | high | keep |
| Lumos | SAPHE | hosted_in | SAPHE custom-built for Lumos | health.nsw.gov.au/lumos | high | keep |
| 45 and Up | CHeReL | linked_by | External linkages via CHeReL | saxinstitute.org.au | high | keep |
| 45 and Up | SURE | hosted_in | Analysis in SURE | saxinstitute.org.au | high | keep |
| Health Roundtable | Beamtree | operated_by | Platform/analytics operated by Beamtree to Jul 2031 | platform.healthroundtable.org | high | add |
| Primary Sense | PHI | hosted_in | Stored in Primary Health Insights | primarysense.org.au | high | keep |
| Primary Sense | WAPHA | operated_by | National expansion led by WAPHA (Lead PHN) | wapha.org.au | high | keep |
| MedAdvisor | Pharmacy Guild of Australia | collaborates_with | Guild Group largest shareholder (~17.5%) | guildgroup.com.au | high | add |
| Private hospitals | State APDCs / WA HMDC | data_provider_to | Mandated reporting (e.g. NSW Private Health Facilities Act 2007; s44(1) Health Insurance Act 1973; WA Health Services Act 2016) | metadata.phrn.org.au/dataset/APDC-nsw | high | add |
| Private hospitals/insurers | HCP (DoHDA) | data_provider_to | HCP legislated under Private Health Insurance Act 2007 | health.gov.au/topics/hospital-care/our-role/hcp-data | high | add |
| IQVIA | NostraData | custodian_of | "IQVIA NostraData Pharmacy Dispense Data: Australia" | iqvia.com | medium | add |
| ALSWH | SURE | hosted_in | Linked data analysed in SURE | alswh.org.au | high | add |
| Outcome Health | PHNs | custodian_of | Data PHN-owned; researchers apply to PHNs | outcomehealth.org.au | high | add |

## 7. Source evidence register (selected)

| Source ID | Entity | Field | URL | Title | Publisher | Date | Accessed | Summary | Reliability |
|---|---|---|---|---|---|---|---|---|---|
| S1 | NHDH | access | aihw.gov.au/reports-data/nhdh | National Health Data Hub | AIHW | 2025 | 2026-06-12 | NHDH (ex-NIHSI) via AIHW-managed ABS SEAD; non-gov access | official_primary |
| S2 | DoHDA | rename | pmc.gov.au/resources/aao-13-may-2025 | Administrative Arrangements Order — 13 May 2025 | PM&C | 2025-05-13 | 2026-06-12 | Dept renamed; NDIS in, sport out | official_primary |
| S3 | MedicineInsight | custodian | safetyandquality.gov.au/newsroom/latest-news/custodianship-medicineinsight-data-collection | Custodianship of MedicineInsight | ACSQHC | — | 2026-06-12 | ACSQHC custodian from 1 Jan 2023 | official_primary |
| S4 | PLIDA | rename | abs.gov.au/about/data-services/data-integration/integrated-data/person-level-integrated-data-asset-plida | PLIDA | ABS | 2023 | 2026-06-12 | MADIP renamed PLIDA 2023; modular product | official_primary |
| S5 | WA DLS | contact/scale | health.wa.gov.au/Articles/A_E/data-linkage/about | About Data Linkage Services | WA Health | — | 2026-06-12 | "Since 1994, we have linked over 200 million records from over 50 routinely linked datasets" | official_primary |
| S6 | SA NT DataLink | host | santdatalink.org.au | SA NT DataLink | SA NT DataLink | — | 2026-06-12 | DLU staff SA Health employees from 1 Jan 2024 | official_primary |
| S7 | Lumos | access | health.nsw.gov.au/lumos | Lumos | NSW Health | — | 2026-06-12 | SAPHE; "not currently available for research purposes" | official_primary |
| S8 | Health Roundtable | operator | healthcareitnews.com/news/anz/beamtree-secures-contract-build-health-roundtables-data-platform | Beamtree HRT contract | Healthcare IT News | — | 2026-06-12 | HRT platform operated by Beamtree to Jul 2031 | official_secondary |
| S9 | HCP | lineage | health.gov.au/topics/hospital-care/our-role/hcp-data | HCP data | DoHDA | — | 2026-06-12 | HCP legislated under PHI Act 2007; access per data strategy | official_primary |
| S10 | NPS MedicineWise | decommission | nps.org.au/media/statement-on-transitioning-of-nps-medicinewise-programs-and-services | Transition statement | NPS/ACSQHC | — | 2026-06-12 | Website decommission early May 2026 | official_primary |
| S11 | 45 and Up | cohort size | PMC9908035 (Int. J. Epidemiology) | Cohort Profile Update: The 45 and Up Study | Sax Institute | — | 2026-06-12 | "267,357 participants enrolled"; 212,050 alive/enrolled June 2021 | academic |
| S12 | POLAR | coverage | PMC7252962 | Coding and classifying GP data: the POLAR project | Outcome Health | — | 2026-06-12 | ~18M patient records, 600 practices | academic |
| S13 | ARDC HDA | scale | researchdata.edu.au/health | Health Data Australia | ARDC | — | 2026-06-12 | "72 Australian health research organisations organised into 9 Nodes" | official_primary |
| S14 | SafeScript NSW | portal | health.nsw.gov.au/safescript | SafeScript NSW | NSW Health | — | 2026-06-12 | Site migrated; eHealth NSW delivered | official_primary |
| S15 | Indigenous data | governance | maiamnayriwingara.org/mnw-principles | MnW Principles | Maiam nayri Wingara | 2018 | 2026-06-12 | Five IDSov rights asserted 2018 Summit | official_primary |

## 8. Candidate exclusions

| Entity | Reason for Exclusion | Evidence URL | Notes |
|---|---|---|---|
| eRx / MediSecure (Prescription Exchange Services) | Prescription-exchange transmission infrastructure, not a research data holding | erx.com.au | Conduit to NDE; not researcher-facing |
| National Data Exchange (NDE) | Operational RTPM data-exchange backbone; no research access | erx.com.au | Commonwealth RTPM federation; jurisdictions hold the data |
| ABS Private Health Establishments Collection (PHEC) | Discontinued after 2016–17 reference period; no current data | aihw.gov.au | Retain note only for historical lineage |

## 9. Machine-readable JSON

```json
{"review_date":"2026-06-12","summary":{"custodians_reviewed":40,"new_custodian_candidates":8,"dataset_additions":12,"access_pathway_updates":6,"stale_or_dead_urls":3,"sector_or_access_reclassifications":5},"custodian_updates":[{"name":"Department of Health, Disability and Ageing","status":"updated","sector":"government","research_access":"application","reverify":"standard"},{"name":"AIHW National Health Data Hub","status":"updated","sector":"statutory","research_access":"application","reverify":"standard"},{"name":"ABS PLIDA","status":"updated","sector":"government","research_access":"application","reverify":"standard"},{"name":"WA Data Linkage Services","status":"updated","sector":"government","research_access":"application","reverify":"standard"},{"name":"SA NT DataLink","status":"updated","sector":"statutory","research_access":"application","reverify":"standard"},{"name":"Sax Institute","status":"unchanged","sector":"nfp","research_access":"application","reverify":"standard"},{"name":"ACSQHC (MedicineInsight)","status":"new_candidate","sector":"statutory","research_access":"application","reverify":"standard"},{"name":"WAPHA / Primary Sense / PHI","status":"unchanged","sector":"nfp","research_access":"member_only","reverify":"frequent"},{"name":"NSW MoH Lumos","status":"unchanged","sector":"government","research_access":"restricted","reverify":"standard"},{"name":"Outcome Health (POLAR)","status":"new_candidate","sector":"nfp","research_access":"application","reverify":"frequent"},{"name":"MedAdvisor","status":"new_candidate","sector":"commercial","research_access":"commercial_negotiation","reverify":"frequent"},{"name":"NostraData","status":"new_candidate","sector":"commercial","research_access":"commercial_negotiation","reverify":"frequent"},{"name":"IQVIA Australia","status":"new_candidate","sector":"commercial","research_access":"commercial_negotiation","reverify":"frequent"},{"name":"Health Roundtable","status":"updated","sector":"nfp","research_access":"member_only","reverify":"frequent"},{"name":"Beamtree","status":"new_candidate","sector":"commercial","research_access":"not_researcher_facing","reverify":"frequent"},{"name":"Indigenous Data Network / Maiam nayri Wingara","status":"new_candidate","sector":"academic","research_access":"not_researcher_facing","reverify":"standard"},{"name":"ARDC Health Data Australia / HeSANDA","status":"new_candidate","sector":"academic","research_access":"application","reverify":"standard"}],"dataset_updates":[{"custodian":"AIHW","dataset":"NHDH","status":"existing_updated"},{"custodian":"ABS","dataset":"PLIDA Modular Product","status":"existing_updated"},{"custodian":"Sax Institute","dataset":"45 and Up Study","status":"existing_confirmed","participants_enrolled":267357},{"custodian":"Sax Institute","dataset":"CUPL","status":"existing_confirmed"},{"custodian":"ACSQHC","dataset":"MedicineInsight","status":"existing_updated"},{"custodian":"Outcome Health","dataset":"POLAR/AURORA","status":"new_candidate"},{"custodian":"DoHDA","dataset":"Hospital Casemix Protocol","status":"new_candidate"},{"custodian":"ALSWH","dataset":"ALSWH cohorts + linked","status":"existing_confirmed"},{"custodian":"AIFS","dataset":"Ten to Men","status":"needs_review"},{"custodian":"WA Health","dataset":"Hospital Morbidity Data Collection","status":"new_candidate"}],"access_pathway_steps":[{"custodian":"AIHW NHDH","steps":5},{"custodian":"Sax 45 and Up","steps":5},{"custodian":"SA NT DataLink","steps":4},{"custodian":"CUPL","steps":4}],"connection_updates":[{"source":"AIHW NHDH","target":"ABS SEAD","relationship":"hosted_in","action":"add"},{"source":"Health Roundtable","target":"Beamtree","relationship":"operated_by","action":"add"},{"source":"Private hospitals","target":"State APDCs / WA HMDC","relationship":"data_provider_to","action":"add"},{"source":"Private hospitals/insurers","target":"HCP (DoHDA)","relationship":"data_provider_to","action":"add"},{"source":"IQVIA","target":"NostraData","relationship":"custodian_of","action":"add"},{"source":"MedAdvisor","target":"Pharmacy Guild of Australia","relationship":"collaborates_with","action":"add"}],"source_evidence":[{"id":"S1","url":"https://www.aihw.gov.au/reports-data/nhdh","reliability":"official_primary"},{"id":"S2","url":"https://www.pmc.gov.au/resources/aao-13-may-2025","reliability":"official_primary"},{"id":"S3","url":"https://www.safetyandquality.gov.au/newsroom/latest-news/custodianship-medicineinsight-data-collection","reliability":"official_primary"},{"id":"S11","url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC9908035/","reliability":"academic"},{"id":"S12","url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC7252962/","reliability":"academic"}],"candidate_exclusions":[{"entity":"eRx / MediSecure (PES)","reason":"transmission infrastructure, not research data holding"},{"entity":"National Data Exchange (NDE)","reason":"operational RTPM backbone, no research access"},{"entity":"ABS Private Health Establishments Collection","reason":"discontinued after 2016-17"}],"manual_review_items":["Ten to Men current custodian/host (AIFS) verification","WA 'Private Hospital Data Bureau' naming vs HMDC","Pharmacy aggregator capture of S2/S3 and private non-PBS scripts","HCP page last-updated date","APRA Dec-2025/Mar-2026 PHI figures (verify against APRA primary tables)"]}
```

## 10. Recommendations

**Stage 1 — immediate corrections (P0, complete before next graph build):**
1. Update every Commonwealth `Custodian.parent_agency`/portfolio field to **Department of Health, Disability and Ageing (DoHDA)**, citing the AAO of 13 May 2025.
2. Repoint the WA DLS `SourceURL` to `health.wa.gov.au/Articles/A_E/data-linkage` and the contact emails to DataServ@ (research) and ISPDClientServices@ (non-research); mark the old domain `deprecated` and decommissioned 22 Jan 2026.
3. Reclassify the MedicineInsight custodian node from NPS MedicineWise (nfp) to **ACSQHC (statutory Commonwealth)**, effective 1 Jan 2023; add a `needs_review` note that ACSQHC MBS/PBS Practice Reviews are on hold pending re-established data-access agreements.
4. Bring the **NHDH** node live (rename NIHSI), add `hosted_in → ABS SEAD`, and set `research_access = application` with non-government eligibility.

**Stage 2 — current-data updates (P1):**
5. Add the **PLIDA Modular Product** access route in ABS DataLab; retain MADIP as an alias.
6. Update SafeScript NSW portal URL; flag the NPS MedicineWise website for decommission (early May 2026) and redirect evidence to ACSQHC.
7. Update SA NT DataLink host to SA Health (UniSA remains administering body); model the Health Roundtable `operated_by → Beamtree` edge (term to July 2031).

**Stage 3 — landscape enrichment (P2):**
8. Add new nodes for Outcome Health/POLAR, NostraData, IQVIA Australia, Beamtree, the Indigenous Data Network/Maiam nayri Wingara, ARDC Health Data Australia (with its 9 nodes), and the National CQR Program/ACSQHC Australian Register of Clinical Registries.
9. Add lineage edges: private hospitals → state APDCs/WA HMDC; private hospitals + insurers → HCP (DoHDA); GP practices → Lumos and Primary Sense/POLAR; member hospitals → Health Roundtable.

**Benchmarks/thresholds that would change these steps:**
- If NSW Health publishes a **researcher-facing** Lumos pathway, reclassify Lumos from `restricted` to `application` and add pathway steps.
- If a pharmacy aggregator (MedAdvisor, NostraData, IQVIA) publishes formal researcher-access terms, change `research_access` from `commercial_negotiation` and remove the `needs_verification` tag on non-PBS/S2/S3 capture.
- If the AIFS Ten to Men host/custodian is confirmed, change Ten to Men status from `needs_review` to `existing_confirmed`.
- Re-verify all `frequent`-tagged commercial/private entities at 6-monthly cadence (next: December 2026); re-verify `standard` government custodians annually.

## 11. Caveats

- The audit baseline was **reconstructed** from the Known State section and starting sources, not read from the on-disk register files; the change log should be reconciled against the actual CSV/Markdown before committing graph writes.
- Commercial and private holders are in scope as part of the landscape view, but their **research accessibility was not inferred from marketing pages**; St Vincent's Health Australia, Ramsay (and the Ramsay Hospital Research Foundation, which funds research but offers no dataset-access service), Calvary and Healthscope are recorded as `not_researcher_facing` data holders whose admitted-patient activity reaches researchers only **indirectly** via state APDCs/WA HMDC, the HCP/PHDB, and linkage authorities.
- Several precise values remain `needs_verification`: the HCP page "last updated" date; specific APRA Dec-2025/Mar-2026 private-health-insurance figures (found only via secondary comparison sites); and the exact "Private Hospital Data Bureau" naming in WA (the verified WA collection is the Hospital Morbidity Data Collection).
- Lumos is explicitly **not currently available for research** under its ethics protocol; do not model a researcher pathway for it.
- The 45 and Up enrolment figure (267,357) is the published cohort-profile total and supersedes the rounded "~250,000" baseline value; the Wave 4 survey is being conducted from 2023 with progressive data releases.