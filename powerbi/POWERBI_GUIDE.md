# Building the dashboard in Power BI

Every pipeline run writes fresh CSV files to `powerbi/data/`. Power BI reads
them, and clicking **Refresh** picks up the latest data.

The data covers **34 capital cities**, which between them are the capitals of
all 28 states and 8 union territories. Chandigarh is the capital of Punjab,
Haryana and the Chandigarh UT, which is why there are 34 cities for 36 states
and UTs. Every city-level CSV has `city`, `state_ut` and `region` columns.

## The CSV files

| File | Rows | Use it for |
|---|---|---|
| `dim_city.csv` | 1 per city | City list: `city`, `state_ut`, `state_type`, `region`, `capital_of`, `latitude`, `longitude` |
| `fact_daily_weather.csv` | 1 per city per day | Raw daily facts, plus `city`, `state_ut` and `region`. Build your own DAX on this. |
| `pipeline_runs.csv` | 1 per run | Run history (`success` / `partial` / `failed`, rows, API calls) |
| `report_city_summary_30d.csv` | 1 per city | Last-30-day KPIs, `hot_rank`, `wet_rank`, plus `latitude` and `longitude` for the map |
| `report_daily_trend.csv` | 1 per city per day | Daily temperature + 7-day rolling average (last 120 days) |
| `report_monthly.csv` | 1 per city per month | Monthly rain, rainy days, temperature, month-over-month change |
| `report_region_monthly.csv` | 1 per region per month | Regional averages (per city), used for the heatmap |
| `report_dry_streaks.csv` | 1 per city | Longest dry spell |
| `report_forecast.csv` | 1 per city per day | Next 7 days |
| `report_data_quality.csv` | 1 per city | PASS / WARN / FAIL quality checks |

**Regions:** North (8 cities), Central (2), East (5), Northeast (8), West (4), South (7).

---

## Step 1: Create a folder parameter

1. Open Power BI Desktop, then go to **Home > Transform data**.
2. Go to **Home > Manage Parameters > New Parameter**.
   - Name: `DataFolder`
   - Type: **Text**
   - Current value: the full path to `powerbi\data`, for example
     `C:\Projects\weather-pipeline\powerbi\data\`. Keep the trailing backslash.

## Step 2: Load each CSV

For each of the 10 files, go to **Home > New Source > Blank Query** and open
**Advanced Editor**. Paste the code below, change the file name, and rename the
query to match the file name.

```powerquery
let
    Source   = Csv.Document(
                   File.Contents(DataFolder & "fact_daily_weather.csv"),
                   [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                   {"obs_date", type date},
                   {"city_id", Int64.Type},
                   {"temp_max_c", type number}, {"temp_min_c", type number},
                   {"temp_mean_c", type number}, {"precip_mm", type number},
                   {"wind_max_kmh", type number}, {"weather_code", Int64.Type},
                   {"is_forecast", Int64.Type}},
                   "en-US")
in
    Typed
```

For the other files, Power BI's automatic type detection usually works. Check that:
- date columns (`obs_date`, `peak_date`, `start_date`, `end_date`, `first_date`, `last_date`) are **Date**
- `latitude` and `longitude` are **Decimal number**
- `month` (in `report_monthly` and `report_region_monthly`) is **Text**. For a real date, add a column with `Date.FromText([month] & "-01")`.
- the `"en-US"` locale argument is kept, so decimals parse correctly on any PC

Finish with **Close & Apply**.

## Step 3: Data model

**3.1 Add a Region table.** Go to **Modeling > New table**:

```dax
Regions =
DATATABLE (
    "region", STRING, "region_order", INTEGER,
    { { "North", 1 }, { "Central", 2 }, { "East", 3 }, { "Northeast", 4 }, { "West", 5 }, { "South", 6 } }
)
```

Sort `Regions[region]` by `region_order` (**Column tools > Sort by column**).

**3.2 Add a Calendar table:**

```dax
Calendar =
ADDCOLUMNS (
    CALENDAR ( MIN ( fact_daily_weather[obs_date] ), MAX ( fact_daily_weather[obs_date] ) ),
    "Year", YEAR ( [Date] ),
    "Month", FORMAT ( [Date], "MMM yyyy" ),
    "MonthSort", YEAR ( [Date] ) * 100 + MONTH ( [Date] )
)
```

Mark it as a date table (**Table tools > Mark as date table**). Sort `Month` by `MonthSort`.

**3.3 Relationships.** Create these in **Model view**. All are many-to-one with single-direction filtering.

| From (many) | To (one) | Column |
|---|---|---|
| `dim_city` | `Regions` | `region` |
| `report_region_monthly` | `Regions` | `region` |
| `fact_daily_weather` | `dim_city` | `city_id` |
| `fact_daily_weather` | `Calendar` | `obs_date` to `Date` |
| `report_city_summary_30d` | `dim_city` | `city` |
| `report_daily_trend` | `dim_city` | `city` |
| `report_monthly` | `dim_city` | `city` |
| `report_dry_streaks` | `dim_city` | `city` |
| `report_forecast` | `dim_city` | `city` |
| `report_data_quality` | `dim_city` | `city` |

The filters flow **Regions → dim_city → every city table**. So:
- a **Region slicer** must use `Regions[region]`
- a **State/UT slicer** must use `dim_city[state_ut]`
- a **City slicer** must use `dim_city[city]`

**Hide** the `city`, `state_ut` and `region` columns on the fact and report
tables (right-click > Hide in report view), so you always slice through the
dimension tables. Otherwise a slicer built on a report table's own `region` column
would filter only that one table.

## Step 4: DAX measures

Create a blank table called `_Measures` to hold these. Most of them exclude forecast rows.

```dax
Capitals Tracked = DISTINCTCOUNT ( dim_city[city] )

States & UTs Covered =
SUMX ( dim_city, 1 + LEN ( dim_city[capital_of] ) - LEN ( SUBSTITUTE ( dim_city[capital_of], ";", "" ) ) )

Observed Days = CALCULATE ( COUNTROWS ( fact_daily_weather ), fact_daily_weather[is_forecast] = 0 )

Avg High °C = CALCULATE ( AVERAGE ( fact_daily_weather[temp_max_c] ), fact_daily_weather[is_forecast] = 0 )

Avg Low °C = CALCULATE ( AVERAGE ( fact_daily_weather[temp_min_c] ), fact_daily_weather[is_forecast] = 0 )

Temp Range °C = [Avg High °C] - [Avg Low °C]

Total Rain mm = CALCULATE ( SUM ( fact_daily_weather[precip_mm] ), fact_daily_weather[is_forecast] = 0 )

Avg Rain per City mm = DIVIDE ( [Total Rain mm], [Capitals Tracked] )

Rainy Days =
CALCULATE ( COUNTROWS ( fact_daily_weather ),
    fact_daily_weather[is_forecast] = 0, fact_daily_weather[precip_mm] >= 1 )

Temp 7d Rolling =
CALCULATE ( AVERAGE ( fact_daily_weather[temp_mean_c] ), fact_daily_weather[is_forecast] = 0,
    DATESINPERIOD ( Calendar[Date], MAX ( Calendar[Date] ), -7, DAY ) )

Avg Temp MoM Δ =
VAR cur  = CALCULATE ( AVERAGE ( fact_daily_weather[temp_mean_c] ), fact_daily_weather[is_forecast] = 0 )
VAR prev = CALCULATE ( AVERAGE ( fact_daily_weather[temp_mean_c] ), fact_daily_weather[is_forecast] = 0,
               DATEADD ( Calendar[Date], -1, MONTH ) )
RETURN IF ( NOT ISBLANK ( prev ), cur - prev )

Hottest Capital =
MAXX ( TOPN ( 1, report_city_summary_30d, report_city_summary_30d[avg_high_c], DESC ),
       report_city_summary_30d[city] )

Wettest Capital =
MAXX ( TOPN ( 1, report_city_summary_30d, report_city_summary_30d[total_rain_mm], DESC ),
       report_city_summary_30d[city] )

Heavy Rain Days (Forecast) = CALCULATE ( COUNTROWS ( report_forecast ), report_forecast[precip_mm] >= 10 )

Quality Pass Rate =
DIVIDE ( COUNTROWS ( FILTER ( report_data_quality, report_data_quality[status] = "PASS" ) ),
         COUNTROWS ( report_data_quality ) )

Last Refresh =
"Last run: " & FORMAT ( MAX ( pipeline_runs[started_at] ), "dd mmm yyyy hh:mm" ) & " UTC"
```

## Step 5: The map visual

1. Enable map visuals: **File > Options and settings > Options > Security** and tick
   **Use Map and Filled Map visuals**. Restart Power BI if asked.
2. In `report_city_summary_30d`, select the `latitude` column and set
   **Column tools > Data category > Latitude**. Do the same for `longitude` (**Longitude**).
3. Insert a **Map** visual (or **Azure Maps** if Map isn't available):
   - Latitude: `report_city_summary_30d[latitude]`
   - Longitude: `report_city_summary_30d[longitude]`
   - Bubble size: `total_rain_mm`, or `avg_high_c`
   - Legend: `Regions[region]`
   - Tooltips: `city`, `state_ut`, `avg_high_c`, `total_rain_mm`
4. If the Map visual is blocked on your PC, use a **Filled map** with
   `dim_city[state_ut]` as the Location (set its Data category to
   **State or Province**). Or use a bar chart of the top 10 capitals instead.

## Step 6: Report pages and design

The report is branded **The Weather Report**. Folder Containing The templates is present in this folder.

| Page | Main visuals |
|---|---|
| 1. National Overview | KPI cards, map of India, Top 10 hottest, Top 10 wettest |
| 2. Regional Overview | Region slicer, region × month rainfall heatmap (matrix), regional temperature line |
| 3. City Temperature | City slicer (up to 4), rolling temperature line, day/night range bars, month-over-month matrix |
| 4. Rainfall & Dry Spells | Monthly rainfall by city, rainy-days heatmap, longest dry spell |
| 5. 7 Day Forecast | Heavy-rain matrix, forecast highs, forecast table with condition icons, heavy-rain card |
| 6. Pipeline Health and Data Quality | Run status cards, rows per run, data quality by city, run history |

**Design system**

| Element | Setting |
|---|---|
| Page size | **1920 × 1080**, display **Fit to page** (Format pane > Canvas settings) |
| Page background | An SVG from `powerbi/backgrounds/` showing translucent blue panels (`#215F9A`): **Format pane > Canvas background > Image**, Image fit **Fill**, Transparency **0%** |
| Layout | A left sidebar holding the **The Weather Report** logo; the page title and a page navigator across the top; visuals sit on the blue panels |
| Visual backgrounds and borders | **Off**, so every visual sits directly on its panel |
| Titles | Navy `#081E37`, 20 pt, centred. Page titles: bold 40 pt, `#153C6B`, centred |
| Single-colour bars, card accent bars, selected page tab | Dark blue `#153C6B` |
| Data labels | Dark green `#0B4811`, 11 pt |
| Table and matrix headers | Indigo `#211B44`, 14 pt; values navy `#081E37`, 16 pt |
| Region colours (map legend, region lines) | North `#2A78D6` · Central `#EB6834` · East `#1BAF7A` · Northeast `#EDA100` · West `#E87BA4` · South `#008300` |
| Status colours | Success / PASS `#0CA30C` · partial / WARN `#FAB219` · failed / FAIL `#D03B3B`, always with an icon |

Tips:
- **Too many lines:** with 34 cities, never put all of them on one line chart.
  Use a City slicer limited to 4 selections, or a Top N filter (Filters pane >
  Filter type: Top N).
- **Sync slicers:** go to **View > Sync slicers** so Region and State slicers
  apply to every page.
- **Status icons:** in the data-quality table, use **Conditional formatting > Icons**
  on `status`.

## Step 7: Refreshing

1. Run the pipeline (on its daily schedule, or with `python run_pipeline.py`).
2. In Power BI Desktop, click **Home > Refresh**.

Save the report as `powerbi/WeatherDashboard.pbix`.

> **Publishing online:** scheduled refresh in the Power BI Service needs the
> on-premises data gateway (personal mode), because the CSVs are local files. It
> also needs a work or school account.
