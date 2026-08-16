version 19.0
clear all
set more off

local root "."
local out "`root'/outputs/robustness"

capture confirm file "`out'/robustness_manifest.json"
if _rc {
    display as error "Robustness manifest not found."
    exit 601
}

display "============================================================"
display "ROBUSTNESS R1-R5 STATA AUDIT"
display "============================================================"

* R1 summary: 28 adjacent-stage tests and arithmetic flags.
import delimited using "`out'/r1_h1_alternative_fixed_summary.csv", varnames(1) clear case(preserve) asdouble
assert _N == 28
assert eligible_pairs > 0
assert inlist(sq_sign_concordant_with_primary,0,1)
assert inlist(abs_sign_concordant_with_primary,0,1)
count if hac_p_sq < .05 & mean_delta_squared_error < 0
display "R1 nominal squared-loss improvements: " r(N)
count if hac_p_sq < .05 & mean_delta_squared_error > 0
display "R1 nominal squared-loss deteriorations: " r(N)

* R2 summary: 36 target-stage cells.
import delimited using "`out'/r2_h2_shortdev_summary.csv", varnames(1) clear case(preserve) asdouble
assert _N == 36
assert inlist(same_model,0,1)
assert abs(mean_delta_squared_error) < 1e-12 if same_model == 1
assert abs(mean_delta_abs_error) < 1e-12 if same_model == 1
count if same_model == 0
display "R2 informative cells: " r(N)
count if same_model == 0 & hac_p_sq < .05 & mean_delta_squared_error < 0
display "R2 nominal squared-loss policy gains: " r(N)
count if same_model == 0 & hac_p_sq < .05 & mean_delta_squared_error > 0
display "R2 nominal squared-loss policy losses: " r(N)

* R3 archived stage-level heterogeneity: 36 stage cells, 8 targets.
import delimited using "`out'/r3_h3_stage_heterogeneity.csv", varnames(1) clear case(preserve) asdouble
assert _N == 36
assert inlist(sq_latest_better,0,1)
assert inlist(abs_latest_better,0,1)

import delimited using "`out'/r3_h3_target_stage_concordance.csv", varnames(1) clear case(preserve) asdouble
assert _N == 8
assert stage_count >= 4 & stage_count <= 5
assert sq_latest_better_stages >= 0 & sq_latest_better_stages <= stage_count
assert abs_latest_better_stages >= 0 & abs_latest_better_stages <= stage_count

* R4 detail: 1,302 evaluation cells x 2 variants.
import delimited using "`out'/r4_h4_memory_detail.csv", varnames(1) clear case(preserve) asdouble
assert _N == 2604
assert abs(interval_width - (upper_80-lower_80)) < 1e-8 * max(1,abs(interval_width))
assert abs(interval_half_width - interval_width/2) < 1e-8 * max(1,abs(interval_width))
assert inlist(interval_covered,0,1)
assert violation == 1-interval_covered
gen double score_repro = interval_width
replace score_repro = score_repro + 10*(lower_80-actual) if actual < lower_80
replace score_repro = score_repro + 10*(actual-upper_80) if actual > upper_80
assert abs(interval_score-score_repro) < 1e-8 * max(1,abs(interval_score))

import delimited using "`out'/r4_h4_memory_summary.csv", varnames(1) clear case(preserve) asdouble
assert _N == 72
assert covered >= 0 & covered <= n
assert abs(coverage - covered/n) < 1e-12

import delimited using "`out'/r4_h4_memory_comparisons.csv", varnames(1) clear case(preserve) asdouble
assert _N == 72
assert n > 0

* R5 family counts and Holm arithmetic bounds.
import delimited using "`out'/r5_holm_adjusted_pvalues.csv", varnames(1) clear case(preserve) asdouble
assert raw_p >= 0 & raw_p <= 1
assert holm_p >= raw_p if !missing(raw_p,holm_p)
assert holm_p >= 0 & holm_p <= 1 if !missing(holm_p)
assert raw_sig_005 == (raw_p < .05)
assert holm_sig_005 == (holm_p < .05)

count if test_family == "H1_squared_error"
assert r(N) == 28
count if test_family == "H1_absolute_error"
assert r(N) == 28
count if test_family == "H2_squared_error_informative_cells"
assert r(N) == 11
count if test_family == "H2_absolute_error_informative_cells"
assert r(N) == 11
count if test_family == "H3_target_squared_error"
assert r(N) == 8
count if test_family == "H3_target_absolute_error"
assert r(N) == 8
count if test_family == "H4_primary_unconditional_coverage"
assert r(N) == 36
count if test_family == "H4_primary_vs_gaussian_interval_score"
assert r(N) == 36
count if test_family == "H4_primary_vs_rolling_interval_score"
assert r(N) == 31

preserve
contract test_family
list test_family _freq, noobs abbreviate(40)
restore

display "============================================================"
display "ROBUSTNESS R1-R5 STATA AUDIT COMPLETED SUCCESSFULLY"
display "============================================================"
