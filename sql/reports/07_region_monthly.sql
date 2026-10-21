-- Regional roll-up: per region and month, the average city's temperature and rainfall.
-- Averaging per city first (not per row) stops regions with more cities from dominating.
DROP TABLE IF EXISTS report_region_monthly;
CREATE TABLE report_region_monthly AS
WITH city_month AS (
    SELECT c.region, f.city_id,
           strftime('%Y-%m', f.obs_date) AS month,
           AVG(f.temp_mean_c)            AS avg_temp_c,
           SUM(f.precip_mm)              AS rain_mm
    FROM fact_daily_weather f
    JOIN dim_city c ON c.city_id = f.city_id AND c.is_active = 1
    WHERE f.is_forecast = 0
    GROUP BY c.region, f.city_id, month
)
SELECT region, month,
       COUNT(*)                    AS cities,
       ROUND(AVG(avg_temp_c), 1)   AS avg_temp_c,
       ROUND(AVG(rain_mm), 1)      AS avg_rain_per_city_mm,
       ROUND(MAX(rain_mm), 1)      AS max_city_rain_mm
FROM city_month
GROUP BY region, month
ORDER BY region, month;
