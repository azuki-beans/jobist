import sqlite3

import pytest

from jobist.config import Settings
from jobist.notify import _urls, componi_digest
from jobist.search import costruisci_brief, web_search_tool
from jobist.store import Annuncio, Archivio


@pytest.fixture
def settings(monkeypatch) -> Settings:
    for var in ("JOB_SEARCH_QUERY", "JOB_SEARCH_RUOLO", "JOB_SEARCH_STACK"):
        monkeypatch.delenv(var, raising=False)
    return Settings(_env_file=None, anthropic_api_key="sk-test")


@pytest.fixture
def archivio() -> Archivio:
    return Archivio(sqlite3.connect(":memory:"))


def test_dedup_e_invio(archivio):
    a = Annuncio(url="https://x.it/1", titolo="Dev")
    assert archivio.aggiungi([a, Annuncio(url="https://x.it/2", titolo="Ops")]) == 2
    assert archivio.aggiungi([a]) == 0  # già visto

    da_inviare = archivio.da_inviare()
    assert [x.url for x in da_inviare] == ["https://x.it/1", "https://x.it/2"]
    archivio.segna_inviati(da_inviare)
    assert archivio.da_inviare() == []
    assert set(archivio.url_recenti()) == {"https://x.it/1", "https://x.it/2"}


def test_brief_usa_criteri_o_query(settings):
    assert costruisci_brief(settings) == ""
    settings.job_search_query = "Python remoto"
    assert costruisci_brief(settings) == "- Profilo: Python remoto"
    settings.job_search_ruolo = "Backend"
    assert costruisci_brief(settings) == "- Ruolo: Backend"


def test_domini_csv_e_precedenza(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_ALLOWED_DOMAINS", "linkedin.com, indeed.it")
    monkeypatch.setenv("WEB_SEARCH_BLOCKED_DOMAINS", "spam.com")
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    tool = web_search_tool(s)
    assert tool["allowed_domains"] == ["linkedin.com", "indeed.it"]
    assert "blocked_domains" not in tool
    assert tool["user_location"]["country"] == "IT"


def test_digest_escape_html():
    titolo, corpo = componi_digest([Annuncio(url="https://x.it/?a=1&b=2", titolo="<Dev>")], "01/01")
    assert titolo == "Jobist: 1 annunci (01/01)"
    assert "&lt;Dev&gt;" in corpo and "a=1&amp;b=2" in corpo


def test_notify_urls_multipli():
    assert _urls("mailto://a, tgram://b  ntfy://c\n") == ["mailto://a", "tgram://b", "ntfy://c"]
