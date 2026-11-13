"""Invio del digest tramite Apprise: email, Telegram, Slack, ntfy, webhook, ...

La destinazione si configura con NOTIFY_URLS (uno o più URL Apprise), vedi
https://github.com/caronc/apprise/wiki
"""

import logging
import re
from html import escape

import apprise

from jobist.store import Annuncio

logger = logging.getLogger(__name__)


def _urls(notify_urls: str) -> list[str]:
    return [u for u in re.split(r"[\s,]+", notify_urls) if u]


def componi_digest(annunci: list[Annuncio], data: str) -> tuple[str, str]:
    """Restituisce (titolo, corpo HTML)."""
    titolo = f"Jobist: {len(annunci)} annunci ({data})"
    voci = "".join(
        f'<li><a href="{escape(a.url)}"><strong>{escape(a.titolo)}</strong></a>'
        + (f" <em>({escape(a.fonte)})</em>" if a.fonte else "")
        + (f"<br>{escape(a.sommario)}" if a.sommario else "")
        + "</li>"
        for a in annunci
    )
    return titolo, f"<p>Annunci trovati:</p><ul>{voci}</ul>"


def invia(notify_urls: str, titolo: str, corpo_html: str) -> bool:
    """True se l'invio riesce su tutte le destinazioni configurate."""
    urls = _urls(notify_urls)
    if not urls:
        raise ValueError("NOTIFY_URLS è vuoto: configura almeno una destinazione Apprise")

    client = apprise.Apprise()
    for url in urls:
        if not client.add(url):
            # Non loggare l'URL: contiene credenziali.
            raise ValueError("Un URL in NOTIFY_URLS non è valido o il servizio non è supportato")
    return bool(client.notify(title=titolo, body=corpo_html, body_format=apprise.NotifyFormat.HTML))
