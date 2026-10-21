-- KPI table: last 30 observed days per city, with national rankings and map coordinates.
DROP TABLE IF EXISTS report_city_summary_30d;
CREATE TABLE report_city_summary_30d AS
WITH anchor AS (
    SELECT MAX(obs_date) AS max_date FROM fact_daily_weather WHERE is_forecast = 0
),
recent AS (
    SELECT f.*
    FROM fact_daily_weather f
    JOIN dim_city c ON c.city_id = f.city_id AND c.is_active = 1, anchor a
    WHERE f.is_forecast = 0
      AND f.obs_date > date(a.max_date, '-30 day')
),
hottest AS (
    SELECT city_id, obs_date,
           ROW_NUMBER() OVER (PARTITION BY city_id ORDER BY temp_max_c DESC, obs_date DESC) AS rn
    FROM recent
),
agg AS (
    SELECT r.city_id,
           COUNT(*)                                          AS days,
           AVG(r.temp_max_c)                                 AS avg_high_c,
           AVG(r.temp_min_c)                                 AS avg_low_c,
           MAX(r.temp_max_c)                                 AS peak_high_c,
           SUM(r.precip_mm)                                  AS total_rain_mm,
           SUM(CASE WHEN r.precip_mm >= 1 THEN 1 ELSE 0 END) AS rainy_days,
           MAX(r.wind_max_kmh)                               AS max_wind_kmh
    FROM recent r
    GROUP BY r.city_id
)
SELECT
    c.name                          AS city,
    c.state_ut,
    c.state_type,
    c.region,
    c.latitude,
    c.longitude,
    a.days,
    ROUND(a.avg_high_c, 1)          AS avg_high_c,
    ROUND(a.avg_low_c, 1)           AS avg_low_c,
    ROUND(a.peak_high_c, 1)         AS peak_high_c,
    h.obs_date                      AS peak_date,
    ROUND(a.total_rain_mm, 1)       AS total_rain_mm,
    a.rainy_days,
    ROUND(a.max_wind_kmh, 1)        AS max_wind_kmh,
    RANK() OVER (ORDER BY a.avg_high_c DESC)    AS hot_rank,
    RANK() OVER (ORDER BY a.total_rain_mm DESC) AS wet_rank
FROM agg a
JOIN dim_city c ON c.city_id = a.city_id
JOIN hottest h  ON h.city_id = a.city_id AND h.rn = 1
ORDER BY hot_rank, c.name;
