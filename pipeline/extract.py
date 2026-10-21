"""Extract: pull daily weather from the Open-Meteo public API (free, no key)."""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
    "weather_code",
]
MAX_FORECAST_PAST_DAYS = 92  # API limit for past_days on the forecast endpoint
RATE_LIMIT_WAIT = 60         # free tier is limited per minute; on HTTP 429 wait for the window to reset

# Open-Meteo's free tier allows 600 weighted calls/minute. A 1-year archive request
# weighs ~16 calls, so 30+ cities fired back-to-back can exceed it. Space requests out.
_min_interval = 0.0
_last_request = 0.0


def set_request_delay(seconds):
    global _min_interval
    _min_interval = max(0.0, float(seconds))


def _throttle():
    global _last_request
    wait = _min_interval - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


class ExtractError(RuntimeError):
    pass


def _get_json(url, params, retries=4, backoff=2.0, timeout=30):
    """GET with throttling, plus retries on network errors, 429s and 5xx."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(1, retries + 1):
        _throttle()
        wait = backoff ** attempt
        try:
            with urllib.request.urlopen(full_url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            retryable = e.code == 429 or e.code >= 500
            if not retryable or attempt == retries:
                body = e.read().decode("utf-8", errors="replace")[:300]
                raise ExtractError(f"HTTP {e.code} from {url}: {body}") from e
            if e.code == 429:
                retry_after = e.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else RATE_LIMIT_WAIT
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                raise ExtractError(f"Network error calling {url}: {e}") from e
        log.warning("Attempt %d/%d failed for %s, retrying in %.0fs", attempt, retries, url, wait)
        time.sleep(wait)


def _base_params(city):
    return {
        "latitude": city["latitude"],
        "longitude": city["longitude"],
        "timezone": city.get("timezone", "Asia/Kolkata"),
        "daily": ",".join(DAILY_VARS),
    }


def fetch_archive(city, start: date, end: date):
    """Historical reanalysis data (lags real time by ~5 days)."""
    params = _base_params(city) | {"start_date": start.isoformat(), "end_date": end.isoformat()}
    log.info("archive  %-10s %s -> %s", city["name"], start, end)
    return _get_json(ARCHIVE_URL, params)


def fetch_recent_and_forecast(city, past_days: int, forecast_days: int):
    """Recent observed days plus the upcoming forecast in one call."""
    past_days = max(0, min(past_days, MAX_FORECAST_PAST_DAYS))
    params = _base_params(city) | {"past_days": past_days, "forecast_days": forecast_days}
    log.info("forecast %-10s past_days=%d forecast_days=%d", city["name"], past_days, forecast_days)
    return _get_json(FORECAST_URL, params)
