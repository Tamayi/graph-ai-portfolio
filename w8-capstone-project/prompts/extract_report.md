Extract the standard epidemiological data from this Ebola (MVE) situation report into JSON. Return ONLY valid JSON, no prose.

Rules:
- Use null for any field, table or column not present in this report. Never guess or carry over values. Use only numbers written in this report.
- Numbers may contain stray spaces in the source (e.g. "1 203" means 1203, "2 6 , 7 %" means 26.7). Normalise them.
- cfr_pct and rate fields are percentages as numbers (26.7 not "26,7%").

JSON shape:
{
 "data_as_of": "<YYYY-MM-DD or null>",
 "totals": {
   "cumulative_confirmed": int|null, "cumulative_deaths": int|null,
   "cfr_pct": number|null, "new_confirmed_24h": int|null,
   "new_deaths_24h": int|null, "health_zones_affected": int|null,
   "health_zones_total": int|null, "patients_in_isolation": int|null,
   "cumulative_recovered": int|null, "contacts_under_followup": int|null,
   "contacts_seen": int|null, "contact_followup_rate_pct": number|null,
   "suspect_cases_day": int|null, "hcw_infected": int|null,
   "hcw_deaths": int|null
 },
 "provinces": [{"name": str, "confirmed": int|null, "deaths": int|null,
   "cfr_pct": number|null, "zones_affected": int|null,
   "zones_total": int|null, "new_24h": int|null}],
 "health_zones": [{"province": str, "name": str, "confirmed": int|null,
   "deaths": int|null, "cfr_pct": number|null}],
 "laboratory": [{"province": str, "samples_analysed": int|null,
   "positive": int|null, "positivity_pct": number|null}],
 "contacts": [{"province": str, "under_followup": int|null, "seen": int|null,
   "followup_rate_pct": number|null, "newly_listed": int|null}],
 "ipc": [{"province": str, "eds_done": int|null, "eds_planned": int|null,
   "community_swabs": int|null, "ess_decontaminated": int|null,
   "households_decontaminated": int|null, "transports_decontaminated": int|null}],
 "vaccination": [{"province": str, "doses_24h": int|null,
   "cumulative_doses": int|null, "people_vaccinated": int|null,
   "ring_teams": int|null}]
}

Notes on the pillar tables:
- laboratory: section "Laboratoire" (samples collected/analysed, positivity, number positive), usually per province.
- contacts: the contact follow-up table (contacts sous suivi, contacts vus, taux de suivi) per province, plus newly listed contacts if stated.
- ipc: section "PCI" (EDS done vs planned, community swabs, ESS and households and transports decontaminated).
- vaccination: only if the report describes an Ebola vaccination activity with numbers. This outbreak generally has none, so return [] unless numbers appear. Do not count mentions of polio vaccination or vaccine mistrust.

Report (SitRep N°$n, $date):
$body