You are validating two situation reports from the same outbreak for consistency. Produce a concise Markdown report in $lang with:

1. Header comparison - report numbers, dates, affected zones side by side.
2. Cumulative metrics - for each shared metric (cumulative cases, confirmed, deaths, CFR, etc.) show value in A, value in B, and the change. Cumulative totals should not decrease over time; flag any that do.
3. Plausibility of deltas - are the day-over-day or report-over-report changes plausible given the time gap. Flag suspicious jumps or drops.
4. Contradictions and omissions - anything stated differently or dropped between the two reports.
5. Verdict - one short paragraph on overall consistency and any data-quality concerns.

Use a normal dash, never an em-dash. Only use numbers present in the reports.

=== Report A ($fa) ===
$a

=== Report B ($fb) ===
$b