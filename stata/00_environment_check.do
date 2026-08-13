*******************************************************
* MacroPulse Scientific Paper
* Environment Check
* File: 00_environment_check.do
*******************************************************

version 19
clear all
set more off

display "===================================================="
display "MacroPulse Stata Environment Check"
display "===================================================="

display "Current working directory:"
pwd

display "Stata version and edition:"
about

display "Update status:"
update query

display "System directories:"
sysdir

display "Current date:"
display c(current_date)

display "Current time:"
display c(current_time)

display "Stata flavor:"
display c(flavor)

display "Stata version:"
display c(stata_version)

display "Operating system:"
display c(os)

display "Machine type:"
display c(machine_type)

display "===================================================="
display "Basic functionality test"
display "===================================================="

sysuse auto, clear

summarize price mpg weight

regress price mpg weight

display "===================================================="
display "Environment check completed successfully."
display "===================================================="

exit