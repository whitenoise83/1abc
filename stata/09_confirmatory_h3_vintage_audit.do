/***********************************************************************
* MacroPulse Scientific Paper
* Confirmatory H3 Vintage Counterfactual Audit
*
* File:
*   stata/09_confirmatory_h3_vintage_audit.do
*
* Purpose:
*   Independently audit the H3 RT-versus-latest-vintage paired outputs,
*   frozen stage-policy identity, mask invariance, loss algebra, and
*   reported means/medians. HAC inference remains predeclared in Python.
***********************************************************************/

version 19
clear all
set more off

display as text "============================================================"
display as text "09_confirmatory_h3_vintage_audit.do"
display as text "Confirmatory H3 vintage counterfactual audit"
display as text "============================================================"

/***********************************************************************
* 1. DETAIL-LEVEL STRUCTURAL GATES
***********************************************************************/

import delimited ///
    "outputs/confirmatory/h3_vintage_detail.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N > 0
isid domain_name target_series target_period forecast_stage

assert mask_equal == 1
assert rt_hash_verified == 1
assert final_missing_values == 0
assert raw_changed_rows >= 0
assert raw_fallback_rows >= 0

* The frozen-latest gaps audited in step 06 are WTI/inflation only.
assert domain_name == "Inflation" if raw_fallback_rows > 0

assert rt_squared_error >= 0
assert lv_squared_error >= 0
assert rt_abs_error >= 0
assert lv_abs_error >= 0

assert abs(forecast_revision - ///
    (lv_point_forecast - rt_point_forecast)) <= ///
    1e-6 * max(1, abs(forecast_revision), ///
    abs(lv_point_forecast), abs(rt_point_forecast))

assert abs(delta_squared_error - ///
    (lv_squared_error - rt_squared_error)) <= ///
    1e-6 * max(1, abs(delta_squared_error), ///
    abs(lv_squared_error), abs(rt_squared_error))

assert abs(delta_abs_error - ///
    (lv_abs_error - rt_abs_error)) <= ///
    1e-6 * max(1, abs(delta_abs_error), ///
    abs(lv_abs_error), abs(rt_abs_error))

assert abs(rolling_rt_repro_gap) <= ///
    1e-6 * max(1, abs(rt_point_forecast)) ///
    if selected_model == "Rolling Bridge–DFM Ensemble"

assert rolling_rt_w_bridge >= .10 & rolling_rt_w_bridge <= .70 ///
    if selected_model == "Rolling Bridge–DFM Ensemble"
assert rolling_lv_w_bridge >= .10 & rolling_lv_w_bridge <= .70 ///
    if selected_model == "Rolling Bridge–DFM Ensemble"

tempfile h3_detail
save `h3_detail'

/***********************************************************************
* 2. SAMPLE-COMPOSITION AUDIT
***********************************************************************/

use `h3_detail', clear

gen expected_stage_count = .
replace expected_stage_count = 5 if domain_name == "GDP"
replace expected_stage_count = 4 if domain_name == "Inflation"
replace expected_stage_count = 5 if domain_name == "Labour"
assert !missing(expected_stage_count)

bysort domain_name target_series target_period: ///
    gen observed_stage_count = _N

gen complete_stage_set = ///
    observed_stage_count == expected_stage_count

gen primary_included = 1
gen secondary_included = complete_stage_set

keep domain_name target_series target_period ///
    expected_stage_count observed_stage_count complete_stage_set ///
    primary_included secondary_included
duplicates drop

rename expected_stage_count expected_stage_count_using
rename observed_stage_count observed_stage_count_using
rename complete_stage_set complete_stage_set_using
rename primary_included primary_included_using
rename secondary_included secondary_included_using

tempfile sample_reproduced
save `sample_reproduced'

import delimited ///
    "outputs/confirmatory/h3_vintage_sample_audit.csv", ///
    clear varnames(1) encoding("UTF-8")

isid domain_name target_series target_period

* CSV header secondary_target_summary_included is 33 characters.
* Stata truncates it on import. Resolve both inclusion columns by prefix.
ds primary_stage_cell*
local primaryvar `r(varlist)'
assert wordcount("`primaryvar'") == 1
rename `primaryvar' primary_included

ds secondary_target_summary*
local secondaryvar `r(varlist)'
assert wordcount("`secondaryvar'") == 1
rename `secondaryvar' secondary_included

merge 1:1 domain_name target_series target_period ///
    using `sample_reproduced'

assert _merge == 3
drop _merge

assert expected_stage_count == expected_stage_count_using
assert observed_stage_count == observed_stage_count_using
assert complete_stage_set == complete_stage_set_using
assert primary_included == primary_included_using
assert secondary_included == secondary_included_using

/***********************************************************************
* 3. FROZEN STAGE-POLICY IDENTITY
***********************************************************************/

import delimited ///
    "freeze/research_stage_policy_freeze.csv", ///
    clear varnames(1) encoding("UTF-8")

keep domain_name target_series stage_order forecast_stage selected_model
rename selected_model frozen_model

tempfile frozen_policy
save `frozen_policy'

use `h3_detail', clear
merge m:1 domain_name target_series stage_order forecast_stage ///
    using `frozen_policy'

assert _merge == 3
drop _merge
assert selected_model == frozen_model
drop frozen_model

/***********************************************************************
* 4. STAGE-CELL SUMMARY REPRODUCTION
***********************************************************************/

preserve
collapse ///
    (count) n=delta_squared_error ///
    (mean) mean_delta_squared_error=delta_squared_error ///
           mean_delta_abs_error=delta_abs_error ///
    (median) median_delta_squared_error=delta_squared_error ///
             median_delta_abs_error=delta_abs_error, ///
    by(domain_name target_series stage_order forecast_stage selected_model)

rename n n_using
rename mean_delta_squared_error mean_delta_squared_error_using
rename mean_delta_abs_error mean_delta_abs_error_using
rename median_delta_squared_error median_delta_squared_error_using
rename median_delta_abs_error median_delta_abs_error_using

tempfile stage_reproduced
save `stage_reproduced'
restore

import delimited ///
    "outputs/confirmatory/h3_vintage_summary.csv", ///
    clear varnames(1) encoding("UTF-8")

isid domain_name target_series stage_order
merge 1:1 domain_name target_series stage_order forecast_stage selected_model ///
    using `stage_reproduced'

assert _merge == 3
drop _merge
assert n == n_using

assert abs(mean_delta_squared_error - mean_delta_squared_error_using) <= ///
    1e-6 * max(1, abs(mean_delta_squared_error), ///
    abs(mean_delta_squared_error_using))
assert abs(median_delta_squared_error - median_delta_squared_error_using) <= ///
    1e-6 * max(1, abs(median_delta_squared_error), ///
    abs(median_delta_squared_error_using))
assert abs(mean_delta_abs_error - mean_delta_abs_error_using) <= ///
    1e-6 * max(1, abs(mean_delta_abs_error), ///
    abs(mean_delta_abs_error_using))
assert abs(median_delta_abs_error - median_delta_abs_error_using) <= ///
    1e-6 * max(1, abs(median_delta_abs_error), ///
    abs(median_delta_abs_error_using))

/***********************************************************************
* 5. TARGET-LEVEL STAGE-AVERAGED SUMMARY REPRODUCTION
***********************************************************************/

use `h3_detail', clear

gen expected_stage_count = .
replace expected_stage_count = 5 if domain_name == "GDP"
replace expected_stage_count = 4 if domain_name == "Inflation"
replace expected_stage_count = 5 if domain_name == "Labour"

bysort domain_name target_series target_period: ///
    gen observed_stage_count = _N

keep if observed_stage_count == expected_stage_count

collapse ///
    (mean) delta_squared_error delta_abs_error, ///
    by(domain_name target_series target_period)

collapse ///
    (count) periods=delta_squared_error ///
    (mean) mean_stageavg_delta_sq=delta_squared_error ///
           mean_stageavg_delta_abs=delta_abs_error ///
    (median) median_stageavg_delta_sq=delta_squared_error ///
             median_stageavg_delta_abs=delta_abs_error, ///
    by(domain_name target_series)

rename periods periods_using
rename mean_stageavg_delta_sq mean_stageavg_delta_sq_using
rename mean_stageavg_delta_abs mean_stageavg_delta_abs_using
rename median_stageavg_delta_sq median_stageavg_delta_sq_using
rename median_stageavg_delta_abs median_stageavg_delta_abs_using

tempfile target_reproduced
save `target_reproduced'

import delimited ///
    "outputs/confirmatory/h3_vintage_target_summary.csv", ///
    clear varnames(1) encoding("UTF-8")

isid domain_name target_series
merge 1:1 domain_name target_series using `target_reproduced'

assert _merge == 3
drop _merge
assert periods == periods_using

assert abs(mean_stageavg_delta_sq - mean_stageavg_delta_sq_using) <= ///
    1e-6 * max(1, abs(mean_stageavg_delta_sq), ///
    abs(mean_stageavg_delta_sq_using))
assert abs(median_stageavg_delta_sq - median_stageavg_delta_sq_using) <= ///
    1e-6 * max(1, abs(median_stageavg_delta_sq), ///
    abs(median_stageavg_delta_sq_using))
assert abs(mean_stageavg_delta_abs - mean_stageavg_delta_abs_using) <= ///
    1e-6 * max(1, abs(mean_stageavg_delta_abs), ///
    abs(mean_stageavg_delta_abs_using))
assert abs(median_stageavg_delta_abs - median_stageavg_delta_abs_using) <= ///
    1e-6 * max(1, abs(median_stageavg_delta_abs), ///
    abs(median_stageavg_delta_abs_using))

/***********************************************************************
* 6. FINAL GATE
***********************************************************************/

display as text ""
display as text "============================================================"
display as result "CONFIRMATORY H3 AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "Verified:"
display as text "  - exact RT/LV historical availability-mask equality"
display as text "  - source RT information-set hash verification"
display as text "  - no missing values after frozen-latest fallback"
display as text "  - frozen development-selected stage-policy identity"
display as text "  - H3 loss-differential algebra"
display as text "  - GDP rolling RT recursive-weight reproduction"
display as text "  - unbalanced primary stage-cell sample is preserved"
display as text "  - complete-stage rule for secondary target summaries"
display as text "  - stage-cell means and medians"
display as text "  - target-level stage-averaged means and medians"
display as text "============================================================"
