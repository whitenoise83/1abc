/***********************************************************************
* MacroPulse Scientific Paper
* Development-Only Research Policy Freeze Audit
*
* File:
*   stata/07_policy_freeze_audit.do
***********************************************************************/

version 19
clear all
set more off

display as text "============================================================"
display as text "07_policy_freeze_audit.do"
display as text "Development-only research policy freeze audit"
display as text "============================================================"


/***********************************************************************
* 1. STAGE POLICY FREEZE
***********************************************************************/

import delimited ///
    "freeze/research_stage_policy_freeze.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N == 36
isid domain_name target_series forecast_stage

assert selected_model != ""
assert development_n > 0
assert development_mse >= 0
assert development_rmse >= 0
assert development_mae >= 0
assert abs(development_rmse - sqrt(development_mse)) <= 1e-6 * max(1, abs(development_rmse))
assert abs(tie_tolerance - 1e-12) <= 1e-18

count if domain_name == "GDP"
assert r(N) == 5

count if domain_name == "Inflation"
assert r(N) == 16

count if domain_name == "Labour"
assert r(N) == 15

foreach target in CPIAUCSL CPILFESL PCEPI PCEPILFE {
    count if domain_name == "Inflation" & target_series == "`target'"
    assert r(N) == 4
}

foreach target in CES0500000003 PAYEMS UNRATE {
    count if domain_name == "Labour" & target_series == "`target'"
    assert r(N) == 5
}

tempfile stage_policy
save `stage_policy'


/***********************************************************************
* 2. COMMON-SAMPLE AUDIT
***********************************************************************/

import delimited ///
    "freeze/research_policy_common_sample_audit.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N == 36
isid domain_name target_series forecast_stage

assert common_origins > 0
assert common_rows == common_origins * candidate_count
assert actual_consistent == 1
assert length(common_key_sha256) == 64

assert candidate_count == 5 if domain_name == "GDP"
assert candidate_count == 4 if domain_name == "Inflation"
assert candidate_count == 5 if domain_name == "Labour"

merge 1:1 domain_name target_series forecast_stage using `stage_policy'
assert _merge == 3
drop _merge

assert development_n == common_origins

drop selected_model development_n development_mse development_rmse ///
     development_mae selection_rule tie_tolerance stage_order

tempfile common_audit
save `common_audit'


/***********************************************************************
* 3. STAGE-WINNER CONSISTENCY AGAINST DEVELOPMENT METRICS
***********************************************************************/

import delimited ///
    "outputs/tables/research_stage_candidate_development_metrics.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N == 164
isid domain_name target_series forecast_stage model_name

bysort domain_name target_series forecast_stage: egen double min_mse = min(mse)
gen byte mse_tie = abs(mse - min_mse) <= 1e-12

bysort domain_name target_series forecast_stage: ///
    egen double min_mae_tie = min(cond(mse_tie == 1, mae, .))

merge m:1 domain_name target_series forecast_stage using `stage_policy'
assert _merge == 3
drop _merge

gen byte is_selected = model_name == selected_model
bysort domain_name target_series forecast_stage: egen byte selected_count = total(is_selected)
assert selected_count == 1

assert abs(mse - min_mse) <= 1e-12 if is_selected
assert abs(mae - min_mae_tie) <= 1e-12 if is_selected
assert n == development_n if is_selected

drop min_mse mse_tie min_mae_tie is_selected selected_count ///
     selected_model development_n development_mse development_rmse ///
     development_mae selection_rule tie_tolerance

merge m:1 domain_name target_series forecast_stage using `common_audit'
assert _merge == 3
drop _merge

assert n == common_origins


/***********************************************************************
* 4. FIXED-COMPARATOR FREEZE
***********************************************************************/

import delimited ///
    "freeze/research_fixed_comparator_freeze.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N == 8
isid domain_name target_series

assert selected_model != ""
assert development_n > 0
assert development_mse >= 0
assert development_rmse >= 0
assert development_mae >= 0
assert abs(development_rmse - sqrt(development_mse)) <= 1e-6 * max(1, abs(development_rmse))
assert abs(tie_tolerance - 1e-12) <= 1e-18

count if domain_name == "GDP"
assert r(N) == 1

count if domain_name == "Inflation"
assert r(N) == 4

count if domain_name == "Labour"
assert r(N) == 3

assert stage_count == 5 if domain_name == "GDP"
assert stage_count == 4 if domain_name == "Inflation"
assert stage_count == 5 if domain_name == "Labour"

tempfile fixed_policy
save `fixed_policy'


/***********************************************************************
* 5. FIXED-WINNER CONSISTENCY AGAINST DEVELOPMENT METRICS
***********************************************************************/

import delimited ///
    "outputs/tables/research_fixed_candidate_development_metrics.csv", ///
    clear varnames(1) encoding("UTF-8")

assert _N == 36
isid domain_name target_series model_name

bysort domain_name target_series: egen double min_mse = min(mse)
gen byte mse_tie = abs(mse - min_mse) <= 1e-12

bysort domain_name target_series: ///
    egen double min_mae_tie = min(cond(mse_tie == 1, mae, .))

merge m:1 domain_name target_series using `fixed_policy'
assert _merge == 3
drop _merge

gen byte is_selected = model_name == selected_model
bysort domain_name target_series: egen byte selected_count = total(is_selected)
assert selected_count == 1

assert abs(mse - min_mse) <= 1e-12 if is_selected
assert abs(mae - min_mae_tie) <= 1e-12 if is_selected
assert n == development_n if is_selected


/***********************************************************************
* 6. FINAL FREEZE GATE
***********************************************************************/

display as text ""
display as text "============================================================"
display as result "RESEARCH POLICY FREEZE AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "Verified:"
display as text "  - 36 development-only target-stage policy decisions"
display as text "  - 8 development-only fixed target comparators"
display as text "  - exact common-candidate samples at every target-stage"
display as text "  - minimum-MSE / MAE tie-break consistency"
display as text "  - no evaluation metrics are required by this audit"
display as text "============================================================"
