-- Data-quality checks: coverage, gaps, nulls, freshness.
DROP TABLE IF EXISTS report_data_quality;
CREATE TABLE report_data_quality AS
WITH stats AS (
    SELECT city_id,
           MIN(obs_date) AS first_date,
           MAX(obs_date) AS last_date,
           COUNT(*)      AS row_count,
           SUM(CASE WHEN temp_mean_c IS NULL OR precip_mm IS NULL THEN 1 ELSE 0 END) AS null_rows,
           SUM(CASE WHEN temp_min_c > temp_max_c THEN 1 ELSE 0 END) AS invalid_rows
    FROM fact_daily_weather
    WHERE is_forecast = 0
    GROUP BY city_id
)
SELECT c.name AS city, c.state_ut, c.region, s.first_date, s.last_date, s.row_count,
       CAST(julianday(s.last_date) - julianday(s.first_date) + 1 AS INTEGER) - s.row_count AS missing_days,
       s.null_rows, s.invalid_rows,
       CAST(julianday('now') - julianday(s.last_date) AS INTEGER) AS staleness_days,
       CASE
           WHEN s.invalid_rows > 0 THEN 'FAIL'
           WHEN CAST(julianday(s.last_date) - julianday(s.first_date) + 1 AS INTEGER) - s.row_count > 0
                OR s.null_rows > 0
                OR julianday('now') - julianday(s.last_date) > 3 THEN 'WARN'
           ELSE 'PASS'
       END AS status
FROM stats s
JOIN dim_city c ON c.city_id = s.city_id AND c.is_active = 1
ORDER BY CASE status WHEN 'FAIL' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, c.name;
