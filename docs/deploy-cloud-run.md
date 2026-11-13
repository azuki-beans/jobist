# Deploy su Cloud Run Job

Configurazione una tantum. Sostituisci `PROJECT`, `REGION` e il nome del bucket.

```bash
PROJECT=mio-progetto
REGION=europe-west1
BUCKET=$PROJECT-jobist
SA=jobist@$PROJECT.iam.gserviceaccount.com

gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  secretmanager.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com --project $PROJECT
```

## 1. Immagine

Le immagini stanno su un repository Artifact Registry del progetto, nella stessa regione del job:

```bash
gcloud artifacts repositories create jobist --project $PROJECT --location $REGION \
  --repository-format docker

IMAGE=$REGION-docker.pkg.dev/$PROJECT/jobist/jobist
gcloud builds submit --project $PROJECT --region $REGION --tag $IMAGE:latest
```

La prima immagine si costruisce così (o in locale su una macchina amd64); poi ci pensa il
workflow GitHub (sezione 5), che cambia solo l'immagine del job.

## 2. Bucket, service account e segreti

```bash
gcloud storage buckets create gs://$BUCKET --project $PROJECT --location $REGION \
  --uniform-bucket-level-access

gcloud iam service-accounts create jobist --project $PROJECT
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member serviceAccount:$SA --role roles/storage.objectUser

printf '%s' 'sk-ant-...' | gcloud secrets create anthropic-api-key --project $PROJECT --data-file=-
printf '%s' 'tgram://...' | gcloud secrets create jobist-notify-urls --project $PROJECT --data-file=-
for s in anthropic-api-key jobist-notify-urls; do
  gcloud secrets add-iam-policy-binding $s --project $PROJECT \
    --member serviceAccount:$SA --role roles/secretmanager.secretAccessor
done
```

## 3. Job

`--max-retries 0` e `--tasks 1`: un'esecuzione alla volta, senza ripetere automaticamente le
ricerche, che costano.

```bash
gcloud run jobs create jobist --project $PROJECT --region $REGION \
  --image $IMAGE:latest --service-account $SA \
  --tasks 1 --max-retries 0 --task-timeout 30m --memory 512Mi \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest,NOTIFY_URLS=jobist-notify-urls:latest \
  --set-env-vars "^@^JOBIST_DB_GCS_URI=gs://$BUCKET/jobist.sqlite3@JOB_SEARCH_RUOLO=Backend developer@JOB_SEARCH_STACK=Python, Django@JOB_SEARCH_MODALITA=remoto"

gcloud run jobs execute jobist --project $PROJECT --region $REGION --wait   # prova
```

Il separatore `^@^` serve perché i valori contengono virgole. Per i criteri si può anche usare
`--env-vars-file criteri.yaml`.

## 4. Pianificazione

```bash
gcloud iam service-accounts create jobist-scheduler --project $PROJECT
gcloud run jobs add-iam-policy-binding jobist --project $PROJECT --region $REGION \
  --member serviceAccount:jobist-scheduler@$PROJECT.iam.gserviceaccount.com \
  --role roles/run.invoker

gcloud scheduler jobs create http jobist-giornaliero --project $PROJECT --location $REGION \
  --schedule "0 8 * * *" --time-zone "Europe/Rome" --http-method POST \
  --uri "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/jobist:run" \
  --oauth-service-account-email jobist-scheduler@$PROJECT.iam.gserviceaccount.com
```

## 5. GitHub Actions con Workload Identity Federation

Il workflow `.github/workflows/deploy.yml` parte solo al push di un tag `v*`: costruisce
l'immagine, la pubblica su Artifact Registry e aggiorna il job. Nessuna chiave di service account:
il token OIDC di GitHub viene scambiato con credenziali a breve durata, e GCP lo accetta solo
dall'environment `production` di questo repository.

Service account di deploy, con i soli permessi necessari:

```bash
DEPLOY=github-deploy@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create github-deploy --project $PROJECT

gcloud artifacts repositories add-iam-policy-binding jobist --project $PROJECT --location $REGION \
  --member serviceAccount:$DEPLOY --role roles/artifactregistry.writer
gcloud run jobs add-iam-policy-binding jobist --project $PROJECT --region $REGION \
  --member serviceAccount:$DEPLOY --role roles/run.developer
gcloud iam service-accounts add-iam-policy-binding $SA --project $PROJECT \
  --member serviceAccount:$DEPLOY --role roles/iam.serviceAccountUser
```

Pool e provider WIF, legati a repository ed environment:

```bash
gcloud iam workload-identity-pools create github --location global --project $PROJECT

gcloud iam workload-identity-pools providers create-oidc github \
  --workload-identity-pool github --location global --project $PROJECT \
  --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.environment=assertion.environment" \
  --attribute-condition "assertion.repository_id == 'REPO_ID' && assertion.repository_owner_id == 'OWNER_ID' && assertion.environment == 'production'"

gcloud iam service-accounts add-iam-policy-binding $DEPLOY --project $PROJECT \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository_id/REPO_ID"
```

Usa gli ID numerici di repository e owner (`gh api repos/OWNER/REPO --jq '.id, .owner.id'`), non
il nome: un repository rinominato o ricreato con lo stesso nome non deve ereditare i diritti di
deploy.

Nel repository GitHub:

- **Variables**: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`
  (`projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github`),
  `GCP_DEPLOY_SA`.
- **Environment `production`**: required reviewer, deployment limitati ai tag `v*`.
- **Tag ruleset** su `v*`: solo i maintainer possono creare tag.
- **Actions**: approvazione obbligatoria per i workflow di collaboratori esterni.

## Aggiornare

```bash
git tag v1.2.3 && git push origin v1.2.3
```

Poi approva il deployment su GitHub (Actions → run → *Review deployments*). Il workflow aggiorna
solo l'immagine del job; env, segreti e scheduler restano quelli configurati qui sopra.

I log sono in Cloud Logging, sotto la risorsa `cloud_run_job`.
