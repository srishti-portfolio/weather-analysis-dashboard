-- Upcoming days (forecast rows only).
DROP TABLE IF EXISTS report_forecast;
CREATE TABLE report_forecast AS
SELECT c.name AS city, c.state_ut, c.region, f.obs_date,
       ROUND(f.temp_max_c, 1) AS temp_max_c,
       ROUND(f.temp_min_c, 1) AS temp_min_c,
       ROUND(f.precip_mm, 1)  AS precip_mm,
       f.weather_code
FROM fact_daily_weather f
JOIN dim_city c ON c.city_id = f.city_id AND c.is_active = 1
WHERE f.is_forecast = 1
ORDER BY c.name, f.obs_date;
