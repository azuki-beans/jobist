"""Ricerca degli annunci con Claude: web_search per trovarli, poi estrazione in JSON."""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import anthropic

from jobist.config import Settings
from jobist.store import Annuncio

logger = logging.getLogger(__name__)

# Il server può fermare il ciclo di ricerca con pause_turn: lo riprendiamo al massimo N volte.
_MAX_CONTINUAZIONI = 5
# Se il modello rifiuta, l'API riprova sul modello di fallback consigliato.
_BETAS = ["server-side-fallback-2026-07-01"]

_SCHEMA_ANNUNCI = {
    "type": "object",
    "properties": {
        "annunci": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL diretto all'annuncio"},
                    "titolo": {"type": "string", "description": "Titolo della posizione"},
                    "fonte": {"type": "string", "description": "Sito o azienda di provenienza"},
                    "sommario": {
                        "type": "string",
                        "description": "1-2 frasi in italiano sul perché è pertinente",
                    },
                },
                "required": ["url", "titolo", "fonte", "sommario"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["annunci"],
    "additionalProperties": False,
}


def costruisci_brief(s: Settings) -> str:
    """Compone in un elenco il profilo (JOB_SEARCH_QUERY) e i criteri valorizzati."""
    criteri = [
        ("Profilo", s.job_search_query),
        ("Ruolo", s.job_search_ruolo),
        ("Stack/competenze", s.job_search_stack),
        ("Seniority", s.job_search_seniority),
        ("Modalità di lavoro", s.job_search_modalita),
        ("Località", s.job_search_localita),
        ("RAL minima", s.job_search_ral_minima),
        ("Da escludere", s.job_search_esclusioni),
    ]
    return "\n".join(
        f"- {etichetta}: {valore.strip()}" for etichetta, valore in criteri if valore.strip()
    )


def web_search_tool(s: Settings) -> dict:
    tool: dict = {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": s.web_search_max_uses,
    }
    # allowed_domains e blocked_domains sono alternativi: allowed ha la precedenza.
    if s.web_search_allowed_domains:
        tool["allowed_domains"] = s.web_search_allowed_domains
        if s.web_search_blocked_domains:
            logger.warning("WEB_SEARCH_BLOCKED_DOMAINS ignorato: vale WEB_SEARCH_ALLOWED_DOMAINS")
    elif s.web_search_blocked_domains:
        tool["blocked_domains"] = s.web_search_blocked_domains

    luogo = {
        "country": s.web_search_country,
        "city": s.web_search_city,
        "region": s.web_search_region,
    }
    luogo = {k: v for k, v in luogo.items() if v}
    if luogo:
        tool["user_location"] = {"type": "approximate", "timezone": s.timezone, **luogo}
    return tool


def _prompt(s: Settings, brief: str, gia_visti: list[str]) -> str:
    oggi = datetime.now(ZoneInfo(s.timezone)).date()
    soglia = oggi - timedelta(days=s.job_search_giorni)
    prompt = (
        "Cerca offerte di lavoro davvero pertinenti per questo profilo.\n"
        f"Oggi è il {oggi:%d/%m/%Y}.\n\n"
        f"Criteri:\n{brief}\n\n"
        "Regole:\n"
        "- Usa fonti diverse: job board, pagine carriere delle aziende, LinkedIn.\n"
        f"- Solo annunci pubblicati dopo il {soglia:%d/%m/%Y} e ancora aperti.\n"
        "- Rispetta le esclusioni indicate nei criteri.\n"
        "- Ogni risultato è un singolo annuncio con URL diretto, non una pagina di elenco.\n"
        f"- Al massimo {s.job_search_max_risultati} risultati, i più rilevanti.\n"
        "- Per ognuno: url, titolo, fonte e 1-2 frasi in italiano con il motivo concreto "
        "della pertinenza (stack, seniority, modalità, RAL)."
    )
    if gia_visti:
        prompt += "\n\nQuesti annunci li conosco già, non riproporli:\n" + "\n".join(gia_visti)
    return prompt


def _crea(client: anthropic.Anthropic, s: Settings, **kwargs):
    return client.beta.messages.create(
        model=s.anthropic_model,
        max_tokens=16000,
        betas=_BETAS,
        fallbacks="default",
        **kwargs,
    )


def cerca_annunci(s: Settings, gia_visti: list[str] | None = None) -> list[Annuncio]:
    brief = costruisci_brief(s)
    if not brief:
        raise ValueError("Nessun criterio di ricerca: imposta JOB_SEARCH_QUERY o i JOB_SEARCH_*")

    client = anthropic.Anthropic(api_key=s.anthropic_api_key.get_secret_value(), timeout=900)
    prompt = _prompt(s, brief, gia_visti or [])
    messages: list[dict] = [{"role": "user", "content": prompt}]

    # Fase 1: ricerca sul web.
    risposta = _crea(
        client,
        s,
        thinking={"type": "adaptive"},
        output_config={"effort": s.anthropic_effort},
        tools=[web_search_tool(s)],
        messages=messages,
    )
    for _ in range(_MAX_CONTINUAZIONI):
        if risposta.stop_reason != "pause_turn":
            break
        # Si rimanda la risposta così com'è: il server riprende da dove si era fermato.
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": risposta.content},
        ]
        risposta = _crea(
            client,
            s,
            thinking={"type": "adaptive"},
            output_config={"effort": s.anthropic_effort},
            tools=[web_search_tool(s)],
            messages=messages,
        )
    logger.info("Ricerca terminata (stop_reason=%s, request_id=%s)",
                risposta.stop_reason, risposta._request_id)

    if risposta.stop_reason == "refusal":
        logger.warning("Ricerca rifiutata dal modello: %s", risposta.stop_details)
        return []

    testo = "\n".join(b.text for b in risposta.content if b.type == "text").strip()
    if not testo:
        logger.warning("La ricerca non ha prodotto testo")
        return []

    # Fase 2: estrazione strutturata (output vincolato allo schema JSON).
    estrazione = _crea(
        client,
        s,
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": _SCHEMA_ANNUNCI},
        },
        messages=[{
            "role": "user",
            "content": "Estrai gli annunci di lavoro da questo testo. "
                       "Includi solo quelli con un URL valido.\n\n" + testo,
        }],
    )
    if estrazione.stop_reason == "refusal":
        logger.warning("Estrazione rifiutata dal modello: %s", estrazione.stop_details)
        return []

    payload = next((b.text for b in estrazione.content if b.type == "text"), "{}")
    try:
        dati = json.loads(payload)
    except json.JSONDecodeError:
        logger.exception("JSON di estrazione non valido: %s", payload[:500])
        return []

    annunci = []
    for a in dati.get("annunci", [])[: s.job_search_max_risultati]:
        url = a.get("url", "").strip()
        if url.startswith(("http://", "https://")):
            annunci.append(Annuncio(
                url=url,
                titolo=a.get("titolo", "").strip() or url,
                fonte=a.get("fonte", "").strip(),
                sommario=a.get("sommario", "").strip(),
            ))
    return annunci
