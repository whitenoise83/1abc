*******************************************************
* MacroPulse Scientific Paper
* Motivation Descriptives
*
* File:
* stata/02_motivation_descriptives.do
*
* Purpose:
*   1. Describe the paper's macroeconomic targets
*   2. Illustrate economically meaningful GDP revisions
*      across historical ALFRED vintages
*******************************************************

version 19
clear all
set more off


* =====================================================
* 0. GENERAL INFORMATION
* =====================================================

display "===================================================="
display "MACROPULSE PAPER: MOTIVATION DESCRIPTIVES"
display "===================================================="

about

display "Run date: " c(current_date)
display "Run time: " c(current_time)


* =====================================================
* PART A
* CURRENT-VINTAGE TARGET DESCRIPTIVES
* =====================================================


* =====================================================
* 1. REAL GDP GROWTH
* =====================================================

display ""
display "===================================================="
display "1. REAL GDP GROWTH"
display "===================================================="

import fred GDPC1, clear

generate qdate = qofd(daten)
format qdate %tq
tsset qdate, quarterly

* Annualized quarter-on-quarter log growth
generate gdp_growth = 400 * (ln(GDPC1) - ln(L.GDPC1))

label variable gdp_growth ///
    "Real GDP growth, annualized QoQ log difference"

display ""
display "GDP growth: full available sample"
summarize gdp_growth, detail

display ""
display "GDP growth: 2015Q1 onward"
summarize gdp_growth if qdate >= yq(2015,1), detail

display ""
display "Recent GDP growth observations"
list qdate GDPC1 gdp_growth if ///
    qdate >= yq(2019,1), ///
    noobs


* =====================================================
* 2. MONTHLY INFLATION AND LABOUR TARGETS
* =====================================================

clear

display ""
display "===================================================="
display "2. MONTHLY INFLATION AND LABOUR TARGETS"
display "===================================================="

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


* -----------------------------------------------------
* Inflation targets:
* annualized month-on-month log growth
* -----------------------------------------------------

generate pi_cpi = ///
    1200 * (ln(CPIAUCSL) - ln(L.CPIAUCSL))

generate pi_corecpi = ///
    1200 * (ln(CPILFESL) - ln(L.CPILFESL))

generate pi_pce = ///
    1200 * (ln(PCEPI) - ln(L.PCEPI))

generate pi_corepce = ///
    1200 * (ln(PCEPILFE) - ln(L.PCEPILFE))


* -----------------------------------------------------
* Labour targets
* -----------------------------------------------------

* Monthly change in nonfarm payroll employment
generate d_payems = PAYEMS - L.PAYEMS

* Unemployment rate remains in levels
generate unemployment = UNRATE

* Average hourly earnings:
* annualized month-on-month log growth
generate ahe_growth = ///
    1200 * (ln(CES0500000003) - ln(L.CES0500000003))


label variable pi_cpi ///
    "Headline CPI inflation, annualized MoM"

label variable pi_corecpi ///
    "Core CPI inflation, annualized MoM"

label variable pi_pce ///
    "Headline PCE inflation, annualized MoM"

label variable pi_corepce ///
    "Core PCE inflation, annualized MoM"

label variable d_payems ///
    "Monthly change in nonfarm payrolls"

label variable unemployment ///
    "Unemployment rate"

label variable ahe_growth ///
    "Average hourly earnings growth, annualized MoM"


* -----------------------------------------------------
* Descriptive statistics: 2015 onward
* -----------------------------------------------------

display ""
display "Monthly target descriptives: January 2015 onward"

summarize ///
    pi_cpi ///
    pi_corecpi ///
    pi_pce ///
    pi_corepce ///
    d_payems ///
    unemployment ///
    ahe_growth ///
    if mdate >= ym(2015,1), ///
    detail


display ""
display "Pre-COVID target descriptives: 2015m1--2019m12"

summarize ///
    pi_cpi ///
    pi_corecpi ///
    pi_pce ///
    pi_corepce ///
    d_payems ///
    unemployment ///
    ahe_growth ///
    if inrange(mdate,ym(2015,1),ym(2019,12))


display ""
display "COVID/post-COVID target descriptives: 2020m1 onward"

summarize ///
    pi_cpi ///
    pi_corecpi ///
    pi_pce ///
    pi_corepce ///
    d_payems ///
    unemployment ///
    ahe_growth ///
    if mdate >= ym(2020,1)


* =====================================================
* PART B
* GDP VINTAGE COMPARISON
* =====================================================

clear

display ""
display "===================================================="
display "3. GDP VINTAGE COMPARISON"
display "===================================================="

import fred GDPC1, ///
    vintage(2019-01-15 2020-01-15 2021-01-15) ///
    clear

generate qdate = qofd(daten)
format qdate %tq
tsset qdate, quarterly


* -----------------------------------------------------
* Record metadata before making comparisons
* -----------------------------------------------------

display ""
display "Vintage metadata"

char list GDPC1_20190115[Last_Updated]
char list GDPC1_20190115[Units]

char list GDPC1_20200115[Last_Updated]
char list GDPC1_20200115[Units]

char list GDPC1_20210115[Last_Updated]
char list GDPC1_20210115[Units]


* -----------------------------------------------------
* Compute growth independently within each vintage
* -----------------------------------------------------

generate gdpgr_2019v = ///
    400 * (ln(GDPC1_20190115) - ln(L.GDPC1_20190115))

generate gdpgr_2020v = ///
    400 * (ln(GDPC1_20200115) - ln(L.GDPC1_20200115))

generate gdpgr_2021v = ///
    400 * (ln(GDPC1_20210115) - ln(L.GDPC1_20210115))


* -----------------------------------------------------
* Compare overlapping observations only
* -----------------------------------------------------

display ""
display "GDP growth as measured in different vintages"

list ///
    qdate ///
    gdpgr_2019v ///
    gdpgr_2020v ///
    gdpgr_2021v ///
    if inrange(qdate,yq(2017,1),yq(2018,3)), ///
    noobs


* -----------------------------------------------------
* Revision differences
* -----------------------------------------------------

generate rev_2020_vs_2019 = ///
    gdpgr_2020v - gdpgr_2019v

generate rev_2021_vs_2020 = ///
    gdpgr_2021v - gdpgr_2020v

generate absrev_2020_vs_2019 = ///
    abs(rev_2020_vs_2019)

generate absrev_2021_vs_2020 = ///
    abs(rev_2021_vs_2020)


display ""
display "Revision statistics: 2020 vintage minus 2019 vintage"

summarize ///
    rev_2020_vs_2019 ///
    absrev_2020_vs_2019 ///
    if !missing(rev_2020_vs_2019)


display ""
display "Revision statistics: 2021 vintage minus 2020 vintage"

summarize ///
    rev_2021_vs_2020 ///
    absrev_2021_vs_2020 ///
    if !missing(rev_2021_vs_2020)


* =====================================================
* 4. SAVE RESEARCH DATA
* =====================================================

save "data/derived/gdp_vintage_motivation.dta", replace

export delimited ///
    qdate ///
    gdpgr_2019v ///
    gdpgr_2020v ///
    gdpgr_2021v ///
    rev_2020_vs_2019 ///
    rev_2021_vs_2020 ///
    using "outputs/tables/gdp_vintage_motivation.csv", ///
    replace


* =====================================================
* 5. FINISH
* =====================================================

display ""
display "===================================================="
display "02_motivation_descriptives.do COMPLETED SUCCESSFULLY"
display "===================================================="

exit