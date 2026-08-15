# Confirmatory H4 provenance record

## Purpose

This record documents the confirmatory H4 interval-evaluation run, subsequent audit-only corrections, accidental local artifact truncations, deterministic restoration, and the final successful independent Stata audit.

## Pre-result boundary

- Pre-H4 checkpoint: `54f70fdd6d2d673731e619a371227fc2e0d10864`
- H4 pre-analysis commit: `a1a706f792580730d29021bd9c48b776d2246f09`
- Frozen research-policy commit: `420feaeb51dca3abc79e9426aacca3816fe6ad5a`
- Pinned MacroPulse source: `c4f357e463354f72eabead3dbc7f3b14ae71bec5`
- H4 design SHA-256: `13bf3b75e65c0a9ec0b9362d57005f170e3b1d896de8c051b948cdef8e23485c`
- Confirmatory Python SHA-256: `f44ba7a9e31e4b7622ebb1f71868aa521f63e924c4d25f398b01645b22eaa412`

The first confirmatory Python evaluation reported `PRE-ANALYSIS BOUNDARY VERIFICATION: PASS` before producing results.

## Original confirmatory result hashes

These are the hashes recorded from the first successful H4 evaluation and subsequently reproduced/restored byte-for-byte:

- `h4_interval_detail.csv`  
  `38c747a6d575a20c1806ed076dab2da33f5a5f85dcf98f78551332519f91c68a`
- `h4_interval_summary.csv`  
  `48fd2b7bbf2d69e7916c6a13809b4e70cc24762656e3e6a678bc6b8a7e820d36`
- `h4_interval_eligibility_audit.csv`  
  `f1f71a19af27196e56dc9c3bf495a13ed1eecf1a4a0a53658d57e7ae0640dbb5`
- `h4_interval_method_comparisons.csv`  
  `fee3f933c94430f4d809da495cfab53046f585db09425628daf5424699d9b156`
- `confirmatory_h4_manifest.json`  
  `e8a6517e00c7e87630f8c336223658dbee858b1ee6edac27960964b4a17b1bfa`

## Post-result audit-only corrections

No H4 analytical method, forecast, interval, score, sample, benchmark, calibration rule, or result file was intentionally changed after results were observed.

Three audit-only code corrections were committed separately:

1. `0f4fd2bd4ffa5fa0d7f0cbc5e5d5cb9e6d0df089`  
   `Fix Stata H4 nominal-coverage precision audit`  
   Replaced exact comparison of the imported constant 0.8 with a numerical tolerance.

2. `9a8d18427d3c5191cea473893d7034d571d85a04`  
   `Use double precision in Stata H4 CSV audit`  
   Added `asdouble` to the five `import delimited` calls after a diagnostic showed that default Stata float storage generated artificial Winkler-score discrepancies.

3. `d5322fe2a065305c8261c3a9d68d0a3d0e29a3ec`  
   `Reproduce H4 coverage rates from exact counts`  
   Reconstructed coverage and tail-miss rates from integer counts divided by `n`, avoiding float storage introduced by `collapse (mean)`. A diagnostic showed zero disagreement between the Python-reported coverage and the exact count ratio at a 1e-12 threshold.

## Accidental local artifact truncations and recovery

Two uncommitted local H4 CSV artifacts were accidentally truncated to zero bytes during the audit workflow:

- `h4_interval_detail.csv`
- `h4_interval_summary.csv`

Neither truncation was committed.

The detail file was deterministically regenerated from the frozen confirmatory Python implementation and accepted only after its SHA-256 exactly reproduced the original first-run hash.

The summary file was restored from a pre-existing backup made before the truncation and accepted only after its SHA-256 exactly reproduced the original first-run hash.

After recovery, all five original H4 output hashes matched the first-run hashes listed above.

## Audit-log chronology

The audit workflow retained the following failed logs for transparency:

- `10_confirmatory_h4_intervals_audit_failed_precision.log`
- `10_confirmatory_h4_intervals_audit_failed_empty_detail.log`
- `10_confirmatory_h4_intervals_audit_failed_score_reproduction.log`
- `10_confirmatory_h4_intervals_audit_failed_summary_precision.log`
- `10_confirmatory_h4_intervals_audit_failed_empty_summary.log`

The final successful audit is:

- `10_confirmatory_h4_intervals_audit.log`
- SHA-256: `303ea7db29bb20b05270150860a169600f01bd7222d32697ade9f808ab0fa46c`

The final Stata run printed:

`CONFIRMATORY H4 AUDIT COMPLETED SUCCESSFULLY`

A machine-readable scan for Stata return codes, failed assertions, syntax errors, missing-file errors, and modification errors returned no matches.

## Interpretation of provenance

The post-result changes were restricted to the independent Stata audit layer. The confirmatory H4 analytical outputs archived with this record are byte-identical to the originally observed result artifacts, as demonstrated by the SHA-256 hashes above.
