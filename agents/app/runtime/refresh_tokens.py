"""OAuth refresh-token poller.

Runs on the same APScheduler instance as the agents. Every
REFRESH_INTERVAL seconds it POSTs to the web service's
`/api/cron/refresh-broker-tokens` endpoint (which does the actual work
in the only place that holds TREZO_TOKENS_KEY).

Why this lives in the agents service: APScheduler already owns the
recurring cadence layer. We don't need Vercel Cron or a separate
Windows task — the same process that ticks Pattern Detection ticks
this. The web route is the single chokepoint that knows how to talk
to each broker.

Failure handling: every call has a short timeout. The poller logs
structured outcomes (`refresh.poll`) so Mike can grep the logs. It
never raises - the agents scheduler keeps ticking.
"""

from __future__ import annotations

import asyncio
import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.refresh_tokens")

# How often the agents service kicks the web cron route. 15 minutes is
# the sweet spot - tokens expire on hour boundaries at most brokers and
# our HORIZON_MS is 1h, so 15m catches them comfortably before bedtime.
REFRESH_INTERVAL_SECONDS = 15 * 60

# How long we'll wait for the web route to respond. Refreshes are
# light - a few dozen rows, one HTTPS call each. Anything longer than
# 30s usually means the web tier is wedged.
HTTP_TIMEOUT_SECONDS = 30.0


async def poll_refresh_endpoint() -> dict:
    """POST to the web cron route once. Returns the parsed JSON
    response or an error dict. Never raises.

    Skips silently when web URL or secret aren't configured - the
    bootstrap path will have already logged the "not configured"
    warning, no need to spam.
    """
    settings = get_settings()
    base = (settings.trezo_web_base_url or "").rstrip("/")
    secret = settings.cron_secret
    if not base or not secret:
        return {"ok": False, "skipped": True, "reason": "not_configured"}

    url = f"{base}/api/cron/refresh-broker-tokens"
    headers = {"Authorization": f"Bearer {secret}"}

    try:
        import httpx
    except ImportError:  # pragma: no cover
        log.warning("refresh.poll.no_httpx",
                    note="httpx not installed; cannot poll refresh route")
        return {"ok": False, "error": "httpx not installed"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            res = await client.post(url, headers=headers)
            if res.status_code != 200:
                log.warning(
                    "refresh.poll.bad_status",
                    status=res.status_code,
                    body=res.text[:200],
                )
                return {"ok": False, "status": res.status_code,
                        "body": res.text[:200]}
            data = res.json()
            log.info(
                "refresh.poll.ok",
                candidates=data.get("candidates", 0),
                results_count=len(data.get("results", [])),
            )
            return data
    except Exception as e:  # noqa: BLE001
        log.warning("refresh.poll.exception", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}


def schedule_refresh_token_job(scheduler) -> None:
    """Hook into the APScheduler instance owned by `start_scheduler()`.

    Idempotent - safe to call once on boot. If the web URL / cron
    secret aren't set, we still register the job (it'll noop) so
    that adding the env vars later doesn't require a restart loop.
    """
    if scheduler is None:
        return

    async def _tick():
        try:
            await poll_refresh_endpoint()
        except Exception as e:  # noqa: BLE001
            log.warning("refresh.poll.unhandled", error=str(e)[:200])

    scheduler.add_job(
        _tick,
        "interval",
        seconds=REFRESH_INTERVAL_SECONDS,
        id="refresh_broker_tokens",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log.info(
        "refresh.poll.scheduled",
        interval_seconds=REFRESH_INTERVAL_SECONDS,
    )


# Convenience for manual ticking from FastAPI route or REPL.
async def run_once_for_testing() -> dict:
    return await poll_refresh_endpoint()


if __name__ == "__main__":
    print(asyncio.run(run_once_for_testing()))
