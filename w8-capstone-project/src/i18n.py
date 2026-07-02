"""Minimal UI string catalog for FR / EN / PT.

French is the primary language (the sitreps are in French). Keys are referenced
by the Streamlit app; the assistant's own replies are localised by the model.
"""
from __future__ import annotations

STRINGS = {
    "fr": {
        "app_title": "Analyse des SitReps - Epidemie MVE/BVD (RDC)",
        "nav_chat": "Assistant",
        "nav_quality": "Qualite des donnees",
        "nav_topics": "Defis et lacunes",
        "language": "Langue",
        "ask_placeholder": "Posez une question sur les rapports de situation...",
        "single_assess": "Evaluer un rapport",
        "compare_assess": "Comparer deux rapports",
        "select_report": "Choisir un rapport",
        "select_report_a": "Rapport A",
        "select_report_b": "Rapport B",
        "run": "Lancer",
        "sources": "Sources",
        "no_data": "Aucune donnee indexee. Lancez l'ingestion d'abord.",
        "extract_topics": "Extraire les defis et lacunes",
    },
    "en": {
        "app_title": "SitRep Analysis - EVD/BVD Outbreak (DRC)",
        "nav_chat": "Assistant",
        "nav_quality": "Data quality",
        "nav_topics": "Gaps and challenges",
        "language": "Language",
        "ask_placeholder": "Ask a question about the situation reports...",
        "single_assess": "Assess one report",
        "compare_assess": "Compare two reports",
        "select_report": "Select a report",
        "select_report_a": "Report A",
        "select_report_b": "Report B",
        "run": "Run",
        "sources": "Sources",
        "no_data": "No indexed data. Run ingestion first.",
        "extract_topics": "Extract gaps and challenges",
    },
    "pt": {
        "app_title": "Analise de SitReps - Surto de DVE/BVD (RDC)",
        "nav_chat": "Assistente",
        "nav_quality": "Qualidade dos dados",
        "nav_topics": "Lacunas e desafios",
        "language": "Idioma",
        "ask_placeholder": "Faca uma pergunta sobre os relatorios de situacao...",
        "single_assess": "Avaliar um relatorio",
        "compare_assess": "Comparar dois relatorios",
        "select_report": "Selecionar um relatorio",
        "select_report_a": "Relatorio A",
        "select_report_b": "Relatorio B",
        "run": "Executar",
        "sources": "Fontes",
        "no_data": "Nenhum dado indexado. Execute a ingestao primeiro.",
        "extract_topics": "Extrair lacunas e desafios",
    },
}


def t(lang: str, key: str) -> str:
    return STRINGS.get(lang, STRINGS["fr"]).get(key, key)
