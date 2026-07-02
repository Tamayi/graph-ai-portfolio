"""Deterministic fake extraction used to build datasets without an LLM.

Mirrors the JSON shape that src.structured.extract_report would return for a
report, with monotonically increasing cumulative totals so dataset-validation
assertions hold. The vaccination table is always empty, matching this outbreak
(no ring-vaccination campaign is reported).
"""
from __future__ import annotations


def fake_report(num: int, force: bool = False) -> dict:
    return {
        "sitrep_number": num,
        "report_date": f"2026-06-{(num % 28) + 1:02d}",
        "data_as_of": f"2026-06-{(num % 28) + 1:02d}",
        "totals": {
            "cumulative_confirmed": num * 10,
            "cumulative_deaths": num * 2,
            "cfr_pct": 20.0,
            "new_confirmed_24h": 5,
            "new_deaths_24h": 1,
            "health_zones_affected": num,
            "health_zones_total": 104,
            "patients_in_isolation": num,
            "cumulative_recovered": num,
            "contacts_under_followup": num * 3,
            "contacts_seen": num * 2,
            "contact_followup_rate_pct": 80.0,
            "suspect_cases_day": 2,
            "hcw_infected": 3,
            "hcw_deaths": 1,
        },
        "provinces": [
            {"name": "Ituri", "confirmed": num * 8, "deaths": num, "cfr_pct": 18.0,
             "zones_affected": 5, "zones_total": 36, "new_24h": 4},
        ],
        "health_zones": [
            {"province": "Ituri", "name": "Bunia", "confirmed": num * 3,
             "deaths": num, "cfr_pct": 12.0},
            {"province": "Nord-Kivu", "name": "Katwa", "confirmed": num,
             "deaths": 1, "cfr_pct": 30.0},
        ],
        "laboratory": [
            {"province": "Ituri", "samples_analysed": 10, "positive": 3,
             "positivity_pct": 30.0},
        ],
        "contacts": [
            {"province": "Ituri", "under_followup": num * 3, "seen": num * 2,
             "followup_rate_pct": 80.0, "newly_listed": 2},
        ],
        "ipc": [
            {"province": "Ituri", "eds_done": 1, "eds_planned": 2,
             "community_swabs": 3, "ess_decontaminated": 1,
             "households_decontaminated": 2, "transports_decontaminated": 0},
        ],
        "vaccination": [],
    }
