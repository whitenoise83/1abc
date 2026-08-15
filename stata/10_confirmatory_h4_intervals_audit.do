/***********************************************************************
* MacroPulse Scientific Paper
* Confirmatory H4 Prior-Only Prediction-Interval Audit
*
* File:
*   stata/10_confirmatory_h4_intervals_audit.do
*
* Purpose:
*   Independently audit H4 output structure, frozen research-policy
*   identity, strict release-date eligibility, interval algebra,
*   coverage/width/score summaries, and primary-vs-benchmark means.
*
* Note:
*   Exact weighted-quantile construction and HAC standard errors remain
*   frozen in the precommitted Python implementation. This Stata audit
*   independently verifies the resulting interval arithmetic and reported
*   non-HAC summary quantities.
***********************************************************************/

version 19
clear all
set more off

display as text "============================================================"
display as text "10_confirmatory_h4_intervals_audit.do"
display as text "Confirmatory H4 prior-only interval audit"
display as text "============================================================"

/***********************************************************************
* 1. DETAIL-LEVEL STRUCTURAL AND ALGEBRAIC GATES
***********************************************************************/

import delimited ///
    "outputs/confirmatory/h4_interval_detail.csv", ///
    clear varnames(1) encoding("UTF-8") asdouble

assert _N > 0
isid domain_name target_series target_period forecast_stage interval_method

assert abs(nominal_coverage - .8) <= 1e-6
assert inlist(eligible_h4, 0, 1)
assert inlist(is_primary, 0, 1)

assert interval_method == "rolling_q80" if domain_name == "GDP" & is_primary == 1
assert interval_method == "exp_weighted_q80" if ///
    inlist(domain_name, "Inflation", "Labour") & is_primary == 1

assert calibration_window == 20 if domain_name == "GDP"
assert minimum_prior_errors == 12 if domain_name == "GDP"
assert calibration_window == 48 if inlist(domain_name, "Inflation", "Labour")
assert minimum_prior_errors == 24 if inlist(domain_name, "Inflation", "Labour")

assert calibration_window_count <= calibration_window
assert prior_observable_error_count >= calibration_window_count
assert calibration_window_count >= minimum_prior_errors if eligible_h4 == 1
assert calibration_window_count < minimum_prior_errors if eligible_h4 == 0

gen double fd = date(forecast_date, "YMD")
gen double ard = date(actual_release_date, "YMD")
gen double maxcal = date(max_calibration_release_date, "YMD")
format fd ard maxcal %td

assert !missing(fd)
assert !missing(ard)
assert maxcal < fd if eligible_h4 == 1
assert calibration_cutoff_target_period != "" if eligible_h4 == 1

assert missing(interval_half_width) if eligible_h4 == 0
assert missing(lower_80) if eligible_h4 == 0
assert missing(upper_80) if eligible_h4 == 0
assert missing(interval_covered) if eligible_h4 == 0
assert missing(interval_score) if eligible_h4 == 0

assert interval_half_width >= 0 if eligible_h4 == 1
assert interval_width >= 0 if eligible_h4 == 1

assert abs(lower_80 - (point_forecast - interval_half_width)) <= ///
    1e-6 * max(1, abs(lower_80), abs(point_forecast), ///
    abs(interval_half_width)) if eligible_h4 == 1

assert abs(upper_80 - (point_forecast + interval_half_width)) <= ///
    1e-6 * max(1, abs(upper_80), abs(point_forecast), ///
    abs(interval_half_width)) if eligible_h4 == 1

assert abs(interval_width - (upper_80 - lower_80)) <= ///
    1e-6 * max(1, abs(interval_width), abs(upper_80), ///
    abs(lower_80)) if eligible_h4 == 1

gen byte covered_reproduced = ///
    actual >= lower_80 & actual <= upper_80 if eligible_h4 == 1
gen byte lower_reproduced = actual < lower_80 if eligible_h4 == 1
gen byte upper_reproduced = actual > upper_80 if eligible_h4 == 1

assert interval_covered == covered_reproduced if eligible_h4 == 1
assert lower_miss == lower_reproduced if eligible_h4 == 1
assert upper_miss == upper_reproduced if eligible_h4 == 1
assert violation == 1 - interval_covered if eligible_h4 == 1
assert lower_miss + upper_miss == violation if eligible_h4 == 1

gen double score_reproduced = interval_width if eligible_h4 == 1
replace score_reproduced = score_reproduced + ///
    10 * (lower_80 - actual) if eligible_h4 == 1 & actual < lower_80
replace score_reproduced = score_reproduced + ///
    10 * (actual - upper_80) if eligible_h4 == 1 & actual > upper_80

assert abs(interval_score - score_reproduced) <= ///
    1e-6 * max(1, abs(interval_score), abs(score_reproduced)) ///
    if eligible_h4 == 1

tempfile h4_detail
save `h4_detail'

/***********************************************************************
* 2. FROZEN RESEARCH STAGE-POLICY IDENTITY
***********************************************************************/

import delimited ///
    "freeze/research_stage_policy_freeze.csv", ///
    clear varnames(1) encoding("UTF-8") asdouble

keep domain_name target_series stage_order forecast_stage selected_model
rename selected_model frozen_model
tempfile frozen_policy
save `frozen_policy'

use `h4_detail', clear
merge m:1 domain_name target_series stage_order forecast_stage ///
    using `frozen_policy'

assert _merge == 3
drop _merge
assert selected_model == frozen_model
drop frozen_model

/***********************************************************************
* 3. ELIGIBILITY-AUDIT REPRODUCTION FROM PRIMARY DETAIL
***********************************************************************/

keep if is_primary == 1
keep domain_name target_series stage_order forecast_stage target_period ///
    selected_model forecast_date actual_release_date ///
    prior_observable_error_count calibration_window_count ///
    minimum_prior_errors calibration_window ///
    calibration_cutoff_target_period max_calibration_release_date ///
    eligible_h4

rename prior_observable_error_count prior_count_using
rename calibration_window_count window_count_using
rename minimum_prior_errors min_prior_using
rename calibration_window window_using
rename calibration_cutoff_target_period cutoff_period_using
rename max_calibration_release_date max_release_using
rename eligible_h4 eligible_using

tempfile eligibility_reproduced
save `eligibility_reproduced'

import delimited ///
    "outputs/confirmatory/h4_interval_eligibility_audit.csv", ///
    clear varnames(1) encoding("UTF-8") asdouble

isid domain_name target_series target_period forecast_stage

merge 1:1 domain_name target_series stage_order forecast_stage target_period ///
    selected_model forecast_date actual_release_date ///
    using `eligibility_reproduced'

assert _merge == 3
drop _merge

assert prior_observable_error_count == prior_count_using
assert calibration_window_count == window_count_using
assert minimum_prior_errors == min_prior_using
assert calibration_window == window_using
assert calibration_cutoff_target_period == cutoff_period_using
assert max_calibration_release_date == max_release_using
assert eligible_h4 == eligible_using

/***********************************************************************
* 4. STAGE-CELL SUMMARY REPRODUCTION
***********************************************************************/

use `h4_detail', clear
keep if eligible_h4 == 1

collapse ///
    (count) n_reproduced=interval_covered ///
    (sum) covered_reproduced=interval_covered ///
          violations_reproduced=violation ///
          lower_misses_reproduced=lower_miss ///
          upper_misses_reproduced=upper_miss ///
    (mean) avg_width_reproduced=interval_width ///
           avg_half_reproduced=interval_half_width ///
           mean_score_reproduced=interval_score ///
    (median) median_score_reproduced=interval_score ///
    (min) min_cal_reproduced=calibration_window_count ///
    (max) max_cal_reproduced=calibration_window_count, ///
    by(domain_name target_series stage_order forecast_stage selected_model ///
       interval_method is_primary)

gen double coverage_reproduced = covered_reproduced / n_reproduced
gen double lower_rate_reproduced = lower_misses_reproduced / n_reproduced
gen double upper_rate_reproduced = upper_misses_reproduced / n_reproduced

tempfile summary_reproduced
save `summary_reproduced'

import delimited ///
    "outputs/confirmatory/h4_interval_summary.csv", ///
    clear varnames(1) encoding("UTF-8") asdouble

isid domain_name target_series stage_order interval_method
merge 1:1 domain_name target_series stage_order forecast_stage ///
    selected_model interval_method is_primary using `summary_reproduced'

assert _merge == 3
drop _merge

assert n == n_reproduced
assert covered == covered_reproduced
assert violations == violations_reproduced

assert abs(coverage - coverage_reproduced) <= 1e-10
assert abs(average_interval_width - avg_width_reproduced) <= ///
    1e-6 * max(1, abs(average_interval_width), abs(avg_width_reproduced))
assert abs(average_half_width - avg_half_reproduced) <= ///
    1e-6 * max(1, abs(average_half_width), abs(avg_half_reproduced))
assert abs(mean_interval_score - mean_score_reproduced) <= ///
    1e-6 * max(1, abs(mean_interval_score), abs(mean_score_reproduced))
assert abs(median_interval_score - median_score_reproduced) <= ///
    1e-6 * max(1, abs(median_interval_score), abs(median_score_reproduced))
assert abs(lower_miss_rate - lower_rate_reproduced) <= 1e-10
assert abs(upper_miss_rate - upper_rate_reproduced) <= 1e-10
assert minimum_calibration_count == min_cal_reproduced
assert maximum_calibration_count == max_cal_reproduced

* Independently reproduce the 95% Wilson interval.
local z = 1.959963984540054
gen double phat = covered / n
gen double wden = 1 + (`z'^2)/n
gen double wcenter = (phat + (`z'^2)/(2*n)) / wden
gen double whalf = `z' * ///
    sqrt(phat*(1-phat)/n + (`z'^2)/(4*n^2)) / wden
gen double wilson_low_reproduced = max(0, wcenter-whalf)
gen double wilson_high_reproduced = min(1, wcenter+whalf)

assert abs(wilson_95_low - wilson_low_reproduced) <= 1e-10
assert abs(wilson_95_high - wilson_high_reproduced) <= 1e-10

/***********************************************************************
* 5. PRIMARY-vs-BENCHMARK MEAN COMPARISON REPRODUCTION
***********************************************************************/

use `h4_detail', clear
keep if eligible_h4 == 1

preserve
keep if is_primary == 1
keep domain_name target_series stage_order forecast_stage target_period ///
    selected_model interval_method interval_score interval_width ///
    interval_covered
rename interval_method primary_method
rename interval_score primary_score
rename interval_width primary_width
rename interval_covered primary_covered
tempfile primary
save `primary'
restore

keep if is_primary == 0
keep domain_name target_series stage_order forecast_stage target_period ///
    selected_model interval_method interval_score interval_width ///
    interval_covered
rename interval_method benchmark_method
rename interval_score benchmark_score
rename interval_width benchmark_width
rename interval_covered benchmark_covered

merge m:1 domain_name target_series stage_order forecast_stage target_period ///
    selected_model using `primary'
assert _merge == 3
drop _merge

gen double score_diff = primary_score - benchmark_score
gen double width_diff = primary_width - benchmark_width
gen double coverage_diff = primary_covered - benchmark_covered

collapse ///
    (count) n_reproduced=score_diff ///
    (sum) primary_covered_sum=primary_covered ///
          benchmark_covered_sum=benchmark_covered ///
          coverage_diff_sum=coverage_diff ///
    (mean) mean_score_diff_reproduced=score_diff ///
           mean_width_diff_reproduced=width_diff ///
    (median) median_score_diff_reproduced=score_diff ///
             median_width_diff_reproduced=width_diff, ///
    by(domain_name target_series stage_order forecast_stage selected_model ///
       primary_method benchmark_method)

gen double primary_coverage_reproduced = primary_covered_sum / n_reproduced
gen double benchmark_coverage_reproduced = benchmark_covered_sum / n_reproduced
gen double coverage_diff_reproduced = coverage_diff_sum / n_reproduced

tempfile comparison_reproduced
save `comparison_reproduced'

import delimited ///
    "outputs/confirmatory/h4_interval_method_comparisons.csv", ///
    clear varnames(1) encoding("UTF-8") asdouble

isid domain_name target_series stage_order benchmark_method
merge 1:1 domain_name target_series stage_order forecast_stage selected_model ///
    primary_method benchmark_method using `comparison_reproduced'

assert _merge == 3
drop _merge

assert n == n_reproduced
assert abs(primary_coverage - primary_coverage_reproduced) <= 1e-10
assert abs(benchmark_coverage - benchmark_coverage_reproduced) <= 1e-10
assert abs(coverage_diff_p_minus_b - ///
    coverage_diff_reproduced) <= 1e-10
assert abs(mean_score_diff_p_minus_b - ///
    mean_score_diff_reproduced) <= ///
    1e-6 * max(1, abs(mean_score_diff_p_minus_b), ///
    abs(mean_score_diff_reproduced))
assert abs(median_score_diff_p_minus_b - ///
    median_score_diff_reproduced) <= ///
    1e-6 * max(1, abs(median_score_diff_p_minus_b), ///
    abs(median_score_diff_reproduced))
assert abs(mean_width_diff_p_minus_b - ///
    mean_width_diff_reproduced) <= ///
    1e-6 * max(1, abs(mean_width_diff_p_minus_b), ///
    abs(mean_width_diff_reproduced))
assert abs(median_width_diff_p_minus_b - ///
    median_width_diff_reproduced) <= ///
    1e-6 * max(1, abs(median_width_diff_p_minus_b), ///
    abs(median_width_diff_reproduced))

/***********************************************************************
* 6. FINAL GATE
***********************************************************************/

display as text ""
display as text "============================================================"
display as result "CONFIRMATORY H4 AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "Verified:"
display as text "  - frozen research stage-policy identity"
display as text "  - domain-specific H4 method/minimum/window declarations"
display as text "  - strict prior-release-date calibration cutoff"
display as text "  - warm-up/ineligibility treatment"
display as text "  - interval lower/upper/width algebra"
display as text "  - inclusive coverage and tail-miss classification"
display as text "  - 80% Winkler interval-score algebra"
display as text "  - eligibility audit agreement"
display as text "  - stage-cell coverage, width, score, and Wilson summaries"
display as text "  - primary-vs-benchmark mean/median comparisons"
display as text "============================================================"
