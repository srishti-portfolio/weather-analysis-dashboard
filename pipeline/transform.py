"""Transform: reshape the column-oriented API payload into validated rows."""
from datetime import date

FIELD_MAP = {
    "temperature_2m_max": "temp_max_c",
    "temperature_2m_min": "temp_min_c",
    "temperature_2m_mean": "temp_mean_c",
    "precipitation_sum": "precip_mm",
    "wind_speed_10m_max": "wind_max_kmh",
    "weather_code": "weather_code",
}


def to_rows(payload, source: str, today: date):
    """Return (valid_rows, rejected_rows). Each row is a dict keyed by fact columns."""
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    valid, rejected = [], []

    for i, d in enumerate(dates):
        row = {"obs_date": d, "source": source}
        for api_field, col in FIELD_MAP.items():
            values = daily.get(api_field) or []
            row[col] = values[i] if i < len(values) else None

        # Derive mean if the API omitted it but max/min exist.
        if row["temp_mean_c"] is None and None not in (row["temp_max_c"], row["temp_min_c"]):
            row["temp_mean_c"] = round((row["temp_max_c"] + row["temp_min_c"]) / 2, 2)

        # Today is still in progress, so it counts as forecast until tomorrow.
        row["is_forecast"] = 1 if date.fromisoformat(d) >= today else 0

        reason = validate(row)
        if reason:
            row["reject_reason"] = reason
            rejected.append(row)
        else:
            valid.append(row)
    return valid, rejected


def validate(row):
    """Return a rejection reason, or None if the row is OK."""
    if row["temp_max_c"] is None and row["temp_min_c"] is None:
        return "all temperatures null"
    if None not in (row["temp_max_c"], row["temp_min_c"]) and row["temp_min_c"] > row["temp_max_c"] + 0.05:
        return "temp_min > temp_max"
    if row["temp_max_c"] is not None and not -90 <= row["temp_max_c"] <= 60:
        return "temperature out of physical range"
    if row["precip_mm"] is not None and row["precip_mm"] < 0:
        return "negative precipitation"
    return None
