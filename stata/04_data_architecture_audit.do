version 19
clear all
set more off


display as text "============================================================"
display as text "04_data_architecture_audit.do"
display as text "Audit of frozen real-time forecast-stage calendars"
display as text "============================================================"

pwd


/**********************************************************************
* 1. GDP STAGE CALENDAR
**********************************************************************/

display as text ""
display as text "=== GDP STAGE CALENDAR ==="

import delimited ///
    "data/raw/forecast_calendars/gdp_stage_calendar.csv", ///
    clear varnames(1) stringcols(_all)

gen double fdate = daily(forecast_date, "YMD")
gen double rdate = daily(actual_release_date, "YMD")
format fdate rdate %td

destring days_to_release, replace

gen qdate = quarterly(target_period, "YQ")
format qdate %tq

assert !missing(fdate)
assert !missing(qdate)

* There should be one calendar observation per target-period/stage.
isid target_period forecast_stage

* Five governed GDP stages.
gen byte stage_order = .
replace stage_order = 1 if forecast_stage == "early_quarter"
replace stage_order = 2 if forecast_stage == "after_month_1"
replace stage_order = 3 if forecast_stage == "after_month_2"
replace stage_order = 4 if forecast_stage == "quarter_end"
replace stage_order = 5 if forecast_stage == "pre_advance_release"

assert !missing(stage_order)

bysort target_period: assert _N == 5

* Build the calendar dates implied by the governed rules.
gen double qstart = dofq(qdate)
format qstart %td

gen double m1 = dofm(mofd(qstart))
gen double m2 = dofm(mofd(qstart) + 1)
gen double m3 = dofm(mofd(qstart) + 2)
format m1 m2 m3 %td

gen double expected_date = .

replace expected_date = ///
    mdy(month(m1), 15, year(m1)) ///
    if forecast_stage == "early_quarter"

replace expected_date = ///
    mdy(month(m2), 15, year(m2)) ///
    if forecast_stage == "after_month_1"

replace expected_date = ///
    mdy(month(m3), 15, year(m3)) ///
    if forecast_stage == "after_month_2"

replace expected_date = ///
    dofq(qdate + 1) - 1 ///
    if forecast_stage == "quarter_end"

replace expected_date = ///
    rdate - 1 ///
    if forecast_stage == "pre_advance_release"

format expected_date %td

gen byte date_rule_ok = (fdate == expected_date)

assert date_rule_ok == 1

* Validate stored days-to-release.
gen calculated_days_to_release = rdate - fdate ///
    if !missing(rdate)

assert calculated_days_to_release == days_to_release ///
    if !missing(rdate)

* Stage dates must be strictly increasing within a target quarter.
sort target_period stage_order
by target_period: assert fdate > fdate[_n-1] if _n > 1

tab forecast_stage
summarize days_to_release, detail

preserve
collapse ///
    (count) n_origins=fdate ///
    (min) min_days=days_to_release ///
    (median) median_days=days_to_release ///
    (max) max_days=days_to_release, ///
    by(forecast_stage stage_order)

sort stage_order
list, noobs abbreviate(24)
format n_origins %9.0g
restore


/**********************************************************************
* 2. INFLATION STAGE CALENDAR
**********************************************************************/

display as text ""
display as text "=== INFLATION STAGE CALENDAR ==="

import delimited ///
    "data/raw/forecast_calendars/inflation_stage_calendar.csv", ///
    clear varnames(1) stringcols(_all)

gen double fdate = daily(forecast_date, "YMD")
gen double rdate = daily(actual_release_date, "YMD")
format fdate rdate %td

destring days_to_release, replace

assert !missing(fdate)

isid target_series target_period forecast_stage

gen byte stage_order = .
replace stage_order = 1 if forecast_stage == "month_open"
replace stage_order = 2 if forecast_stage == "mid_month"
replace stage_order = 3 if forecast_stage == "month_end"
replace stage_order = 4 if forecast_stage == "pre_release"

assert !missing(stage_order)

* Exact calendar-rule checks.
assert day(fdate) == 1 ///
    if forecast_stage == "month_open"

assert day(fdate) == 15 ///
    if forecast_stage == "mid_month"

assert fdate == dofm(mofd(fdate) + 1) - 1 ///
    if forecast_stage == "month_end"

assert fdate == rdate - 1 ///
    if forecast_stage == "pre_release"

gen calculated_days_to_release = rdate - fdate ///
    if !missing(rdate)

assert calculated_days_to_release == days_to_release ///
    if !missing(rdate)

* Check chronology wherever all four stages exist.
bysort target_series target_period: gen byte nstages = _N

sort target_series target_period stage_order
by target_series target_period: ///
    assert fdate > fdate[_n-1] if _n > 1

tab forecast_stage
tab target_series
tab nstages

preserve
collapse ///
    (count) n_origins=fdate ///
    (min) min_days=days_to_release ///
    (median) median_days=days_to_release ///
    (max) max_days=days_to_release, ///
    by(forecast_stage stage_order)

sort stage_order
list, noobs abbreviate(24)
format n_origins %9.0g
restore


/**********************************************************************
* 3. LABOUR STAGE CALENDAR
**********************************************************************/

display as text ""
display as text "=== LABOUR STAGE CALENDAR ==="

import delimited ///
    "data/raw/forecast_calendars/labour_stage_calendar.csv", ///
    clear varnames(1) stringcols(_all)

gen double fdate = daily(forecast_date, "YMD")
gen double rdate = daily(actual_release_date, "YMD")
format fdate rdate %td

destring days_to_release, replace

assert !missing(fdate)

isid target_series target_period forecast_stage

gen byte stage_order = .
replace stage_order = 1 if forecast_stage == "month_open"
replace stage_order = 2 if forecast_stage == "after_week_1"
replace stage_order = 3 if forecast_stage == "after_week_2"
replace stage_order = 4 if forecast_stage == "month_end"
replace stage_order = 5 if forecast_stage == "pre_employment_report"

assert !missing(stage_order)

assert day(fdate) == 1 ///
    if forecast_stage == "month_open"

assert day(fdate) == 7 ///
    if forecast_stage == "after_week_1"

assert day(fdate) == 14 ///
    if forecast_stage == "after_week_2"

assert fdate == dofm(mofd(fdate) + 1) - 1 ///
    if forecast_stage == "month_end"

assert fdate == rdate - 1 ///
    if forecast_stage == "pre_employment_report"

gen calculated_days_to_release = rdate - fdate

assert calculated_days_to_release == days_to_release

bysort target_series target_period: gen byte nstages = _N

sort target_series target_period stage_order

by target_series target_period: ///
    gen stage_gap_days = fdate - fdate[_n-1] if _n > 1

count if stage_gap_days < 0
assert r(N) == 0

count if stage_gap_days == 0
display as result ///
    "Same-calendar-day labour stage transitions: " r(N)

assert stage_gap_days >= 0 if !missing(stage_gap_days)

tab forecast_stage
tab target_series
tab nstages

preserve
collapse ///
    (count) n_origins=fdate ///
    (min) min_days=days_to_release ///
    (median) median_days=days_to_release ///
    (max) max_days=days_to_release, ///
    by(forecast_stage stage_order)

sort stage_order
list, noobs abbreviate(28)
format n_origins %9.0g
restore


/**********************************************************************
* 4. SCIENTIFIC DESIGN SUMMARY
**********************************************************************/

display as text ""
display as text "============================================================"
display as result "STAGE-CALENDAR AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "GDP chronological stages:"
display as text "  1 early_quarter"
display as text "  2 after_month_1"
display as text "  3 after_month_2"
display as text "  4 quarter_end"
display as text "  5 pre_advance_release"

display as text ""
display as text "Inflation chronological stages:"
display as text "  1 month_open"
display as text "  2 mid_month"
display as text "  3 month_end"
display as text "  4 pre_release"

display as text ""
display as text "Labour chronological stages:"
display as text "  1 month_open"
display as text "  2 after_week_1"
display as text "  3 after_week_2"
display as text "  4 month_end"
display as text "  5 pre_employment_report"
display as text "============================================================"
