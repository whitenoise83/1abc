/***********************************************************************
* MacroPulse Scientific Paper
* Series Registry and Transformation Audit
*
* File:
*   stata/05_series_registry_audit.do
*
* Purpose:
*   Freeze the governed Model 1A, 1B and 1C information universes and
*   their transformations before constructing the real-time panels.
*
* Source architecture audited from MacroPulse:
*   config/series_registry.yml
*   config/inflation_series_registry.yml
*   config/labour_series_registry.yml
*   src/macropulse/processing/transforms.py
*
* IMPORTANT:
*   This script defines metadata only.
*   It does not estimate forecasting models and does not download data.
***********************************************************************/

version 19
clear all
set more off

capture mkdir "data"
capture mkdir "data/derived"
capture mkdir "outputs"
capture mkdir "outputs/tables"

display as text "============================================================"
display as text "05_series_registry_audit.do"
display as text "Governed series registry and transformation audit"
display as text "============================================================"

pwd


/***********************************************************************
* 1. MASTER GOVERNED SERIES REGISTRY
***********************************************************************/

clear

input ///
    str10 domain ///
    str18 series_id ///
    str8 role ///
    str1 frequency ///
    str12 aggregation ///
    str24 transform ///
    str8 source ///
    str10 start_date ///
    str80 series_name

"GDP"       "GDPC1"          "target"  "Q" ""     "annualised_qoq_log" "FRED" "1985-01-01" "Real Gross Domestic Product"
"GDP"       "INDPRO"         "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "Industrial Production Index"
"GDP"       "PAYEMS"         "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "All Employees, Total Nonfarm"
"GDP"       "RSAFS"          "feature" "M" ""     "mom_log_pct"        "FRED" "1992-01-01" "Advance Retail Sales"
"GDP"       "HOUST"          "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "Housing Starts"
"GDP"       "AWHMAN"         "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "Average Weekly Hours, Manufacturing"
"GDP"       "UNRATE"         "feature" "M" ""     "diff"               "FRED" "1985-01-01" "Unemployment Rate"
"GDP"       "CPIAUCSL"       "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "Consumer Price Index"
"GDP"       "FEDFUNDS"       "feature" "M" ""     "diff"               "FRED" "1985-01-01" "Effective Federal Funds Rate"

"Inflation" "CPIAUCSL"       "target"  "M" ""     "annualised_mom_log" "FRED" "1985-01-01" "Headline CPI"
"Inflation" "CPILFESL"       "target"  "M" ""     "annualised_mom_log" "FRED" "1985-01-01" "Core CPI"
"Inflation" "PCEPI"          "target"  "M" ""     "annualised_mom_log" "FRED" "1985-01-01" "Headline PCE Price Index"
"Inflation" "PCEPILFE"       "target"  "M" ""     "annualised_mom_log" "FRED" "1985-01-01" "Core PCE Price Index"

"Inflation" "PPIFIS"         "feature" "M" ""     "mom_log_pct"        "FRED" "2009-11-01" "Producer Price Index - Final Demand"
"Inflation" "CES0500000003"  "feature" "M" ""     "mom_log_pct"        "FRED" "2006-03-01" "Average Hourly Earnings - Total Private"
"Inflation" "CUSR0000SEHA"   "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "CPI Rent of Primary Residence"
"Inflation" "CUSR0000SEHC"   "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "CPI Owners Equivalent Rent"
"Inflation" "UNRATE"         "feature" "M" ""     "diff"               "FRED" "1985-01-01" "Unemployment Rate"
"Inflation" "FEDFUNDS"       "feature" "M" ""     "diff"               "FRED" "1985-01-01" "Effective Federal Funds Rate"
"Inflation" "T5YIE"          "feature" "D" "mean" "level"              "FRED" "2003-01-01" "Five-Year Breakeven Inflation Rate"
"Inflation" "MICH"           "feature" "M" ""     "level"              "FRED" "1985-01-01" "University of Michigan Inflation Expectations"
"Inflation" "DCOILWTICO"     "feature" "D" "mean" "mom_log_pct"        "FRED" "1986-01-01" "West Texas Intermediate Crude Oil Price"

"Labour"    "PAYEMS"         "target"  "M" ""     "diff"               "FRED" "1985-01-01" "Nonfarm Payroll Change"
"Labour"    "UNRATE"         "target"  "M" ""     "level"              "FRED" "1985-01-01" "Unemployment Rate"
"Labour"    "CES0500000003"  "target"  "M" ""     "annualised_mom_log" "FRED" "2006-03-01" "Average Hourly Earnings Growth"

"Labour"    "ICSA"           "feature" "W" "mean" "mom_log_pct"        "FRED" "1985-01-01" "Initial Unemployment Claims"
"Labour"    "CCSA"           "feature" "W" "mean" "mom_log_pct"        "FRED" "1985-01-01" "Continued Claims"
"Labour"    "JTSJOL"         "feature" "M" ""     "mom_log_pct"        "FRED" "2000-12-01" "Job Openings - Total Nonfarm"
"Labour"    "JTSQUR"         "feature" "M" ""     "mom_log_pct"        "FRED" "2000-12-01" "Quits - Total Nonfarm"
"Labour"    "CIVPART"        "feature" "M" ""     "level"              "FRED" "1985-01-01" "Labour Force Participation Rate"
"Labour"    "EMRATIO"        "feature" "M" ""     "level"              "FRED" "1985-01-01" "Employment-Population Ratio"
"Labour"    "TEMPHELPS"      "feature" "M" ""     "diff"               "FRED" "1990-01-01" "Temporary Help Services Employment"
"Labour"    "AWHI"           "feature" "M" ""     "level"              "FRED" "1985-01-01" "Aggregate Weekly Hours Index - Production and Nonsupervisory Employees"
"Labour"    "MANEMP"         "feature" "M" ""     "diff"               "FRED" "1985-01-01" "Manufacturing Employment"
"Labour"    "INDPRO"         "feature" "M" ""     "mom_log_pct"        "FRED" "1985-01-01" "Industrial Production Index"

end


/***********************************************************************
* 2. BASIC REGISTRY INTEGRITY
***********************************************************************/

display as text ""
display as text "=== BASIC REGISTRY INTEGRITY ==="

assert _N == 35

isid domain series_id

assert inlist(domain, "GDP", "Inflation", "Labour")
assert inlist(role, "target", "feature")
assert inlist(frequency, "Q", "M", "D", "W")
assert source == "FRED"

assert inlist( ///
    transform, ///
    "level", ///
    "diff", ///
    "mom_log_pct", ///
    "annualised_qoq_log", ///
    "annualised_mom_log" ///
)

gen double registry_start = daily(start_date, "YMD")
format registry_start %td
assert !missing(registry_start)

count if domain == "GDP"
assert r(N) == 9

count if domain == "Inflation"
assert r(N) == 13

count if domain == "Labour"
assert r(N) == 13

count if role == "target"
assert r(N) == 8

count if role == "feature"
assert r(N) == 27

display as result "Registry rows validated: " _N


/***********************************************************************
* 3. DOMAIN-SPECIFIC TARGET DEFINITIONS
***********************************************************************/

display as text ""
display as text "=== TARGET DEFINITIONS ==="

* GDP
assert role == "target" ///
    if domain == "GDP" & series_id == "GDPC1"

assert transform == "annualised_qoq_log" ///
    if domain == "GDP" & series_id == "GDPC1"

* Inflation
assert role == "target" ///
    if domain == "Inflation" & ///
    inlist(series_id, "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE")

assert transform == "annualised_mom_log" ///
    if domain == "Inflation" & role == "target"

* Labour
assert transform == "diff" ///
    if domain == "Labour" & series_id == "PAYEMS"

assert transform == "level" ///
    if domain == "Labour" & series_id == "UNRATE"

assert transform == "annualised_mom_log" ///
    if domain == "Labour" & series_id == "CES0500000003"

count if domain == "GDP" & role == "target"
assert r(N) == 1

count if domain == "Inflation" & role == "target"
assert r(N) == 4

count if domain == "Labour" & role == "target"
assert r(N) == 3


/***********************************************************************
* 4. GDP FEATURE TRANSFORMATIONS
***********************************************************************/

display as text ""
display as text "=== GDP FEATURE TRANSFORMATIONS ==="

assert transform == "mom_log_pct" ///
    if domain == "GDP" & ///
    inlist( ///
        series_id, ///
        "INDPRO", ///
        "PAYEMS", ///
        "RSAFS", ///
        "HOUST", ///
        "AWHMAN", ///
        "CPIAUCSL" ///
    )

assert transform == "diff" ///
    if domain == "GDP" & ///
    inlist(series_id, "UNRATE", "FEDFUNDS")

assert frequency == "Q" ///
    if domain == "GDP" & series_id == "GDPC1"

assert frequency == "M" ///
    if domain == "GDP" & role == "feature"


/***********************************************************************
* 5. INFLATION FEATURE TRANSFORMATIONS
***********************************************************************/

display as text ""
display as text "=== INFLATION FEATURE TRANSFORMATIONS ==="

assert transform == "mom_log_pct" ///
    if domain == "Inflation" & ///
    inlist( ///
        series_id, ///
        "PPIFIS", ///
        "CES0500000003", ///
        "CUSR0000SEHA", ///
        "CUSR0000SEHC", ///
        "DCOILWTICO" ///
    )

assert transform == "diff" ///
    if domain == "Inflation" & ///
    inlist(series_id, "UNRATE", "FEDFUNDS")

assert transform == "level" ///
    if domain == "Inflation" & ///
    inlist(series_id, "T5YIE", "MICH")

assert frequency == "D" ///
    if domain == "Inflation" & ///
    inlist(series_id, "T5YIE", "DCOILWTICO")

assert aggregation == "mean" ///
    if domain == "Inflation" & ///
    inlist(series_id, "T5YIE", "DCOILWTICO")


/***********************************************************************
* 6. LABOUR FEATURE TRANSFORMATIONS
***********************************************************************/

display as text ""
display as text "=== LABOUR FEATURE TRANSFORMATIONS ==="

assert transform == "mom_log_pct" ///
    if domain == "Labour" & ///
    inlist( ///
        series_id, ///
        "ICSA", ///
        "CCSA", ///
        "JTSJOL", ///
        "JTSQUR", ///
        "INDPRO" ///
    )

assert transform == "level" ///
    if domain == "Labour" & ///
    inlist(series_id, "CIVPART", "EMRATIO", "AWHI")

assert transform == "diff" ///
    if domain == "Labour" & ///
    inlist(series_id, "TEMPHELPS", "MANEMP")

assert frequency == "W" ///
    if domain == "Labour" & ///
    inlist(series_id, "ICSA", "CCSA")

assert aggregation == "mean" ///
    if domain == "Labour" & ///
    inlist(series_id, "ICSA", "CCSA")


/***********************************************************************
* 7. AGGREGATION POLICY
***********************************************************************/

display as text ""
display as text "=== HIGHER-FREQUENCY AGGREGATION POLICY ==="

gen byte should_mean = ///
    (domain == "Inflation" & ///
        inlist(series_id, "T5YIE", "DCOILWTICO")) | ///
    (domain == "Labour" & ///
        inlist(series_id, "ICSA", "CCSA"))

assert aggregation == "mean" if should_mean == 1
assert aggregation == ""     if should_mean == 0

count if aggregation == "mean"
assert r(N) == 4

list domain series_id frequency aggregation transform ///
    if aggregation != "", ///
    noobs abbreviate(24)


/***********************************************************************
* 8. TRANSFORMATION FORMULAS
*
* These reproduce src/macropulse/processing/transforms.py:
*
* level               = x_t
* diff                = x_t - x_(t-1)
* mom_log_pct         = 100 * [ln(x_t) - ln(x_(t-1))]
* annualised_qoq_log  = 400 * [ln(x_t) - ln(x_(t-1))]
* annualised_mom_log  = 1200 * [ln(x_t) - ln(x_(t-1))]
***********************************************************************/

display as text ""
display as text "=== TRANSFORMATION FORMULAS ==="

gen double transform_scale = .

replace transform_scale = 1 ///
    if inlist(transform, "level", "diff")

replace transform_scale = 100 ///
    if transform == "mom_log_pct"

replace transform_scale = 400 ///
    if transform == "annualised_qoq_log"

replace transform_scale = 1200 ///
    if transform == "annualised_mom_log"

assert !missing(transform_scale)

gen str60 transform_formula = ""

replace transform_formula = ///
    "x_t" ///
    if transform == "level"

replace transform_formula = ///
    "x_t - x_(t-1)" ///
    if transform == "diff"

replace transform_formula = ///
    "100*[ln(x_t)-ln(x_(t-1))]" ///
    if transform == "mom_log_pct"

replace transform_formula = ///
    "400*[ln(x_t)-ln(x_(t-1))]" ///
    if transform == "annualised_qoq_log"

replace transform_formula = ///
    "1200*[ln(x_t)-ln(x_(t-1))]" ///
    if transform == "annualised_mom_log"

assert transform_formula != ""

tab transform
tab domain role


/***********************************************************************
* 9. START-DATE AUDIT
***********************************************************************/

display as text ""
display as text "=== REGISTRY START DATES ==="

summarize registry_start, detail

list ///
    domain ///
    series_id ///
    role ///
    start_date ///
    if registry_start > daily("1985-01-01", "YMD"), ///
    noobs sepby(domain)


/***********************************************************************
* 10. SAVE MACHINE-READABLE PAPER REGISTRY
***********************************************************************/

sort domain role series_id

order ///
    domain ///
    series_id ///
    series_name ///
    role ///
    frequency ///
    aggregation ///
    transform ///
    transform_scale ///
    transform_formula ///
    source ///
    start_date ///
    registry_start

compress

save ///
    "data/derived/series_registry_audit.dta", ///
    replace

export delimited using ///
    "outputs/tables/series_registry_audit.csv", ///
    replace


/***********************************************************************
* 11. MODEL INPUT-LAG POLICY
*
* Inflation and labour lag policies are explicitly declared in their
* governed registries.
*
* Model 1A does not declare an analogous generic lag vector in
* config/series_registry.yml; its Bridge and DFM input construction will
* therefore be audited from their dataset builders in the model section
* rather than inferred here.
***********************************************************************/

clear

input ///
    str10 domain ///
    str20 target_lags ///
    str20 cross_target_lags ///
    str20 feature_lags ///
    int minimum_training ///
    byte max_feature_carry_months ///
    str10 backtest_start

"Inflation" "1 2 3 6 12" ""    "1 2"   120 2 "2015-01-01"
"Labour"    "1 2 3 6 12" "1 2" "0 1 2" 120 4 "2016-01"

end

isid domain

assert target_lags == "1 2 3 6 12"

assert feature_lags == "1 2" ///
    if domain == "Inflation"

assert cross_target_lags == "" ///
    if domain == "Inflation"

assert feature_lags == "0 1 2" ///
    if domain == "Labour"

assert cross_target_lags == "1 2" ///
    if domain == "Labour"

assert minimum_training == 120

assert max_feature_carry_months == 2 ///
    if domain == "Inflation"

assert max_feature_carry_months == 4 ///
    if domain == "Labour"

list, noobs abbreviate(24)

save ///
    "data/derived/model_input_lag_policy.dta", ///
    replace

export delimited using ///
    "outputs/tables/model_input_lag_policy.csv", ///
    replace


/***********************************************************************
* 12. FINAL AUDIT MESSAGE
***********************************************************************/

display as text ""
display as text "============================================================"
display as result "SERIES-REGISTRY AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "Frozen governed universes:"
display as text "  GDP:        1 target + 8 features = 9 series"
display as text "  Inflation:  4 targets + 9 features = 13 series"
display as text "  Labour:     3 targets + 10 features = 13 series"
display as text ""
display as text "Total domain-series definitions: 35"
display as text ""
display as text "Transformations:"
display as text "  annualised_qoq_log = 400 * Delta log"
display as text "  annualised_mom_log = 1200 * Delta log"
display as text "  mom_log_pct        = 100 * Delta log"
display as text "  diff               = first difference"
display as text "  level              = untransformed level"
display as text ""
display as text "Higher-frequency monthly aggregation:"
display as text "  T5YIE      -> monthly mean"
display as text "  DCOILWTICO -> monthly mean"
display as text "  ICSA       -> monthly mean"
display as text "  CCSA       -> monthly mean"
display as text ""
display as text "GDP model-specific lag/input construction remains"
display as text "reserved for the Bridge/DFM model audit."
display as text "============================================================"