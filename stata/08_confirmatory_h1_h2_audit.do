/***********************************************************************
* MacroPulse Scientific Paper
* Confirmatory H1/H2 Evaluation Audit
*
* File:
*   stata/08_confirmatory_h1_h2_audit.do
***********************************************************************/

version 19
clear all
set more off

display as text "============================================================"
display as text "08_confirmatory_h1_h2_audit.do"
display as text "Confirmatory H1/H2 evaluation audit"
display as text "============================================================"

/***********************************************************************
* 1. H1 DETAIL
***********************************************************************/

import delimited ///
    "outputs/confirmatory/h1_information_gain_detail.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N > 0
isid domain_name target_series transition_order target_period

assert later_squared_error >= 0
assert earlier_squared_error >= 0
assert later_abs_error >= 0
assert earlier_abs_error >= 0

assert abs(delta_squared_error - ///
    (later_squared_error - earlier_squared_error)) <= ///
    1e-6 * max(1, abs(delta_squared_error), ///
    abs(later_squared_error), abs(earlier_squared_error))

assert abs(delta_abs_error - ///
    (later_abs_error - earlier_abs_error)) <= ///
    1e-6 * max(1, abs(delta_abs_error), ///
    abs(later_abs_error), abs(earlier_abs_error))

assert eligible_h1 == hash_changed
assert hash_changed == ///
    (earlier_information_set_hash != later_information_set_hash)

assert domain_name == "Labour" if eligible_h1 == 0
assert earlier_stage == "month_end" if eligible_h1 == 0
assert later_stage == "pre_employment_report" if eligible_h1 == 0

tempfile h1_detail
save `h1_detail'

/***********************************************************************
* 2. H1 SUMMARY REPRODUCTION
***********************************************************************/

preserve
keep if eligible_h1 == 1

collapse ///
    (count) eligible_pairs=delta_squared_error ///
    (mean) mean_delta_squared_error=delta_squared_error ///
           mean_delta_abs_error=delta_abs_error ///
    (median) median_delta_squared_error=delta_squared_error ///
             median_delta_abs_error=delta_abs_error, ///
    by(domain_name target_series transition_order earlier_stage later_stage fixed_model)

rename eligible_pairs eligible_pairs_using
rename mean_delta_squared_error mean_delta_squared_error_using
rename mean_delta_abs_error mean_delta_abs_error_using
rename median_delta_squared_error median_delta_squared_error_using
rename median_delta_abs_error median_delta_abs_error_using

tempfile h1_reproduced
save `h1_reproduced'
restore

import delimited ///
    "outputs/confirmatory/h1_information_gain_summary.csv", ///
    clear varnames(1) encoding("UTF-8")

isid domain_name target_series transition_order

merge 1:1 domain_name target_series transition_order ///
    earlier_stage later_stage fixed_model using `h1_reproduced'

assert _merge == 3
drop _merge

assert eligible_pairs == eligible_pairs_using

assert abs(mean_delta_squared_error - mean_delta_squared_error_using) <= ///
    1e-6 * max(1, abs(mean_delta_squared_error), abs(mean_delta_squared_error_using))

assert abs(mean_delta_abs_error - mean_delta_abs_error_using) <= ///
    1e-6 * max(1, abs(mean_delta_abs_error), abs(mean_delta_abs_error_using))

assert abs(median_delta_squared_error - median_delta_squared_error_using) <= ///
    1e-6 * max(1, abs(median_delta_squared_error), abs(median_delta_squared_error_using))

assert abs(median_delta_abs_error - median_delta_abs_error_using) <= ///
    1e-6 * max(1, abs(median_delta_abs_error), abs(median_delta_abs_error_using))

/***********************************************************************
* 3. H2 DETAIL
***********************************************************************/

import delimited ///
    "outputs/confirmatory/h2_stage_policy_detail.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N > 0
isid domain_name target_series stage_order target_period

assert stage_policy_squared_error >= 0
assert fixed_squared_error >= 0
assert stage_policy_abs_error >= 0
assert fixed_abs_error >= 0

assert abs(delta_squared_error - ///
    (stage_policy_squared_error - fixed_squared_error)) <= ///
    1e-6 * max(1, abs(delta_squared_error), ///
    abs(stage_policy_squared_error), abs(fixed_squared_error))

assert abs(delta_abs_error - ///
    (stage_policy_abs_error - fixed_abs_error)) <= ///
    1e-6 * max(1, abs(delta_abs_error), ///
    abs(stage_policy_abs_error), abs(fixed_abs_error))

assert abs(delta_squared_error) <= 1e-10 if stage_policy_model == fixed_model
assert abs(delta_abs_error) <= 1e-10 if stage_policy_model == fixed_model

tempfile h2_detail
save `h2_detail'

/***********************************************************************
* 4. H2 SUMMARY REPRODUCTION
***********************************************************************/

collapse ///
    (count) n=delta_squared_error ///
    (mean) mean_delta_squared_error=delta_squared_error ///
           mean_delta_abs_error=delta_abs_error ///
    (median) median_delta_squared_error=delta_squared_error ///
             median_delta_abs_error=delta_abs_error, ///
    by(domain_name target_series stage_order forecast_stage ///
       stage_policy_model fixed_model)

rename n n_using
rename mean_delta_squared_error mean_delta_squared_error_using
rename mean_delta_abs_error mean_delta_abs_error_using
rename median_delta_squared_error median_delta_squared_error_using
rename median_delta_abs_error median_delta_abs_error_using

tempfile h2_reproduced
save `h2_reproduced'

import delimited ///
    "outputs/confirmatory/h2_stage_policy_summary.csv", ///
    clear varnames(1) encoding("UTF-8")

isid domain_name target_series stage_order

merge 1:1 domain_name target_series stage_order forecast_stage ///
    stage_policy_model fixed_model using `h2_reproduced'

assert _merge == 3
drop _merge

assert n == n_using

assert abs(mean_delta_squared_error - mean_delta_squared_error_using) <= ///
    1e-6 * max(1, abs(mean_delta_squared_error), abs(mean_delta_squared_error_using))

assert abs(mean_delta_abs_error - mean_delta_abs_error_using) <= ///
    1e-6 * max(1, abs(mean_delta_abs_error), abs(mean_delta_abs_error_using))

assert abs(median_delta_squared_error - median_delta_squared_error_using) <= ///
    1e-6 * max(1, abs(median_delta_squared_error), abs(median_delta_squared_error_using))

assert abs(median_delta_abs_error - median_delta_abs_error_using) <= ///
    1e-6 * max(1, abs(median_delta_abs_error), abs(median_delta_abs_error_using))

/***********************************************************************
* 5. FINAL GATE
***********************************************************************/

display as text ""
display as text "============================================================"
display as result "CONFIRMATORY H1/H2 AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "Verified:"
display as text "  - H1 adjacent-stage loss-difference algebra"
display as text "  - H1 information-set-hash eligibility rule"
display as text "  - H1 same-hash exclusions restricted to Labour final transition"
display as text "  - H1 summary means and medians"
display as text "  - H2 same-stage paired loss-difference algebra"
display as text "  - H2 exact zero differential when policy equals comparator"
display as text "  - H2 summary means and medians"
display as text "============================================================"
