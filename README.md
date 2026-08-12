# Elsevier real-time macro nowcasting working-paper template

This is a modular LaTeX working-paper skeleton tailored to the MacroPulse-style research design:

- real-time / vintage-aware information sets;
- stage-dependent model policies;
- GDP, inflation, and labour-market applications;
- pseudo-real-time evaluation;
- prior-only 80% predictive-interval calibration;
- robustness and reproducibility appendices.

## Confirmatory research structure

The manuscript is now organised around four pre-specified hypotheses:

- **H1 - Information arrival:** holding the forecasting model fixed, later real-time information stages should reduce forecast loss.
- **H2 - Stage-dependent policy:** a pre-specified target-by-stage model policy should outperform a single fixed model selected on a development sample. This is the headline hypothesis.
- **H3 - Data vintage validity:** forecast evaluation and/or model rankings may differ when genuine historical vintages are replaced by latest-vintage data.
- **H4 - Predictive uncertainty:** prior-only 80% empirical prediction intervals should be evaluated jointly for calibration, independence of violations, sharpness, and interval score.

The template deliberately separates H1 from H2 so that the value of incoming information is not confounded with the value of changing models. It also requires policy selection to occur before the final H2 evaluation sample.

## Compile

From the project root:

```bash
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

It is also suitable for upload to Overleaf as a project.

## Working structure

- `main.tex` - front matter and master document
- `sections/` - main paper
- `appendix/` - technical appendices
- `references.bib` - bibliography
- `figures/` - working figures
- `tables/` - optional generated table fragments

## Elsevier submission note

The modular folder structure is convenient while writing. Before source-file submission through Elsevier Editorial Manager, create a flattened submission package if required by the journal/workflow, because Editorial Manager does not process LaTeX subfolder structures.
