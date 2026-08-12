*******************************************************
* MacroPulse Scientific Paper
* Motivation Data Validation
* File: stata/03_motivation_validation.do
*******************************************************

version 19
clear all
set more off


* =====================================================
* MONTHLY DATA COMPLETENESS CHECK
* =====================================================

import fred ///
    CPIAUCSL ///
    CPILFESL ///
    PCEPI ///
    PCEPILFE ///
    PAYEMS ///
    UNRATE ///
    CES0500000003, ///
    clear

generate mdate = mofd(daten)
format mdate %tm
tsset mdate, monthly


display "=============================================="
display "OBSERVATION COVERAGE: 2015 ONWARD"
display "=============================================="

foreach v in CPIAUCSL CPILFESL PCEPI PCEPILFE ///
             PAYEMS UNRATE CES0500000003 {

    display ""
    display "Series: `v'"

    count if mdate >= ym(2015,1) & !missing(`v')

    summarize mdate if ///
        mdate >= ym(2015,1) & ///
        !missing(`v')

    display "First available month:"
    display %tm r(min)

    display "Last available month:"
    display %tm r(max)
}


* =====================================================
* IDENTIFY INTERNAL MISSING VALUES
* =====================================================

display ""
display "=============================================="
display "INTERNAL MISSING MONTHS: 2015 ONWARD"
display "=============================================="

foreach v in CPIAUCSL CPILFESL PCEPI PCEPILFE ///
             PAYEMS UNRATE CES0500000003 {

    display ""
    display "Missing observations for `v':"

    list mdate if ///
        mdate >= ym(2015,1) & ///
        mdate <= ym(2026,7) & ///
        missing(`v'), ///
        noobs
}


* =====================================================
* GDP VINTAGE REVISION CHECK: RECENT OVERLAP
* =====================================================

clear

import fred GDPC1, ///
    vintage(2019-01-15 2020-01-15 2021-01-15) ///
    clear

generate qdate = qofd(daten)
format qdate %tq
tsset qdate, quarterly

generate g19 = ///
    400*(ln(GDPC1_20190115)-ln(L.GDPC1_20190115))

generate g20 = ///
    400*(ln(GDPC1_20200115)-ln(L.GDPC1_20200115))

generate g21 = ///
    400*(ln(GDPC1_20210115)-ln(L.GDPC1_20210115))

generate rev20_19 = g20-g19
generate rev21_20 = g21-g20

generate absrev20_19 = abs(rev20_19)
generate absrev21_20 = abs(rev21_20)


display ""
display "=============================================="
display "RECENT GDP REVISION DISTRIBUTION"
display "=============================================="

summarize rev20_19 absrev20_19 ///
    if inrange(qdate,yq(2010,1),yq(2018,3)), detail

summarize rev21_20 absrev21_20 ///
    if inrange(qdate,yq(2010,1),yq(2019,3)), detail


display ""
display "Largest 2019-to-2020 vintage revisions"

gsort -absrev20_19

list qdate g19 g20 rev20_19 absrev20_19 ///
    if !missing(absrev20_19) in 1/10, noobs


display ""
display "03_motivation_validation.do COMPLETED SUCCESSFULLY"

exit