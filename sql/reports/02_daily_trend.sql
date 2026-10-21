-- Daily mean temperature with a 7-day rolling average (window function), last 120 days.
DROP TABLE IF EXISTS report_daily_trend;
CREATE TABLE report_daily_trend AS
WITH anchor AS (
    SELECT MAX(obs_date) AS max_date FROM fact_daily_weather WHERE is_forecast = 0
),
base AS (
    SELECT f.city_id, f.obs_date, f.temp_mean_c, f.precip_mm,
           AVG(f.temp_mean_c) OVER (
               PARTITION BY f.city_id ORDER BY f.obs_date
               ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
           ) AS temp_7d_avg
    FROM fact_daily_weather f
    WHERE f.is_forecast = 0
)
SELECT c.name AS city, c.state_ut, c.region, b.obs_date,
       ROUND(b.temp_mean_c, 1) AS temp_mean_c,
       ROUND(b.temp_7d_avg, 1) AS temp_7d_avg_c,
       ROUND(b.precip_mm, 1)   AS precip_mm
FROM base b
JOIN dim_city c ON c.city_id = b.city_id AND c.is_active = 1, anchor a
WHERE b.obs_date > date(a.max_date, '-120 day')
ORDER BY c.name, b.obs_date;
