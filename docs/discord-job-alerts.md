# Discord failed-job alerts

Set `DISCORD_ALERT_WEBHOOK_URL` as an Azure Container App secret and reference it with `secretref:` in the environment of the backend and every Celery worker app (general, clustering, and generation). Configure each dev/prod app separately; do not put the URL in source control or logs. No deployment configuration is changed by this feature.

Alerts require both a nonempty URL and backend `ENVIRONMENT=dev` or `prod`. `ENVIRONMENT=local` disables them even when a URL is present. The cloud-native and cloud-docker launchers load `.env.cloud`; `scripts/setup-cloud-env.sh` generates that file with `ENVIRONMENT=dev`, but both launchers explicitly clear the webhook URL for their local backend and workers. Standard local Docker Compose also clears it. These launchers leave `ENVIRONMENT` unchanged for other behavior.

Alerts are best effort after commit, without retries. Error details are reduced to a small set of generic categories to avoid sending user content or secrets.

The webhook uses HTTPX transport directly, bypassing HTTPX client logging and the HTTPX client integrations used by OpenTelemetry and Sentry. Other HTTP traffic keeps its normal observability.
