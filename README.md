## Working Paper

**Real-Time Macroeconomic Nowcasting with Stage-Dependent Model Policies:
Evidence from U.S. GDP, Inflation, and Labour Markets**

Cenk Ufuk Yildiran, 2026

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22042549.svg)](https://doi.org/10.5281/zenodo.22042549)

**DOI:** https://doi.org/10.5281/zenodo.22042549

**Frozen manuscript release:** `manuscript-v1.0`

**Canonical manuscript commit:**  
`8905ea96193624501032074032a6af278d26575a`

# Real-Time Macroeconomic Nowcasting with Stage-Dependent Model Policies

This repository contains the manuscript, frozen research-design artifacts,
confirmatory outputs, robustness analyses, audit logs, and reproducibility
materials for:

**Real-Time Macroeconomic Nowcasting with Stage-Dependent Model Policies:
Evidence from U.S. GDP, Inflation, and Labour Markets**

The paper evaluates a vintage-aware, stage-dependent pseudo-real-time
forecasting framework for U.S. real GDP growth, four inflation measures,
payroll employment, unemployment, and average hourly earnings.

## Research design

The empirical study is organised around four frozen confirmatory hypotheses:

- **H1 — Information arrival:** holding the forecasting model fixed, assess
  whether adjacent release stages change forecast loss.
- **H2 — Stage-dependent policy:** compare a development-frozen
  target-by-stage model policy with a development-frozen target-level fixed
  comparator.
- **H3 — Data vintages:** compare historically available and frozen
  latest-vintage inputs while preserving the historical observation mask and
  the common initial-release evaluation outcome.
- **H4 — Predictive uncertainty:** evaluate prior-only 80% prediction
  intervals for calibration, violation independence, sharpness, and interval
  score.

H1--H4 were frozen and archived before the separate R1--R5 robustness and
sensitivity programme. The robustness analyses do not redefine the
confirmatory estimands.

## Reproducibility structure

- `main.tex` — master manuscript
- `sections/` — main paper
- `appendix/` — technical and reproducibility appendices
- `references.bib` — bibliography
- `freeze/` — pre-analysis and design-freeze artifacts
- `outputs/confirmatory/` — immutable H1--H4 result archives and manifests
- `outputs/robustness/` — immutable R1--R5 robustness archive and provenance
- `python/` — analysis and audit-support scripts
- `stata/` — independent Stata audit programs
- `logs/` — retained execution/audit logs
- `data/` — governed paper-side data artifacts and metadata

The production MacroPulse source is pinned in the archived manifests. Full
commit identifiers, source backtest identifiers, analysis-script hashes, row
counts, and SHA-256 result hashes are preserved in the confirmatory and
robustness provenance files.

## Compile

From the project root:

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

The modular source tree is suitable for local TeX/Overleaf work. A target
journal may require a flattened source package at final submission.

## Analysis boundary

The confirmatory and robustness archives are treated as immutable. Manuscript
editing after those freezes changes presentation and interpretation only; it
does not regenerate the archived empirical results.
