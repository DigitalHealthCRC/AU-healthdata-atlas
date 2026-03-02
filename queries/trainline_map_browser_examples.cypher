// AU Health Data Map
// Browser-ready Cypher examples for reconstructing the trainline-style map graph.
//
// Intended for the Neo4j VS Code extension first.
// - Run one query block at a time.
// - Parameterized examples are written in a VS Code-safe form using:
//   WITH 'value' AS lineId
// - This file intentionally avoids executable $parameter placeholders because
//   the VS Code extension may prompt for empty parameter values when running
//   multiple statements from one file.
// - These examples use the current KG schema:
//   (:Custodian)-[:OFFERS_LINE]->(:ProcessLine)-[:HAS_STEP {order, lane}]->(:PathwayStep)
//   (:Custodian)-[:CONNECTED_TO]->(:Custodian)


// -----------------------------------------------------------------------------
// 1) Quick sanity check
// -----------------------------------------------------------------------------
CALL () { MATCH (c:Custodian) RETURN count(c) AS custodians }
CALL () { MATCH (l:ProcessLine) RETURN count(l) AS lines }
CALL () { MATCH (s:PathwayStep) RETURN count(s) AS steps }
CALL () { MATCH ()-[r:CONNECTED_TO]->() RETURN count(r) AS interchanges }
RETURN custodians, lines, steps, interchanges;


// -----------------------------------------------------------------------------
// 2) Line index for the map legend / left panel
// -----------------------------------------------------------------------------
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


// -----------------------------------------------------------------------------
// 3) Parameter example: inspect one line
// -----------------------------------------------------------------------------
WITH 'line:custodian:act-health' AS lineId
MATCH (l:ProcessLine {id: lineId})<-[:OFFERS_LINE]-(c:Custodian)
RETURN
  l.id AS lineId,
  l.name AS lineName,
  c.id AS custodianId,
  c.name AS custodianName;


// -----------------------------------------------------------------------------
// 4) Ordered steps for one line
// -----------------------------------------------------------------------------
WITH 'line:custodian:act-health' AS lineId
MATCH (l:ProcessLine {id: lineId})-[hs:HAS_STEP]->(s:PathwayStep)
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


// -----------------------------------------------------------------------------
// 5) Derived step-to-step chain edges for one line
// -----------------------------------------------------------------------------
WITH 'line:custodian:act-health' AS lineId
MATCH (l:ProcessLine {id: lineId})-[h1:HAS_STEP]->(s1:PathwayStep)
MATCH (l)-[h2:HAS_STEP]->(s2:PathwayStep)
WHERE h2.order = h1.order + 1
RETURN
  l.id AS lineId,
  s1.id AS fromStepId,
  s2.id AS toStepId,
  h1.order AS fromOrder,
  h2.order AS toOrder,
  coalesce(s2.lane, h2.lane, 'Custodian') AS toLane
ORDER BY fromOrder, toOrder;


// -----------------------------------------------------------------------------
// 6) Datasets attached to one line / custodian
// -----------------------------------------------------------------------------
WITH 'line:custodian:act-health' AS lineId
MATCH (l:ProcessLine {id: lineId})<-[:OFFERS_LINE]-(c:Custodian)-[:HAS_DATASET]->(d:Dataset)
WHERE d.name IS NOT NULL
RETURN
  l.id AS lineId,
  c.name AS custodianName,
  d.id AS datasetId,
  d.name AS datasetName,
  d.description AS datasetDescription,
  d.identifiable AS identifiable,
  d.linkable AS linkable
ORDER BY datasetName;


// -----------------------------------------------------------------------------
// 7) Explicit interchange links between lines
// -----------------------------------------------------------------------------
MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)
WHERE l1.id <> l2.id
RETURN
  l1.id AS fromLineId,
  l1.name AS fromLineName,
  l2.id AS toLineId,
  l2.name AS toLineName,
  r.segment AS reasonSegment,
  r.matchType AS matchType,
  r.matchScore AS matchScore
ORDER BY matchScore DESC, fromLineName, toLineName;


// -----------------------------------------------------------------------------
// 8) Interchange links anchored to the first step of each line
// -----------------------------------------------------------------------------
MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)-[h1:HAS_STEP]->(s1:PathwayStep)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)-[h2:HAS_STEP]->(s2:PathwayStep)
WHERE h1.order = 1
  AND h2.order = 1
  AND l1.id <> l2.id
RETURN
  s1.id AS fromStepId,
  s1.text AS fromStepTitle,
  l1.id AS fromLineId,
  l1.name AS fromLineName,
  s2.id AS toStepId,
  s2.text AS toStepTitle,
  l2.id AS toLineId,
  l2.name AS toLineName,
  r.segment AS reasonSegment,
  r.matchType AS matchType,
  r.matchScore AS matchScore
ORDER BY matchScore DESC, fromLineName, toLineName;


// -----------------------------------------------------------------------------
// 9) Full payload for one line: step nodes + chain edges
// -----------------------------------------------------------------------------
WITH 'line:custodian:act-health' AS lineId
MATCH (l:ProcessLine {id: lineId})-[hs:HAS_STEP]->(s:PathwayStep)
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


// -----------------------------------------------------------------------------
// 10) Full trainline-map payload for all lines
// -----------------------------------------------------------------------------
MATCH (c:Custodian)-[:OFFERS_LINE]->(l:ProcessLine)
MATCH (l)-[hs:HAS_STEP]->(s:PathwayStep)
WITH c, l, s, hs
ORDER BY l.id, hs.order, s.id
WITH
  collect(DISTINCT {
    id: s.id,
    type: 'PathwayStep',
    lineId: l.id,
    lineName: l.name,
    custodianId: c.id,
    custodianName: c.name,
    stepOrder: hs.order,
    lane: coalesce(s.lane, hs.lane, 'Custodian'),
    title: s.text,
    actor: s.actor,
    channel: s.channel,
    timeline: s.timeline
  }) AS nodes,
  collect({
    lineId: l.id,
    lineName: l.name,
    stepId: s.id,
    stepOrder: hs.order
  }) AS ordered
WITH
  nodes,
  [a IN ordered
   WHERE any(b IN ordered WHERE b.lineId = a.lineId AND b.stepOrder = a.stepOrder + 1) |
   {
     from: a.stepId,
     to: head([b IN ordered WHERE b.lineId = a.lineId AND b.stepOrder = a.stepOrder + 1 | b.stepId]),
     type: 'NEXT_IN_LINE',
     lineId: a.lineId,
     lineName: a.lineName
   }
  ] AS inLineEdges
MATCH (c1:Custodian)-[r:CONNECTED_TO]->(c2:Custodian)
MATCH (c1)-[:OFFERS_LINE]->(l1:ProcessLine)-[h1:HAS_STEP]->(s1:PathwayStep)
MATCH (c2)-[:OFFERS_LINE]->(l2:ProcessLine)-[h2:HAS_STEP]->(s2:PathwayStep)
WHERE h1.order = 1
  AND h2.order = 1
WITH
  nodes,
  inLineEdges,
  collect(DISTINCT {
    from: s1.id,
    to: s2.id,
    type: 'INTERCHANGE',
    fromLineId: l1.id,
    fromLineName: l1.name,
    toLineId: l2.id,
    toLineName: l2.name,
    score: r.matchScore,
    matchType: r.matchType,
    reasonSegment: r.segment
  }) AS branchEdges
RETURN
  nodes,
  inLineEdges,
  branchEdges;


// -----------------------------------------------------------------------------
// 11) Lane summary for map header bands
// -----------------------------------------------------------------------------
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


// -----------------------------------------------------------------------------
// 12) Rebuild persistent NEXT_STEP relationships for all lines
// -----------------------------------------------------------------------------
// Run the delete block first if you want to fully regenerate NEXT_STEP edges.

MATCH ()-[r:NEXT_STEP]->()
DELETE r;

MATCH (l:ProcessLine)-[hs:HAS_STEP]->(s:PathwayStep)
WITH l, hs, s
ORDER BY l.id, hs.order, s.id
WITH
  l,
  collect({
    step: s,
    stepOrder: hs.order,
    lane: coalesce(s.lane, hs.lane, 'Custodian')
  }) AS orderedSteps
UNWIND range(0, size(orderedSteps) - 2) AS idx
WITH
  l,
  orderedSteps[idx].step AS currentStep,
  orderedSteps[idx].stepOrder AS currentOrder,
  orderedSteps[idx + 1].step AS nextStep,
  orderedSteps[idx + 1].stepOrder AS nextOrder,
  orderedSteps[idx + 1].lane AS nextLane
MERGE (currentStep)-[r:NEXT_STEP]->(nextStep)
SET
  r.lineId = l.id,
  r.lineName = l.name,
  r.fromOrder = currentOrder,
  r.toOrder = nextOrder,
  r.lane = nextLane
RETURN count(r) AS nextStepRelationshipsCreated;


// -----------------------------------------------------------------------------
// 13) Check NEXT_STEP counts
// -----------------------------------------------------------------------------
MATCH ()-[r:NEXT_STEP]->()
RETURN count(r) AS nextStepCount;


// -----------------------------------------------------------------------------
// 14) Graph-view query for one line using NEXT_STEP
// -----------------------------------------------------------------------------
WITH 'ACT Health' AS custodianName
MATCH p =
  (:Custodian {name: custodianName})
  -[:OFFERS_LINE]->
  (:ProcessLine)
  -[:HAS_STEP]->
  (:PathwayStep)-[:NEXT_STEP*0..20]-(:PathwayStep)
RETURN p;


// -----------------------------------------------------------------------------
// 15) Graph-view query for a single ordered chain only
// -----------------------------------------------------------------------------
WITH 'ACT Health' AS custodianName
MATCH (:Custodian {name: custodianName})-[:OFFERS_LINE]->(:ProcessLine)-[:HAS_STEP]->(start:PathwayStep)
WHERE NOT EXISTS {
  MATCH (:PathwayStep)-[:NEXT_STEP]->(start)
}
MATCH p = (start)-[:NEXT_STEP*0..20]->(:PathwayStep)
RETURN p;



// -----------------------------------------------------------------------------
// 12) graph view
// -----------------------------------------------------------------------------

//MATCH p1 = (c:Custodian)-[:OFFERS_LINE]->(l:ProcessLine)-[:HAS_STEP]->(s:PathwayStep)
//WITH collect(p1) AS linePaths
//MATCH p2 = (c1:Custodian)-[:CONNECTED_TO]->(c2:Custodian)
//RETURN linePaths, collect(p2) AS interchangePaths;



// -----------------------------------------------------------------------------
// 13) example: one line graph view
// -----------------------------------------------------------------------------
WITH 'ACT Health' AS custodianName
MATCH p1 = (c:Custodian {name: custodianName})-[:OFFERS_LINE]->(:ProcessLine)-[:HAS_STEP]->(:PathwayStep)
OPTIONAL MATCH p2 = (c)-[:CONNECTED_TO]->(other:Custodian)-[:OFFERS_LINE]->(:ProcessLine)
RETURN p1, p2;
