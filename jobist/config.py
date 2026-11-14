"""Configurazione da variabili d'ambiente (e, in locale, dal file .env)."""

from functools import cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

type CsvList = Annotated[list[str], NoDecode]


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Claude API ---------------------------------------------------------
    anthropic_api_key: SecretStr
    anthropic_model: str = "claude-opus-5-5"
    # low | medium | high | xhigh | max (su Opus 5.5 il default dell'API è medium)
    anthropic_effort: str = "high"

    # --- Criteri di ricerca (i campi vuoti vengono ignorati) ------------------
    job_search_query: str = ""  # profilo in testo libero, sempre incluso nel brief
    job_search_ruolo: str = ""
    job_search_stack: str = ""
    job_search_seniority: str = ""
    job_search_modalita: str = ""
    job_search_localita: str = ""
    job_search_ral_minima: str = ""
    job_search_esclusioni: str = ""
    job_search_giorni: int = Field(14, ge=1)
    job_search_max_risultati: int = Field(10, ge=1)

    # --- Tool web_search ----------------------------------------------------
    web_search_max_uses: int = Field(8, ge=1)
    web_search_allowed_domains: CsvList = []
    web_search_blocked_domains: CsvList = []
    web_search_country: str = "IT"
    web_search_city: str = ""
    web_search_region: str = ""
    timezone: str = "Europe/Rome"

    # --- Database -----------------------------------------------------------
    # File SQLite locale. Se JOBIST_DB_GCS_URI è valorizzato, viene scaricato dal
    # bucket all'avvio e ricaricato a fine esecuzione (Cloud Run Job).
    jobist_db_path: str = "jobist.sqlite3"
    jobist_db_gcs_uri: str = ""  # es. gs://mio-bucket/jobist.sqlite3

    # --- Notifiche (Apprise) --------------------------------------------------
    # Uno o più URL Apprise separati da spazio o virgola: https://github.com/caronc/apprise/wiki
    notify_urls: SecretStr = SecretStr("")

    _split = field_validator(
        "web_search_allowed_domains", "web_search_blocked_domains", mode="before"
    )(_split_csv)

    @field_validator("anthropic_effort")
    @classmethod
    def _effort_valido(cls, value: str) -> str:
        if value not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("ANTHROPIC_EFFORT deve essere low, medium, high, xhigh o max")
        return value


@cache
def get_settings() -> Settings:
    return Settings()
