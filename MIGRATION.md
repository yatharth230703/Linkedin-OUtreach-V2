# Migration: persistent state + CI/CD

This document captures the one-time bootstrap steps to move from the current
"everything in the container's writable layer" setup to:

1. All cookies, config, flags, status, logs, and uploaded templates persisted
   on the VM's `/mnt/bot-data/state` disk via `/app/state` mount.
2. Single source of truth for `docker run` flags in `scripts/run_container.sh`.
3. GitHub Actions workflow (`.github/workflows/deploy.yml`) auto-deploys on
   push to `main`.

You only need to do this **once**. After that, every push to `main` deploys
itself with no manual steps.

## TL;DR sequence

1. Create CI service account + grant roles
2. Drop the SA key into the GitHub repo as `GCP_SA_KEY` secret
3. `terraform import` + `terraform apply` (idempotent — only adds firewall rules)
4. Copy `scripts/run_container.sh` and `scripts/redeploy.sh` to the VM at `/opt/linkedin-bot/`
5. Stop the old container, run the new one with the new mount layout
6. Re-sync cookies via the extension
7. Push a no-op commit and watch the workflow deploy itself

## 1. Service account for CI

```bash
PROJECT=optimum-beach-489223-h7
SA_NAME=linkedin-bot-ci
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA_NAME" \
  --display-name="LinkedIn Bot CI Deploy" \
  --project="$PROJECT"

# Roles:
#  - artifactregistry.writer  : push images to Artifact Registry
#  - compute.instanceAdmin.v1 : ssh / scp via gcloud
#  - iap.tunnelResourceAccessor : use IAP tunnel (no public SSH needed)
#  - iam.serviceAccountUser   : impersonate the bot SA when running gcloud (needed for SSH)
for role in \
    roles/artifactregistry.writer \
    roles/compute.instanceAdmin.v1 \
    roles/iap.tunnelResourceAccessor \
    roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$role"
done

# Generate key
gcloud iam service-accounts keys create gcp-sa-key.json \
  --iam-account="$SA_EMAIL"
```

Open `gcp-sa-key.json`, copy the entire contents, and paste it into a new
GitHub repo secret named `GCP_SA_KEY` (Settings → Secrets and variables →
Actions → New repository secret). **Then delete the local file.**

## 2. Apply Terraform

```bash
cd terraform

# Import the existing manually-created allow-ssh firewall so terraform tracks it.
terraform import google_compute_firewall.ssh allow-ssh

# Plan should now show only the new allow-ssh-iap rule to add.
terraform plan

# Apply.
terraform apply
```

The `lifecycle.ignore_changes = [metadata_startup_script, ...]` block in
`main.tf` ensures terraform will *never* recreate the VM on a startup-script
change. Day-to-day deploys go through the GitHub Actions workflow only.

## 3. One-time VM migration to the new mount layout

The currently-running container (3 weeks old) only mounts `browser_profiles`,
which is wiped on every login anyway and contains nothing valuable. The
cookies inside it can be re-synced via the extension after the swap.

SSH into the VM (your IP is in `allow-ssh`):

```bash
gcloud compute ssh linkedin-bot --zone=asia-south1-a
```

On the VM, copy the new launcher and redeploy script into place. From your
laptop, in another terminal:

```bash
gcloud compute scp --zone=asia-south1-a \
  scripts/run_container.sh scripts/redeploy.sh \
  linkedin-bot:/tmp/

# Back on the VM:
sudo install -d /opt/linkedin-bot
sudo install -m 755 /tmp/run_container.sh /tmp/redeploy.sh /opt/linkedin-bot/
```

Build + push the first new image manually (the GitHub Actions workflow will
do this automatically from the next push onward):

```bash
# From your laptop, at the project root:
gcloud builds submit \
  --tag asia-south1-docker.pkg.dev/optimum-beach-489223-h7/linkedin-bot/bot:bootstrap \
  .
```

Then on the VM, run the redeploy with that bootstrap tag:

```bash
sudo /opt/linkedin-bot/redeploy.sh \
  asia-south1-docker.pkg.dev/optimum-beach-489223-h7/linkedin-bot/bot:bootstrap
```

This will:
1. Stop and remove the old container
2. Pull the new image
3. Run a new container with `/mnt/bot-data/state:/app/state` mounted
4. Health-check the API
5. Append a structured entry to `/mnt/bot-data/state/logs/deploy.log`

## 4. Re-sync cookies

The new container starts with an empty `/app/state/cookies/`. To populate it:

1. Open the Chrome extension while logged into LinkedIn in your normal browser
2. Set the account name (e.g. `yatharth bisht`)
3. Click **Sync LinkedIn Cookies**
4. Repeat for `maurice` and `leon` from their respective LinkedIn sessions

The extension POSTs to `/api/cookies`, which writes to
`/app/state/cookies/cookies_<slug>.json` — backed by the persistent disk, so
this only ever needs to happen once per account (or whenever LinkedIn
invalidates the session).

## 5. First CI/CD deploy

Push a no-op commit to `main`:

```bash
git commit --allow-empty -m "Trigger first CI deploy"
git push origin main
```

Watch the workflow at:
`https://github.com/<org>/<repo>/actions`

When it finishes, verify on the VM:

```bash
sudo tail -20 /mnt/bot-data/state/logs/deploy.log
sudo docker ps
sudo docker inspect linkedin-bot --format='{{.Config.Image}}'
```

The image should now be `bot:<short-sha>` matching the commit you just pushed.

## Rollback

The deploy log records every action with a timestamp. To roll back to a
previous image, SSH to the VM and re-run the redeploy script with the older
tag:

```bash
gcloud compute ssh linkedin-bot --zone=asia-south1-a
sudo /opt/linkedin-bot/redeploy.sh \
  asia-south1-docker.pkg.dev/optimum-beach-489223-h7/linkedin-bot/bot:<previous-sha>
```

Old images stay in Artifact Registry forever unless you set a cleanup policy,
so any past commit is rollback-able by SHA.

## Files you should know about

| Path | Purpose |
|---|---|
| `state_paths.py` | Single source of truth for every persistent file path |
| `scripts/run_container.sh` | Single source of truth for `docker run` flags |
| `scripts/redeploy.sh` | Wrapper around `run_container.sh` with logging + health check |
| `.github/workflows/deploy.yml` | Auto-deploy on push to `main` |
| `terraform/main.tf` | VM, disk, IP, firewall, IAM (no day-to-day changes) |
| `Dockerfile` | Builds the container, declares `STATE_DIR=/app/state` |
| `backend/entrypoint.sh` | Container startup: ensures state dirs, exports STATE_DIR for cron |
| `backend/run_master.sh` | Hourly cron that launches the orchestrator per account |

## What is NOT persisted

Deliberately ephemeral, recreated on every container start:

- `/app/Linkedin_cloud_bot_attio/playwright_bots/user_data_*` — Chromium profile dirs (wiped on every login by `_wipe_profile()`)
- `/tmp/*` — anything Playwright/Chromium scratch space
- The container's writable layer outside `/app/state`
