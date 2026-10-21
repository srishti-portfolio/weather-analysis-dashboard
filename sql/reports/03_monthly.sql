-- Monthly roll-up per city with month-over-month temperature change (LAG).
DROP TABLE IF EXISTS report_monthly;
CREATE TABLE report_monthly AS
WITH monthly AS (
    SELECT city_id,
           strftime('%Y-%m', obs_date)  AS month,
           COUNT(*)                     AS days,
           AVG(temp_mean_c)             AS avg_temp_c,
           SUM(precip_mm)               AS total_rain_mm,
           SUM(CASE WHEN precip_mm >= 1 THEN 1 ELSE 0 END) AS rainy_days
    FROM fact_daily_weather
    WHERE is_forecast = 0
    GROUP BY city_id, month
)
SELECT c.name AS city, c.state_ut, c.region, m.month, m.days,
       ROUND(m.avg_temp_c, 1)    AS avg_temp_c,
       ROUND(m.total_rain_mm, 1) AS total_rain_mm,
       m.rainy_days,
       ROUND(m.avg_temp_c - LAG(m.avg_temp_c) OVER (PARTITION BY m.city_id ORDER BY m.month), 1)
                                 AS temp_change_mom_c
FROM monthly m
JOIN dim_city c ON c.city_id = m.city_id AND c.is_active = 1
ORDER BY c.name, m.month;
