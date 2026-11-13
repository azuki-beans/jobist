# CLAUDE.md: jobist

Job batch open source (MIT): cerca annunci di lavoro con la Claude API (`web_search`) e invia
un digest con Apprise. **Non è un'app Django.** È un pacchetto Python con una CLI
(`python -m jobist run`) che gira come **Cloud Run Job**, pianificato da Cloud Scheduler.

## Scelte (novembre 2026)
- Prima versione Django + Celery + beat archiviata: per un batch giornaliero era sovradimensionata.
- **DB**: SQLite (`jobist/store.py`), sincronizzato su GCS se c'è `JOBIST_DB_GCS_URI`.
  L'upload usa `if_generation_match` come lock ottimistico. Niente Cloud SQL.
- **Notifiche**: Apprise via `NOTIFY_URLS`, una o più destinazioni. L'utente sceglie il canale.
  La regola "niente SMTP" di SASA non si applica qui: SMTP è solo una delle opzioni di Apprise.
- **Claude**: `claude-opus-5-5`, adaptive thinking, `web_search_20260209`, gestione di
  `pause_turn`, `fallbacks="default"` (beta `server-side-fallback-2026-07-01`) e una seconda
  chiamata con output `json_schema` per l'estrazione. SDK `anthropic` 2.x.
- Configurazione con `pydantic-settings` (`jobist/config.py`). Le liste CSV usano `NoDecode`.

## Comandi
- `poetry run pytest`, `poetry run ruff check .`
- `poetry run jobist run --dry-run`: chiama davvero l'API, quindi **costa**.
- Container: `podman compose -f stacks/stack_local.yml run --rm jobist`.
- Release: tag `v*` → `.github/workflows/deploy.yml` (come coperni): build solo amd64, push su
  Artifact Registry (`<region>-docker.pkg.dev/<project>/jobist/jobist`) e `gcloud run jobs update`
  (solo immagine). Gira nell'environment GitHub `production` (approvazione manuale), auth con
  Workload Identity Federation, nessuna chiave. Variabili repo `GCP_PROJECT_ID`,
  `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`. Setup in `docs/deploy-cloud-run.md`.

## Identità Git
Progetto open source → account **marcotn**.
