"""Privacy-preserving, best-effort Discord job failure alerts."""
import httpx


def _error_summary(error):
    # Error strings can contain prompts, paths, credentials, or arbitrary user data.
    # Classify locally instead of sending any part of the original text.
    text = (error or "").lower()
    for words, summary in (
        (("timeout", "timed out"), "Operation timed out"),
        (("connection", "network"), "Connection error"),
        (("rate limit",), "Rate limit exceeded"),
    ):
        if any(word in text for word in words):
            return summary
    return "Job failed; details withheld"


def send_failure_alert(job_id, job_type, error, settings):
    if settings.environment not in ("dev", "prod") or not settings.discord_alert_webhook_url:
        return
    try:
        payload = {
            "content": (
                f"Job {int(job_id)} failed\nType: {job_type.value}\n"
                f"Environment: {settings.environment}\nError: {_error_summary(error)}"
            ),
            "allowed_mentions": {"parse": []},
        }
        # Client.send is instrumented by Sentry and OTel and emits the full URL
        # through HTTPX INFO logging. Use the transport directly for this one
        # request so the secret path never enters those observability hooks.
        request = httpx.Request(
            "POST", settings.discord_alert_webhook_url.get_secret_value(), json=payload,
            extensions={"timeout": httpx.Timeout(2.0).as_dict()},
        )
        with httpx.HTTPTransport(retries=0) as transport:
            response = transport.handle_request(request)
            try:
                response.request = request
                response.raise_for_status()
            finally:
                response.close()
    except Exception:
        # HTTP exception text can contain the secret webhook URL; never log it.
        pass
