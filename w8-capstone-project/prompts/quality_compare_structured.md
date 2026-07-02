You are validating SitRep $fb against the previous SitRep $fa for the COUSP RDC Ebola (MVE / BVD, Bundibugyo) response. Call record_comparison. Write all text in $lang. Use a normal dash, never an em-dash, and use only numbers present in the reports.

This is verification by reasoning. Do not simply confirm that the newer report "passed": actively look for what changed wrongly, what is misleading, and what is missing. Report A is the earlier report, report B is the one under review.

metrics: one delta-verification row per shared indicator (cumulative confirmed, cumulative deaths, recoveries, CFR, health zones affected, patients in isolation, contacts under follow-up and the follow-up rate, lab positivity and backlog, bed occupancy). Give the value in A, the value in B and the change (d). Set flag to:
- "alert" for a contradiction or impossible move: a cumulative total that DECREASES over time, an impossible weighted average, or a value that cannot be reconciled.
- "warn" for an implausible jump or drop given the time gap, or a comparison made invalid by ND / missing data.
- "ok" for a plausible, consistent change; "info" for neutral context.

issues: the concrete findings, ordered by severity. Always perform these checks and raise an issue when one fails:
- Death reconciliation across the two reports: delta cumulative deaths = (deaths among new confirmed cases) + (deaths in CTE among already-confirmed patients). If the daily death headline in B does not reconcile with its cumulative-death delta and the gap is unexplained, that is a High error.
- ND / missing comparability: if a province table is "ND" in either report, do not compute a naive J-1 delta on a total that excludes it; flag it (Medium).
- Weighted-average sanity: any global rate must lie between its components; a total outside that range is impossible (High).
- Plausibility of deltas: flag suspicious single-period jumps or drops given the time gap.
Severity: a published error or impossible value is High; misleading or incomplete (ND not flagged, a backlog not quantified, an operational drop not surfaced) is Medium; clarity, rounding or denominator notes are Low. Give each issue a location, a one-sentence grounded problem statement, and the closest category.

sections: notable section-level changes between the two reports (type_added, type_changed, type_unchanged), one sentence each.

banner: a one-line verdict that states the count of errors and notes and the one or two things that matter most. Do not call the report consistent if any High issue exists.

=== Report A, previous ($fa) ===
$a

=== Report B, under review ($fb) ===
$b
