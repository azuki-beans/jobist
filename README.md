# jobist

Job batch che ogni giorno cerca annunci di lavoro pertinenti con la **Claude API**
(tool `web_search`) e ti manda un digest con **[Apprise](https://github.com/caronc/apprise)**:
email (SMTP o API come Resend, Brevo, SendGrid, SES), Telegram, Slack, Discord, ntfy e molti altri.

Pensato per girare come **Cloud Run Job** pianificato da Cloud Scheduler, ma è un normale
container: funziona anche con cron, Kubernetes CronJob o a mano.

## Come funziona

1. Claude cerca sul web gli annunci in linea con i tuoi criteri. Gli passa anche gli
   annunci già noti, così non li ripropone.
2. Una seconda chiamata estrae i risultati in JSON strutturato.
3. Gli annunci nuovi finiscono in un piccolo database **SQLite**. L'URL è la chiave, quindi
   non ci sono doppioni.
4. Gli annunci non ancora inviati partono in un unico digest. Se l'invio fallisce restano in
   coda per l'esecuzione successiva.

Su Cloud Run il file SQLite vive su **Google Cloud Storage**: il job lo scarica all'avvio e lo
ricarica alla fine. Il caricamento è condizionato alla versione scaricata, quindi due esecuzioni
sovrapposte non si sovrascrivono.

## Configurazione

Tutto si configura con variabili d'ambiente: vedi [`.env.example`](.env.example).

| Variabile | A cosa serve |
|---|---|
| `ANTHROPIC_API_KEY` | Chiave della Claude API (obbligatoria) |
| `ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT` | Modello (default `claude-opus-5-5`) e profondità della ricerca |
| `NOTIFY_URLS` | Uno o più URL Apprise separati da spazio o virgola ([formati](https://github.com/caronc/apprise/wiki)) |
| `JOB_SEARCH_*` | Criteri: ruolo, stack, seniority, modalità, località, RAL, esclusioni, freschezza, numero massimo |
| `WEB_SEARCH_*` | Numero di ricerche, domini ammessi/esclusi, localizzazione |
| `JOBIST_DB_PATH` | File SQLite locale |
| `JOBIST_DB_GCS_URI` | `gs://bucket/jobist.sqlite3` per tenere il database su GCS |

Esempi di `NOTIFY_URLS`:

```env
NOTIFY_URLS=mailtos://utente:password@smtp.example.com?to=io@example.com
NOTIFY_URLS=tgram://BOT_TOKEN/CHAT_ID
NOTIFY_URLS=ntfy://ntfy.sh/mio-topic-segreto, tgram://BOT_TOKEN/CHAT_ID
```

## Uso in locale

```bash
poetry install
cp .env.example .env          # poi compila ANTHROPIC_API_KEY, NOTIFY_URLS e i criteri

poetry run jobist test-notifica   # verifica NOTIFY_URLS
poetry run jobist run --dry-run   # cerca e stampa il digest senza inviarlo
poetry run jobist run             # cerca e invia
poetry run jobist run --solo-invio  # invia solo gli annunci in coda, senza cercare
```

Oppure con il container:

```bash
podman build -t jobist .
podman run --rm --env-file .env -v jobist-data:/data jobist run
```

## Deploy su Cloud Run

Vedi [`docs/deploy-cloud-run.md`](docs/deploy-cloud-run.md).

## Costi

L'infrastruttura (Cloud Run Job una volta al giorno, Scheduler, un file su GCS) rientra di norma
nel free tier di Google Cloud. La voce principale è la Claude API: token e ricerche web.
`ANTHROPIC_EFFORT` e `WEB_SEARCH_MAX_USES` sono le leve per contenerla.

## Sviluppo

```bash
poetry run ruff check .
poetry run pytest
```

Il deploy parte solo al push di un tag `v*`: build su Artifact Registry e aggiornamento del
Cloud Run Job, dopo l'approvazione manuale nell'environment GitHub `production`.

## Licenza

MIT
