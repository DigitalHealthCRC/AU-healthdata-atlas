

WITH 'ACT Health' AS custodianName
MATCH p =
  (:Custodian {name: custodianName})
  -[:OFFERS_LINE]->
  (:ProcessLine)
  -[:HAS_STEP]->
  (:PathwayStep)-[:NEXT_STEP*0..20]-(:PathwayStep)
RETURN p;

