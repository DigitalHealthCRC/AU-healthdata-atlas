// AU Health Data Map frontend query pack
// Assumes the graph model loaded by scripts/load_au_health_kg_via_mcp.py

// 1) Line index for list and legend panels
MATCH (c:Custodian)-[:OFFERS_LINE]->(l:ProcessLine)
OPTIONAL MATCH (l)-[hs:HAS_STEP]->(s:PathwayStep)
RETURN
  l.id AS lineId,
  l.name AS lineName,
  c.id AS custodianId,
  c.name AS custodianName,
  count(s) AS stepCount,
  min(hs.order) AS firstStepOrder,
  max(hs.order) AS lastStepOrder
ORDER BY custodianName;

// 2) Ordered steps for one line
// Params: $lineId
MATCH (l:ProcessLine {id: $lineId})-[hs:HAS_STEP]->(s:PathwayStep)
RETURN
  l.id AS lineId,
  s.id AS stepId,
  hs.order AS stepOrder,
  coalesce(s.lane, hs.lane, 'Custodian') AS lane,
  s.text AS title,
  s.actor AS actor,
  s.channel AS channel,
  s.timeline AS timeline
ORDER BY stepOrder, stepId;

// 3) Step-to-step edges for one line (derived from HAS_STEP order)
// Params: $lineId
MATCH (l:ProcessLine {id: $lineId})-[h1:HAS_STEP]->(s1:PathwayStep)
MATCH (l)-[h2:HAS_STEP]->(s2:PathwayStep)
WHERE h2.order = h1.order + 1
RETURN
  l.id AS lineId,
  s1.id AS fromStepId,
  s2.id AS toStepId,
  h1.order AS fromOrder,
  h2.order AS toOrder,
  coalesce(s2.lane, h2.lane, 'Custodian') AS lane
ORDER BY fromOrder, toOrder;

// 4) Full line payload (nodes + ordered chain edges) for one line
// Params: $lineId
MATCH (l:ProcessLine {id: $lineId})-[hs:HAS_STEP]->(s:PathwayStep)
WITH l, s, hs
ORDER BY hs.order, s.id
WITH
  l,
  collect({
    id: s.id,
    order: hs.order,
    lane: coalesce(s.lane, hs.lane, 'Custodian'),
    title: s.text,
    actor: s.actor,
    channel: s.channel,
    timeline: s.timeline
  }) AS steps
WITH l, steps, range(0, size(steps) - 2) AS idx
RETURN
  l.id AS lineId,
  l.name AS lineName,
  steps AS stepNodes,
  [i IN idx | {
    from: steps[i].id,
    to: steps[i + 1].id,
    fromOrder: steps[i].order,
    toOrder: steps[i + 1].order
  }] AS chainEdges;

// 5) Lane bands summary (for lane headers and colors)
MATCH (:ProcessLine)-[hs:HAS_STEP]->(s:PathwayStep)
WITH coalesce(s.lane, hs.lane, 'Custodian') AS lane
RETURN
  lane,
  count(*) AS stepCount,
  CASE lane
    WHEN 'Researcher' THEN 1
    WHEN 'EthicsRegulatory' THEN 2
    WHEN 'Custodian' THEN 3
    ELSE 99
  END AS laneOrder
ORDER BY laneOrder;

// 6) Explicit inter-line branch edges from curated CONNECTED_TO
MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)
WHERE l1.id <> l2.id
RETURN
  l1.id AS fromLineId,
  l2.id AS toLineId,
  r.segment AS reasonSegment,
  r.matchType AS matchType,
  r.matchScore AS matchScore
ORDER BY matchScore DESC, fromLineId, toLineId;

// 7) Explicit inter-line branch edges anchored to step 1 of each line
MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)-[h1:HAS_STEP]->(s1:PathwayStep)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)-[h2:HAS_STEP]->(s2:PathwayStep)
WHERE h1.order = 1 AND h2.order = 1 AND l1.id <> l2.id
RETURN
  s1.id AS fromStepId,
  s2.id AS toStepId,
  l1.id AS fromLineId,
  l2.id AS toLineId,
  r.segment AS reasonSegment,
  r.matchType AS matchType,
  r.matchScore AS matchScore
ORDER BY matchScore DESC;

// 8) Potential branch points inferred from shared datasets
MATCH (c1:Custodian)-[:HAS_DATASET]->(d:Dataset)<-[:HAS_DATASET]-(c2:Custodian)
WHERE c1.id < c2.id
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)
WITH
  l1, l2,
  count(d) AS sharedDatasetCount,
  collect(d.name)[0..10] AS sharedDatasetSample
RETURN
  l1.id AS fromLineId,
  l2.id AS toLineId,
  sharedDatasetCount,
  sharedDatasetSample
ORDER BY sharedDatasetCount DESC, fromLineId, toLineId;

// 9) Sources for one line/custodian (for detail drawer)
// Params: $lineId
MATCH (l:ProcessLine {id: $lineId})<-[:OFFERS_LINE]-(c:Custodian)
OPTIONAL MATCH (c)-[:HAS_SOURCE]->(u:SourceURL)
RETURN
  l.id AS lineId,
  c.id AS custodianId,
  c.name AS custodianName,
  c.primaryRole AS primaryRole,
  c.ethicsAndGovernanceRequirements AS ethicsAndGovernanceRequirements,
  c.treSecureAccessPlatform AS treSecureAccessPlatform,
  c.contactAndApplicationPortal AS contactAndApplicationPortal,
  c.indicativeTimeline AS indicativeTimeline,
  c.gapsVerifyWithCustodian AS gapsVerifyWithCustodian,
  c.sourceRegisterTitle AS sourceRegisterTitle,
  c.sourceRegisterVersion AS sourceRegisterVersion,
  c.sourceRegisterGenerated AS sourceRegisterGenerated,
  c.sourceCsvPath AS sourceCsvPath,
  c.sourceMarkdownPath AS sourceMarkdownPath,
  c.sourceProvenanceStatus AS sourceProvenanceStatus,
  c.kgLoadedAt AS kgLoadedAt,
  collect(DISTINCT u.url) AS sourceUrls;

// 10) Datasets for one line/custodian
// Params: $lineId
MATCH (l:ProcessLine {id: $lineId})<-[:OFFERS_LINE]-(c:Custodian)-[hd:HAS_DATASET]->(d:Dataset)
RETURN
  l.id AS lineId,
  c.id AS custodianId,
  d.id AS datasetId,
  d.name AS datasetName,
  d.description AS datasetDescription,
  d.identifiable AS identifiable,
  d.linkable AS linkable,
  hd.source AS dataSource,
  coalesce(hd.sourceRegisterTitle, d.sourceRegisterTitle) AS sourceRegisterTitle,
  coalesce(hd.sourceRegisterVersion, d.sourceRegisterVersion) AS sourceRegisterVersion,
  coalesce(hd.sourceRegisterGenerated, d.sourceRegisterGenerated) AS sourceRegisterGenerated,
  coalesce(hd.sourceCsvPath, d.sourceCsvPath) AS sourceCsvPath,
  coalesce(hd.sourceMarkdownPath, d.sourceMarkdownPath) AS sourceMarkdownPath,
  coalesce(hd.sourceCsvModifiedAt, d.sourceCsvModifiedAt) AS sourceCsvModifiedAt,
  coalesce(hd.sourceMarkdownModifiedAt, d.sourceMarkdownModifiedAt) AS sourceMarkdownModifiedAt,
  coalesce(hd.sourceCsvSha256, d.sourceCsvSha256) AS sourceCsvSha256,
  coalesce(hd.sourceMarkdownSha256, d.sourceMarkdownSha256) AS sourceMarkdownSha256,
  coalesce(hd.sourceCustodianRowCount, d.sourceCustodianRowCount) AS sourceCustodianRowCount,
  coalesce(hd.sourceMarkdownCardCount, d.sourceMarkdownCardCount) AS sourceMarkdownCardCount,
  coalesce(hd.sourceOverrideRuleCount, d.sourceOverrideRuleCount) AS sourceOverrideRuleCount,
  coalesce(hd.sourceGitCommit, d.sourceGitCommit) AS sourceGitCommit,
  coalesce(hd.sourceProvenanceStatus, d.sourceProvenanceStatus) AS sourceProvenanceStatus,
  coalesce(hd.kgLoadedAt, d.kgLoadedAt) AS kgLoadedAt
ORDER BY datasetName;

// 11) All map lines as frontend-ready objects (without branch links)
MATCH (c:Custodian)-[:OFFERS_LINE]->(l:ProcessLine)
MATCH (l)-[hs:HAS_STEP]->(s:PathwayStep)
WITH c, l, s, hs
ORDER BY c.name, hs.order, s.id
WITH
  c,
  l,
  collect({
    id: s.id,
    order: hs.order,
    lane: coalesce(s.lane, hs.lane, 'Custodian'),
    title: s.text,
    actor: s.actor,
    channel: s.channel,
    timeline: s.timeline
  }) AS steps
RETURN collect({
  lineId: l.id,
  lineName: l.name,
  custodianId: c.id,
  custodianName: c.name,
  steps: steps
}) AS lines;

// 12) Combined lightweight graph payload (nodes + in-line edges + explicit branches)
MATCH (c:Custodian)-[:OFFERS_LINE]->(l:ProcessLine)
MATCH (l)-[hs:HAS_STEP]->(s:PathwayStep)
WITH c, l, s, hs
ORDER BY l.id, hs.order
WITH
  collect(DISTINCT {
    id: s.id,
    type: 'PathwayStep',
    lineId: l.id,
    order: hs.order,
    lane: coalesce(s.lane, hs.lane, 'Custodian'),
    title: s.text
  }) AS nodes,
  collect({
    lineId: l.id,
    stepId: s.id,
    stepOrder: hs.order
  }) AS ordered
WITH
  nodes,
  ordered,
  [a IN ordered WHERE any(b IN ordered WHERE b.lineId = a.lineId AND b.stepOrder = a.stepOrder + 1) |
    {
      from: a.stepId,
      to: head([b IN ordered WHERE b.lineId = a.lineId AND b.stepOrder = a.stepOrder + 1 | b.stepId]),
      type: 'NEXT_IN_LINE',
      lineId: a.lineId
    }
  ] AS inLineEdges
MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)-[h1:HAS_STEP]->(s1:PathwayStep)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)-[h2:HAS_STEP]->(s2:PathwayStep)
WHERE h1.order = 1 AND h2.order = 1
WITH
  nodes,
  inLineEdges,
  collect(DISTINCT {
    from: s1.id,
    to: s2.id,
    type: 'INTERCHANGE',
    fromLineId: l1.id,
    toLineId: l2.id,
    score: r.matchScore,
    matchType: r.matchType
  }) AS branchEdges
RETURN
  nodes,
  inLineEdges,
  branchEdges;
