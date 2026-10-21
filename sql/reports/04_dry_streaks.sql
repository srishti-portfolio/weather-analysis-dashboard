-- Longest dry spell (precip < 1mm) per city: classic gaps-and-islands.
DROP TABLE IF EXISTS report_dry_streaks;
CREATE TABLE report_dry_streaks AS
WITH flagged AS (
    SELECT city_id, obs_date,
           CASE WHEN precip_mm < 1 THEN 1 ELSE 0 END AS is_dry,
           ROW_NUMBER() OVER (PARTITION BY city_id ORDER BY obs_date) AS rn_all,
           ROW_NUMBER() OVER (PARTITION BY city_id, CASE WHEN precip_mm < 1 THEN 1 ELSE 0 END
                              ORDER BY obs_date) AS rn_grp
    FROM fact_daily_weather
    WHERE is_forecast = 0 AND precip_mm IS NOT NULL
),
islands AS (
    SELECT city_id, MIN(obs_date) AS start_date, MAX(obs_date) AS end_date, COUNT(*) AS length_days
    FROM flagged
    WHERE is_dry = 1
    GROUP BY city_id, rn_all - rn_grp
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY city_id ORDER BY length_days DESC, end_date DESC) AS rn
    FROM islands
)
SELECT c.name AS city, c.state_ut, c.region, r.start_date, r.end_date, r.length_days
FROM ranked r
JOIN dim_city c ON c.city_id = r.city_id AND c.is_active = 1
WHERE r.rn = 1
ORDER BY r.length_days DESC, c.name;
