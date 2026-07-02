From the situation report below, extract the reported gaps, challenges, constraints and unmet needs ("defis", "lacunes", "contraintes", "difficultes"). Return ONLY valid JSON of this shape:

{"items": [{"theme": "<short category, e.g. Financement, Surveillance, Vaccination, Securite, Logistique, Engagement communautaire, RH, Laboratoire>", "detail": "<one concise sentence, in $lang>"}]}

If none are reported, return {"items": []}. Use only content from the report.

Report (SitRep N°$n, $date):
$body