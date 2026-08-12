*******************************************************
* MacroPulse Scientific Paper
* FRED / ALFRED Connectivity Test
* File: stata/01_fred_connectivity.do
*******************************************************

version 19
clear all
set more off


* =====================================================
* 1. CURRENT-VINTAGE FRED TEST
* =====================================================

display "=============================================="
display "1. CURRENT-VINTAGE GDPC1"
display "=============================================="

import fred GDPC1, clear

describe GDPC1
summarize GDPC1

generate qdate = qofd(daten)
format qdate %tq
tsset qdate, quarterly

list qdate GDPC1 in -8/l, noobs

display "Current-vintage metadata:"
char list GDPC1[Title]
char list GDPC1[Source]
char list GDPC1[Frequency]
char list GDPC1[Units]
char list GDPC1[Last_Updated]


* =====================================================
* 2. ALFRED HISTORICAL-VINTAGE TEST
* =====================================================

clear

display ""
display "=============================================="
display "2. HISTORICAL GDPC1 VINTAGES"
display "=============================================="

import fred GDPC1, ///
    vintage(2019-01-15 2020-01-15 2021-01-15) ///
    clear

describe

generate qdate = qofd(daten)
format qdate %tq
tsset qdate, quarterly

ds GDPC1*
local vintagevars `r(varlist)'

display ""
display "Imported vintage variables:"
display "`vintagevars'"

display ""
describe GDPC1*

display ""
display "GDP values across vintages:"
list qdate `vintagevars' if ///
    qdate >= yq(2018,1) & ///
    qdate <= yq(2020,4), ///
    noobs


* =====================================================
* 3. FINISH
* =====================================================

display ""
display "=============================================="
display "FRED / ALFRED TEST COMPLETED SUCCESSFULLY"
display "=============================================="

exit