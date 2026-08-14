/***********************************************************************
* MacroPulse Scientific Paper
* Vintage Input Invariance Audit
*
* File:
*   stata/06_vintage_input_invariance_audit.do
*
* Purpose:
*   Independently verify the Python RT/LV vintage construction and
*   production-input invariance results.
***********************************************************************/

version 19
clear all
set more off

display as text "============================================================"
display as text "06_vintage_input_invariance_audit.do"
display as text "RT/LV vintage mask and model-input invariance audit"
display as text "============================================================"


/***********************************************************************
* 1. RAW MASK AUDIT
***********************************************************************/

display as text ""
display as text "=== RAW MASK AUDIT ==="

import delimited ///
    "outputs/tables/vintage_raw_mask_audit.csv", ///
    clear varnames(1)

assert _N == 3
isid domain

assert final_missing_values == 0
assert rows == comparable_rows + fallback_rows

assert fallback_rows == 0 ///
    if domain == "GDP"

assert fallback_rows == 12 ///
    if domain == "Inflation"

assert fallback_rows == 0 ///
    if domain == "Labour"

assert fallback_unique_keys == 0 ///
    if domain == "GDP"

assert fallback_unique_keys == 5 ///
    if domain == "Inflation"

assert fallback_unique_keys == 0 ///
    if domain == "Labour"

list, noobs abbreviate(24)


/***********************************************************************
* 2. FALLBACK MANIFEST
***********************************************************************/

display as text ""
display as text "=== FALLBACK MANIFEST ==="

import delimited ///
    "outputs/tables/vintage_fallback_manifest.csv", ///
    clear varnames(1) stringcols(_all)

assert _N == 5
assert domain == "Inflation"
assert series_id == "DCOILWTICO"

isid domain series_id observation_date

assert inlist( ///
    observation_date, ///
    "2019-11-11", ///
    "2019-12-25", ///
    "2020-01-01", ///
    "2022-12-26", ///
    "2024-11-11" ///
)

destring snapshot_rows min_rt_value max_rt_value, replace

assert min_rt_value == max_rt_value

summarize snapshot_rows
assert r(sum) == 12

list, noobs abbreviate(24)


/***********************************************************************
* 3. MODEL-INPUT INVARIANCE
***********************************************************************/

display as text ""
display as text "=== MODEL-INPUT INVARIANCE ==="

import delimited ///
    "outputs/tables/vintage_input_invariance_summary.csv", ///
    clear varnames(1)

assert _N == 4
isid domain builder

* Expected production-origin counts.
assert origins == 225 ///
    if domain == "GDP" & builder == "Bridge"

assert origins == 225 ///
    if domain == "GDP" & builder == "DFM"

assert origins == 1202 ///
    if domain == "Inflation"

assert origins == 1739 ///
    if domain == "Labour"

* Both vintage arms must build successfully at every RT-valid origin.
assert rt_success == origins
assert lv_success == origins
assert paired_success == origins

* Econometric structure must be unchanged.
assert structure_pass == origins
assert imputation_pass == origins
assert latest_period_pass == origins

* H3 requires actual numerical vintage variation.
assert numeric_change_origins == origins

* Raw fallback occurs only in inflation.
assert raw_fallback_rows == 0 ///
    if domain == "GDP"

assert raw_fallback_rows == 42 ///
    if domain == "Inflation"

assert raw_fallback_rows == 0 ///
    if domain == "Labour"

list, noobs abbreviate(28)


/***********************************************************************
* 4. ORIGIN-LEVEL HARD GATES
***********************************************************************/

display as text ""
display as text "=== ORIGIN-LEVEL HARD GATES ==="

import delimited ///
    "outputs/tables/vintage_input_invariance_audit.csv", ///
    clear varnames(1) stringcols(_all)

destring ///
    structure_equal ///
    imputation_equal ///
    latest_period_equal ///
    paired_success ///
    numeric_change_detected ///
    raw_fallback_rows ///
    raw_changed_rows, ///
    replace

count
display as result "Total model-input audits: " r(N)

* 225 Bridge + 225 DFM + 1202 inflation + 1739 labour.
assert _N == 3391

assert rt_status == "ok"
assert lv_status == "ok"

assert paired_success == 1
assert structure_equal == 1
assert imputation_equal == 1
assert latest_period_equal == 1

* Every historical origin must contain some RT/LV numerical variation.
assert numeric_change_detected == 1

count if raw_fallback_rows > 0
display as result ///
    "Target-specific origins using WTI fallback: " r(N)

count if domain != "Inflation" & raw_fallback_rows > 0
assert r(N) == 0


/***********************************************************************
* 5. SCIENTIFIC DESIGN SUMMARY
***********************************************************************/

display as text ""
display as text "============================================================"
display as result "VINTAGE INPUT INVARIANCE AUDIT COMPLETED SUCCESSFULLY"
display as text ""
display as text "H3 frozen design:"
display as text "  1. RT and LV use identical historical availability masks."
display as text "  2. Latest values replace only historically admissible cells."
display as text "  3. Five unavailable latest WTI keys retain their RT values."
display as text "  4. Production dataset structure is invariant across vintages."
display as text "  5. Every evaluated origin contains numerical vintage variation."
display as text "  6. Evaluation outcomes remain initial-release realizations."
display as text ""
display as text "Frozen latest-vintage extract SHA256:"
display as text "1f418a21ed774796da4e4426f3270340d296ecca571b205c98b24d81be1346af"
display as text "============================================================"