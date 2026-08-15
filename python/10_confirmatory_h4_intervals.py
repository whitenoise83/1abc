from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
from pathlib import Path
from statistics import NormalDist

import duckdb
import numpy as np
import pandas as pd


PRE_H4_CHECKPOINT = "54f70fdd6d2d673731e619a371227fc2e0d10864"
POLICY_FREEZE_COMMIT = "420feaeb51dca3abc79e9426aacca3816fe6ad5a"
MACROPULSE_SOURCE_COMMIT = "c4f357e463354f72eabead3dbc7f3b14ae71bec5"
DESIGN_SHA256 = "13bf3b75e65c0a9ec0b9362d57005f170e3b1d896de8c051b948cdef8e23485c"

GDP_BACKTEST = "382b4c6b-ef76-4ca1-b52f-d5e3e1ac66b1"
INFLATION_BACKTEST = "fdd2f573-a425-4abc-8056-f9843955bac2"
LABOUR_BACKTEST = "834e0655-ba81-4b96-b42c-e1cdda73b847"

EVALUATION_START = {
    "GDP": "2023Q2",
    "Inflation": "2023-02",
    "Labour": "2023-02",
}

NOMINAL_COVERAGE = 0.80
ALPHA = 1.0 - NOMINAL_COVERAGE
Z_CENTRAL_80 = NormalDist().inv_cdf((1.0 + NOMINAL_COVERAGE) / 2.0)

METHODS = {
    "GDP": {
        "primary": "rolling_q80",
        "benchmarks": ["gaussian_rmse"],
        "window": 20,
        "minimum": 12,
    },
    "Inflation": {
        "primary": "exp_weighted_q80",
        "benchmarks": ["rolling_q80", "gaussian_rmse"],
        "window": 48,
        "minimum": 24,
        "half_life": 18.0,
    },
    "Labour": {
        "primary": "exp_weighted_q80",
        "benchmarks": ["rolling_q80", "gaussian_rmse"],
        "window": 48,
        "minimum": 24,
        "decay": 0.94,
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def git_show_bytes(repo: Path, commit: str, relpath: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{commit}:{relpath}"],
        stderr=subprocess.STDOUT,
    )


def require_commit(repo: Path, commit: str, label: str) -> None:
    try:
        subprocess.check_call(
            ["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{label} commit is not available locally: {commit}") from exc


def require_ancestor(repo: Path, ancestor: str, descendant: str, label: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{label} {ancestor} is not an ancestor of {descendant}.")


def verify_preanalysis_boundaries(
    paper_root: Path,
    macro_root: Path,
) -> tuple[str, str, str, str]:
    head = git_output(paper_root, "rev-parse", "HEAD")
    require_commit(paper_root, PRE_H4_CHECKPOINT, "Pre-H4 checkpoint")
    require_commit(paper_root, POLICY_FREEZE_COMMIT, "Policy freeze")
    require_ancestor(paper_root, PRE_H4_CHECKPOINT, head, "Pre-H4 checkpoint")
    require_ancestor(paper_root, POLICY_FREEZE_COMMIT, head, "Policy freeze")

    require_commit(macro_root, MACROPULSE_SOURCE_COMMIT, "Pinned MacroPulse source")

    design_rel = "freeze/h4_interval_design_freeze.json"
    design_path = paper_root / design_rel
    if not design_path.is_file():
        raise FileNotFoundError(design_path)
    if sha256_file(design_path) != DESIGN_SHA256:
        raise RuntimeError(
            f"H4 design freeze hash mismatch. Expected {DESIGN_SHA256}, "
            f"got {sha256_file(design_path)}."
        )
    try:
        committed_design = git_show_bytes(paper_root, head, design_rel)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "H4 design freeze is not committed at HEAD. Commit the exact H4 "
            "preanalysis package before running evaluation."
        ) from exc
    if committed_design != design_path.read_bytes():
        raise RuntimeError("Working H4 design freeze differs from the HEAD version.")

    script_rel = "python/10_confirmatory_h4_intervals.py"
    audit_rel = "stata/10_confirmatory_h4_intervals_audit.do"
    script_path = paper_root / script_rel
    audit_path = paper_root / audit_rel
    for relpath, path, label in [
        (script_rel, script_path, "Python H4 analysis"),
        (audit_rel, audit_path, "Stata H4 audit"),
    ]:
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            committed = git_show_bytes(paper_root, head, relpath)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"{label} is not committed at HEAD. Commit the exact H4 "
                "preanalysis package before opening evaluation results."
            ) from exc
        if committed != path.read_bytes():
            raise RuntimeError(f"Working {label} differs from the HEAD version.")

    return head, sha256_file(script_path), sha256_file(audit_path), sha256_file(design_path)


def period_order(domain: str, value: str) -> int:
    if domain == "GDP":
        return int(pd.Period(str(value), freq="Q").ordinal)
    return int(pd.Period(str(value), freq="M").ordinal)


def load_stage_policy(paper_root: Path) -> pd.DataFrame:
    path = paper_root / "freeze" / "research_stage_policy_freeze.csv"
    frame = pd.read_csv(path)
    required = {
        "domain_name",
        "target_series",
        "stage_order",
        "forecast_stage",
        "selected_model",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise RuntimeError(f"Frozen stage policy is missing columns: {missing}")
    if len(frame) != 36:
        raise RuntimeError(f"Expected 36 frozen stage-policy rows, got {len(frame)}.")
    if frame.duplicated(
        ["domain_name", "target_series", "forecast_stage"], keep=False
    ).any():
        raise RuntimeError("Frozen stage policy contains duplicate target-stage rows.")
    return frame[
        ["domain_name", "target_series", "stage_order", "forecast_stage", "selected_model"]
    ].copy()


def load_backtest_rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    gdp = con.execute(
        """
        SELECT 'GDP' AS domain_name, 'GDPC1' AS target_series,
               target_period, forecast_stage, forecast_date,
               actual_release_date, model_name, point_forecast, actual
        FROM stage_backtest_results
        WHERE stage_backtest_id = ?
        ORDER BY target_period, forecast_stage, model_name
        """,
        [GDP_BACKTEST],
    ).fetchdf()

    inflation = con.execute(
        """
        SELECT 'Inflation' AS domain_name, target_series,
               target_period, forecast_stage, forecast_date,
               actual_release_date, model_name, point_forecast, actual
        FROM inflation_vintage_backtest_results
        WHERE backtest_id = ?
        ORDER BY target_series, target_period, forecast_stage, model_name
        """,
        [INFLATION_BACKTEST],
    ).fetchdf()

    labour = con.execute(
        """
        SELECT 'Labour' AS domain_name, target_series,
               target_period, forecast_stage, forecast_date,
               actual_release_date, model_name, point_forecast, actual
        FROM labour_vintage_backtest_results
        WHERE backtest_id = ?
        ORDER BY target_series, target_period, forecast_stage, model_name
        """,
        [LABOUR_BACKTEST],
    ).fetchdf()

    frame = pd.concat([gdp, inflation, labour], ignore_index=True, sort=False)
    if frame.empty:
        raise RuntimeError("No source backtest rows were loaded.")
    frame["target_period"] = frame["target_period"].astype(str)
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"], errors="coerce")
    frame["actual_release_date"] = pd.to_datetime(
        frame["actual_release_date"], errors="coerce"
    )
    frame["point_forecast"] = pd.to_numeric(frame["point_forecast"], errors="coerce")
    frame["actual"] = pd.to_numeric(frame["actual"], errors="coerce")
    frame["error"] = frame["actual"] - frame["point_forecast"]
    frame["abs_error"] = frame["error"].abs()
    frame["_period_order"] = [
        period_order(domain, value)
        for domain, value in zip(frame["domain_name"], frame["target_period"])
    ]
    return frame


def select_frozen_policy_rows(
    source: pd.DataFrame,
    stage_policy: pd.DataFrame,
) -> pd.DataFrame:
    policy = stage_policy.rename(columns={"selected_model": "frozen_selected_model"})
    selected = source.merge(
        policy,
        on=["domain_name", "target_series", "forecast_stage"],
        how="inner",
        validate="many_to_one",
    )
    selected = selected.loc[
        selected["model_name"].astype(str)
        == selected["frozen_selected_model"].astype(str)
    ].copy()
    selected["selected_model"] = selected["frozen_selected_model"].astype(str)
    selected = selected.drop(columns=["frozen_selected_model"])

    key = ["domain_name", "target_series", "target_period", "forecast_stage"]
    dup = selected.duplicated(key, keep=False)
    if dup.any():
        raise RuntimeError(
            "Frozen policy selection produced duplicate forecast cells:\n"
            + selected.loc[dup, key + ["selected_model"]].head(20).to_string(index=False)
        )
    if selected.empty:
        raise RuntimeError("Frozen research policy produced no source rows.")
    return selected.sort_values(
        ["domain_name", "target_series", "_period_order", "stage_order"]
    ).reset_index(drop=True)


def evaluation_rows(selected: pd.DataFrame) -> pd.DataFrame:
    keep = np.asarray(
        [
            int(order) >= period_order(str(domain), EVALUATION_START[str(domain)])
            for domain, order in zip(selected["domain_name"], selected["_period_order"])
        ],
        dtype=bool,
    )
    frame = selected.loc[keep].copy()
    if frame.empty:
        raise RuntimeError("No H4 evaluation rows were selected.")
    required_valid = (
        frame["forecast_date"].notna()
        & frame["actual_release_date"].notna()
        & np.isfinite(frame["point_forecast"])
        & np.isfinite(frame["actual"])
    )
    if not bool(required_valid.all()):
        bad = frame.loc[
            ~required_valid,
            [
                "domain_name",
                "target_series",
                "target_period",
                "forecast_stage",
                "selected_model",
                "forecast_date",
                "actual_release_date",
                "point_forecast",
                "actual",
            ],
        ]
        raise RuntimeError(
            "Evaluation rows contain missing/nonfinite required values:\n"
            + bad.head(20).to_string(index=False)
        )
    return frame


def higher_quantile(values: np.ndarray, probability: float) -> float:
    if values.size == 0:
        raise ValueError("At least one value is required.")
    try:
        return float(np.quantile(values, probability, method="higher"))
    except TypeError:
        return float(np.quantile(values, probability, interpolation="higher"))


def weighted_quantile(
    values: np.ndarray,
    weights: np.ndarray,
    probability: float,
) -> float:
    if values.size == 0 or weights.size != values.size:
        raise ValueError("Weighted quantile requires equal-length nonempty arrays.")
    order = np.argsort(values, kind="stable")
    v = values[order]
    w = weights[order]
    if not bool(np.all(np.isfinite(v))) or not bool(np.all(np.isfinite(w))):
        raise ValueError("Weighted quantile received nonfinite values.")
    if not bool(np.all(w > 0)):
        raise ValueError("Weighted quantile weights must be positive.")
    cumulative = np.cumsum(w)
    cutoff = float(probability) * float(cumulative[-1])
    index = int(np.searchsorted(cumulative, cutoff, side="left"))
    return float(v[min(index, len(v) - 1)])


def interval_score(actual: float, lower: float, upper: float) -> float:
    score = float(upper - lower)
    if actual < lower:
        score += (2.0 / ALPHA) * float(lower - actual)
    elif actual > upper:
        score += (2.0 / ALPHA) * float(actual - upper)
    return float(score)


def method_width(domain: str, method: str, window: pd.DataFrame) -> float:
    errors = window["error"].to_numpy(dtype=float)
    absolute = np.abs(errors)

    if method == "rolling_q80":
        return max(0.0, higher_quantile(absolute, NOMINAL_COVERAGE))

    if method == "gaussian_rmse":
        rmse = float(np.sqrt(np.mean(np.square(errors))))
        return max(0.0, Z_CENTRAL_80 * rmse)

    if method == "exp_weighted_q80":
        ages = np.arange(len(absolute) - 1, -1, -1, dtype=float)
        if domain == "Inflation":
            weights = np.power(0.5, ages / float(METHODS[domain]["half_life"]))
        elif domain == "Labour":
            weights = np.power(float(METHODS[domain]["decay"]), ages)
        else:
            raise RuntimeError(f"exp_weighted_q80 is not declared for {domain}.")
        return max(
            0.0,
            weighted_quantile(absolute, weights, NOMINAL_COVERAGE),
        )

    raise RuntimeError(f"Unknown interval method: {method}")


def build_h4(
    selected: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    current = evaluation_rows(selected)
    detail_rows: list[dict] = []
    eligibility_rows: list[dict] = []

    for row in current.itertuples(index=False):
        domain = str(row.domain_name)
        spec = METHODS[domain]

        history = selected.loc[
            (selected["domain_name"] == domain)
            & (selected["target_series"].astype(str) == str(row.target_series))
            & (selected["forecast_stage"].astype(str) == str(row.forecast_stage))
            & (selected["selected_model"].astype(str) == str(row.selected_model))
        ].copy()

        valid = (
            history["actual_release_date"].notna()
            & history["forecast_date"].notna()
            & np.isfinite(history["point_forecast"])
            & np.isfinite(history["actual"])
            & (history["actual_release_date"] < pd.Timestamp(row.forecast_date))
        )
        prior = history.loc[valid].copy()
        prior = prior.sort_values(
            ["actual_release_date", "_period_order", "forecast_date"]
        )
        available_count = int(len(prior))
        window = prior.tail(int(spec["window"])).copy()
        window_count = int(len(window))
        eligible = int(window_count >= int(spec["minimum"]))

        cutoff_release = (
            window["actual_release_date"].max().date().isoformat()
            if not window.empty
            else ""
        )
        cutoff_period = str(window.iloc[-1]["target_period"]) if not window.empty else ""

        if not window.empty:
            if not bool(
                (window["actual_release_date"] < pd.Timestamp(row.forecast_date)).all()
            ):
                raise RuntimeError(
                    "H4 look-ahead gate failed for "
                    f"{domain}/{row.target_series}/{row.forecast_stage}/{row.target_period}."
                )

        eligibility_rows.append(
            {
                "domain_name": domain,
                "target_series": str(row.target_series),
                "stage_order": int(row.stage_order),
                "forecast_stage": str(row.forecast_stage),
                "target_period": str(row.target_period),
                "selected_model": str(row.selected_model),
                "forecast_date": pd.Timestamp(row.forecast_date).date().isoformat(),
                "actual_release_date": pd.Timestamp(
                    row.actual_release_date
                ).date().isoformat(),
                "prior_observable_error_count": available_count,
                "calibration_window_count": window_count,
                "minimum_prior_errors": int(spec["minimum"]),
                "calibration_window": int(spec["window"]),
                "calibration_cutoff_target_period": cutoff_period,
                "max_calibration_release_date": cutoff_release,
                "eligible_h4": eligible,
            }
        )

        methods = [str(spec["primary"])] + [str(x) for x in spec["benchmarks"]]
        for method in methods:
            base = {
                "domain_name": domain,
                "target_series": str(row.target_series),
                "stage_order": int(row.stage_order),
                "forecast_stage": str(row.forecast_stage),
                "target_period": str(row.target_period),
                "selected_model": str(row.selected_model),
                "forecast_date": pd.Timestamp(row.forecast_date).date().isoformat(),
                "actual_release_date": pd.Timestamp(
                    row.actual_release_date
                ).date().isoformat(),
                "interval_method": method,
                "is_primary": int(method == str(spec["primary"])),
                "eligible_h4": eligible,
                "nominal_coverage": NOMINAL_COVERAGE,
                "point_forecast": float(row.point_forecast),
                "actual": float(row.actual),
                "forecast_error": float(row.error),
                "prior_observable_error_count": available_count,
                "calibration_window_count": window_count,
                "minimum_prior_errors": int(spec["minimum"]),
                "calibration_window": int(spec["window"]),
                "calibration_cutoff_target_period": cutoff_period,
                "max_calibration_release_date": cutoff_release,
            }

            if not eligible:
                detail_rows.append(
                    {
                        **base,
                        "interval_half_width": np.nan,
                        "lower_80": np.nan,
                        "upper_80": np.nan,
                        "interval_width": np.nan,
                        "interval_covered": np.nan,
                        "violation": np.nan,
                        "lower_miss": np.nan,
                        "upper_miss": np.nan,
                        "interval_score": np.nan,
                    }
                )
                continue

            width = method_width(domain, method, window)
            point = float(row.point_forecast)
            actual = float(row.actual)
            lower = point - width
            upper = point + width
            covered = int(lower <= actual <= upper)
            lower_miss = int(actual < lower)
            upper_miss = int(actual > upper)
            violation = 1 - covered

            detail_rows.append(
                {
                    **base,
                    "interval_half_width": width,
                    "lower_80": lower,
                    "upper_80": upper,
                    "interval_width": upper - lower,
                    "interval_covered": covered,
                    "violation": violation,
                    "lower_miss": lower_miss,
                    "upper_miss": upper_miss,
                    "interval_score": interval_score(actual, lower, upper),
                }
            )

    detail = pd.DataFrame(detail_rows)
    audit = pd.DataFrame(eligibility_rows)

    if detail.empty or audit.empty:
        raise RuntimeError("H4 detail or eligibility audit is empty.")

    detail_key = [
        "domain_name",
        "target_series",
        "target_period",
        "forecast_stage",
        "interval_method",
    ]
    if detail.duplicated(detail_key, keep=False).any():
        raise RuntimeError("Duplicate H4 interval detail rows detected.")

    audit_key = ["domain_name", "target_series", "target_period", "forecast_stage"]
    if audit.duplicated(audit_key, keep=False).any():
        raise RuntimeError("Duplicate H4 eligibility rows detected.")

    return (
        detail.sort_values(
            [
                "domain_name",
                "target_series",
                "stage_order",
                "target_period",
                "is_primary",
                "interval_method",
            ],
            ascending=[True, True, True, True, False, True],
        ).reset_index(drop=True),
        audit.sort_values(
            ["domain_name", "target_series", "stage_order", "target_period"]
        ).reset_index(drop=True),
    )


def _xlogp(count: int, probability: float) -> float:
    if count == 0:
        return 0.0
    if probability <= 0.0:
        return -math.inf
    return float(count) * math.log(float(probability))


def _binomial_ll(successes: int, total: int, probability: float) -> float:
    failures = int(total - successes)
    return _xlogp(successes, probability) + _xlogp(failures, 1.0 - probability)


def _lr_nonnegative(value: float) -> float:
    if not np.isfinite(value):
        return np.nan
    return max(0.0, float(value))


def chi2_sf(stat: float, df: int) -> float:
    if not np.isfinite(stat) or stat < 0:
        return np.nan
    if df == 1:
        return math.erfc(math.sqrt(stat / 2.0))
    if df == 2:
        return math.exp(-stat / 2.0)
    raise ValueError("Only df=1 or df=2 is implemented.")


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return np.nan, np.nan
    phat = successes / n
    denom = 1.0 + (z * z) / n
    center = (phat + (z * z) / (2.0 * n)) / denom
    half = (
        z
        * math.sqrt(phat * (1.0 - phat) / n + (z * z) / (4.0 * n * n))
        / denom
    )
    return max(0.0, center - half), min(1.0, center + half)


def coverage_tests(violations: np.ndarray) -> dict[str, float | int]:
    v = np.asarray(violations, dtype=int)
    n = int(len(v))
    if n == 0:
        return {
            "violations": 0,
            "lr_uc": np.nan,
            "p_uc": np.nan,
            "n00": 0,
            "n01": 0,
            "n10": 0,
            "n11": 0,
            "lr_ind": np.nan,
            "p_ind": np.nan,
            "lr_cc": np.nan,
            "p_cc": np.nan,
        }

    x = int(v.sum())
    p_hat = x / n
    ll_null = _binomial_ll(x, n, ALPHA)
    ll_alt = _binomial_ll(x, n, p_hat)
    lr_uc = _lr_nonnegative(-2.0 * (ll_null - ll_alt))
    p_uc = chi2_sf(lr_uc, 1)

    if n < 2:
        return {
            "violations": x,
            "lr_uc": lr_uc,
            "p_uc": p_uc,
            "n00": 0,
            "n01": 0,
            "n10": 0,
            "n11": 0,
            "lr_ind": np.nan,
            "p_ind": np.nan,
            "lr_cc": np.nan,
            "p_cc": np.nan,
        }

    prev = v[:-1]
    curr = v[1:]
    n00 = int(np.sum((prev == 0) & (curr == 0)))
    n01 = int(np.sum((prev == 0) & (curr == 1)))
    n10 = int(np.sum((prev == 1) & (curr == 0)))
    n11 = int(np.sum((prev == 1) & (curr == 1)))

    n0 = n00 + n01
    n1 = n10 + n11
    trans_total = n0 + n1
    pi = (n01 + n11) / trans_total if trans_total else 0.0
    pi01 = n01 / n0 if n0 else 0.0
    pi11 = n11 / n1 if n1 else 0.0

    ll_iid = (
        _xlogp(n01 + n11, pi)
        + _xlogp(n00 + n10, 1.0 - pi)
    )
    ll_markov = (
        _xlogp(n01, pi01)
        + _xlogp(n00, 1.0 - pi01)
        + _xlogp(n11, pi11)
        + _xlogp(n10, 1.0 - pi11)
    )
    lr_ind = _lr_nonnegative(-2.0 * (ll_iid - ll_markov))
    p_ind = chi2_sf(lr_ind, 1)
    lr_cc = (
        float(lr_uc + lr_ind)
        if np.isfinite(lr_uc) and np.isfinite(lr_ind)
        else np.nan
    )
    p_cc = chi2_sf(lr_cc, 2) if np.isfinite(lr_cc) else np.nan

    return {
        "violations": x,
        "lr_uc": lr_uc,
        "p_uc": p_uc,
        "n00": n00,
        "n01": n01,
        "n10": n10,
        "n11": n11,
        "lr_ind": lr_ind,
        "p_ind": p_ind,
        "lr_cc": lr_cc,
        "p_cc": p_cc,
    }


def summarise_intervals(detail: pd.DataFrame) -> pd.DataFrame:
    usable = detail.loc[detail["eligible_h4"] == 1].copy()
    rows: list[dict] = []
    group_cols = [
        "domain_name",
        "target_series",
        "stage_order",
        "forecast_stage",
        "selected_model",
        "interval_method",
        "is_primary",
    ]
    for keys, group in usable.groupby(group_cols, sort=False):
        (
            domain,
            target,
            stage_order,
            stage,
            model,
            method,
            is_primary,
        ) = keys
        group = group.sort_values(["forecast_date", "target_period"])
        n = int(len(group))
        covered = int(group["interval_covered"].sum())
        coverage = covered / n
        wilson_low, wilson_high = wilson_interval(covered, n)
        tests = coverage_tests(group["violation"].to_numpy(dtype=int))
        rows.append(
            {
                "domain_name": domain,
                "target_series": target,
                "stage_order": int(stage_order),
                "forecast_stage": stage,
                "selected_model": model,
                "interval_method": method,
                "is_primary": int(is_primary),
                "n": n,
                "covered": covered,
                "violations": int(tests["violations"]),
                "coverage": coverage,
                "coverage_gap_from_080": coverage - NOMINAL_COVERAGE,
                "wilson_95_low": wilson_low,
                "wilson_95_high": wilson_high,
                "lr_uc": tests["lr_uc"],
                "p_uc": tests["p_uc"],
                "n00": int(tests["n00"]),
                "n01": int(tests["n01"]),
                "n10": int(tests["n10"]),
                "n11": int(tests["n11"]),
                "lr_ind": tests["lr_ind"],
                "p_ind": tests["p_ind"],
                "lr_cc": tests["lr_cc"],
                "p_cc": tests["p_cc"],
                "average_interval_width": float(group["interval_width"].mean()),
                "average_half_width": float(group["interval_half_width"].mean()),
                "mean_interval_score": float(group["interval_score"].mean()),
                "median_interval_score": float(group["interval_score"].median()),
                "lower_miss_rate": float(group["lower_miss"].mean()),
                "upper_miss_rate": float(group["upper_miss"].mean()),
                "minimum_calibration_count": int(
                    group["calibration_window_count"].min()
                ),
                "maximum_calibration_count": int(
                    group["calibration_window_count"].max()
                ),
            }
        )
    summary = pd.DataFrame(rows)
    if summary.empty:
        raise RuntimeError("H4 interval summary is empty.")
    return summary.sort_values(
        ["domain_name", "target_series", "stage_order", "is_primary", "interval_method"],
        ascending=[True, True, True, False, True],
    ).reset_index(drop=True)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def hac_mean_summary(values: pd.Series) -> dict[str, float | int]:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    n = int(len(x))
    if n == 0:
        return {
            "n": 0,
            "mean": np.nan,
            "median": np.nan,
            "hac_bw": 0,
            "hac_se": np.nan,
            "hac_z": np.nan,
            "hac_p": np.nan,
        }
    mean = float(np.mean(x))
    median = float(np.median(x))
    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "median": median,
            "hac_bw": 0,
            "hac_se": np.nan,
            "hac_z": np.nan,
            "hac_p": np.nan,
        }
    bandwidth = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    bandwidth = min(max(bandwidth, 0), n - 1)
    u = x - mean
    gamma0 = float(np.dot(u, u) / n)
    lrv = gamma0
    for lag in range(1, bandwidth + 1):
        gamma = float(np.dot(u[lag:], u[:-lag]) / n)
        weight = 1.0 - lag / (bandwidth + 1.0)
        lrv += 2.0 * weight * gamma
    lrv = max(lrv, 0.0)
    se = math.sqrt(lrv / n)
    z = mean / se if se > 0 else np.nan
    p = 2.0 * (1.0 - normal_cdf(abs(z))) if np.isfinite(z) else np.nan
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "hac_bw": bandwidth,
        "hac_se": se,
        "hac_z": z,
        "hac_p": p,
    }


def compare_methods(detail: pd.DataFrame) -> pd.DataFrame:
    usable = detail.loc[detail["eligible_h4"] == 1].copy()
    rows: list[dict] = []
    key = [
        "domain_name",
        "target_series",
        "stage_order",
        "forecast_stage",
        "target_period",
        "selected_model",
    ]

    for domain, spec in METHODS.items():
        primary_method = str(spec["primary"])
        primary = usable.loc[
            (usable["domain_name"] == domain)
            & (usable["interval_method"] == primary_method),
            key
            + [
                "forecast_date",
                "interval_score",
                "interval_width",
                "interval_covered",
            ],
        ].copy()

        for benchmark_method in [str(x) for x in spec["benchmarks"]]:
            benchmark = usable.loc[
                (usable["domain_name"] == domain)
                & (usable["interval_method"] == benchmark_method),
                key
                + [
                    "interval_score",
                    "interval_width",
                    "interval_covered",
                ],
            ].copy()

            pair = primary.merge(
                benchmark,
                on=key,
                how="inner",
                suffixes=("_primary", "_benchmark"),
                validate="one_to_one",
            )
            if pair.empty:
                continue
            pair["score_diff_primary_minus_benchmark"] = (
                pair["interval_score_primary"] - pair["interval_score_benchmark"]
            )
            pair["width_diff_primary_minus_benchmark"] = (
                pair["interval_width_primary"] - pair["interval_width_benchmark"]
            )

            for cell, group in pair.groupby(
                [
                    "domain_name",
                    "target_series",
                    "stage_order",
                    "forecast_stage",
                    "selected_model",
                ],
                sort=False,
            ):
                d, target, order, stage, model = cell
                group = group.sort_values(["forecast_date", "target_period"])
                score = hac_mean_summary(
                    group["score_diff_primary_minus_benchmark"]
                )
                width = hac_mean_summary(
                    group["width_diff_primary_minus_benchmark"]
                )
                rows.append(
                    {
                        "domain_name": d,
                        "target_series": target,
                        "stage_order": int(order),
                        "forecast_stage": stage,
                        "selected_model": model,
                        "primary_method": primary_method,
                        "benchmark_method": benchmark_method,
                        "n": int(score["n"]),
                        "primary_coverage": float(
                            group["interval_covered_primary"].mean()
                        ),
                        "benchmark_coverage": float(
                            group["interval_covered_benchmark"].mean()
                        ),
                        "coverage_diff_p_minus_b": float(
                            group["interval_covered_primary"].mean()
                            - group["interval_covered_benchmark"].mean()
                        ),
                        "mean_score_diff_p_minus_b": score["mean"],
                        "median_score_diff_p_minus_b": score["median"],
                        "hac_bw_score": int(score["hac_bw"]),
                        "hac_se_score": score["hac_se"],
                        "hac_z_score": score["hac_z"],
                        "hac_p_score_two_sided": score["hac_p"],
                        "mean_width_diff_p_minus_b": width["mean"],
                        "median_width_diff_p_minus_b": width["median"],
                    }
                )

    comparison = pd.DataFrame(rows)
    if comparison.empty:
        raise RuntimeError("H4 method-comparison table is empty.")
    return comparison.sort_values(
        [
            "domain_name",
            "target_series",
            "stage_order",
            "benchmark_method",
        ]
    ).reset_index(drop=True)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n")


def package_versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for name in ["duckdb", "numpy", "pandas"]:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = "unavailable"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--macropulse-root", default="../MacroPulse")
    args = parser.parse_args()

    paper_root = Path(args.paper_root).resolve()
    macro_root = Path(args.macropulse_root).resolve()
    db_path = macro_root / "data" / "macropulse.duckdb"
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    print("=" * 96)
    print("CONFIRMATORY H4 — PRIOR-ONLY 80% PREDICTION INTERVALS")
    print("=" * 96)

    analysis_commit, script_sha, audit_sha, design_sha = verify_preanalysis_boundaries(
        paper_root, macro_root
    )
    print(f"Pre-H4 checkpoint:       {PRE_H4_CHECKPOINT}")
    print(f"Policy freeze commit:    {POLICY_FREEZE_COMMIT}")
    print(f"H4 preanalysis commit:   {analysis_commit}")
    print(f"Python script SHA256:     {script_sha}")
    print(f"Stata audit SHA256:       {audit_sha}")
    print(f"H4 design SHA256:         {design_sha}")
    print(f"Pinned MacroPulse source: {MACROPULSE_SOURCE_COMMIT}")
    print("PRE-ANALYSIS BOUNDARY VERIFICATION: PASS")

    stage_policy = load_stage_policy(paper_root)

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        source = load_backtest_rows(con)
    finally:
        con.close()

    selected = select_frozen_policy_rows(source, stage_policy)
    detail, eligibility = build_h4(selected)
    summary = summarise_intervals(detail)
    comparison = compare_methods(detail)

    out = paper_root / "outputs" / "confirmatory"
    out.mkdir(parents=True, exist_ok=True)

    detail_path = out / "h4_interval_detail.csv"
    summary_path = out / "h4_interval_summary.csv"
    eligibility_path = out / "h4_interval_eligibility_audit.csv"
    comparison_path = out / "h4_interval_method_comparisons.csv"
    manifest_path = out / "confirmatory_h4_manifest.json"

    write_csv(detail, detail_path)
    write_csv(summary, summary_path)
    write_csv(eligibility, eligibility_path)
    write_csv(comparison, comparison_path)

    primary_eligible = detail.loc[
        (detail["is_primary"] == 1) & (detail["eligible_h4"] == 1)
    ]

    manifest = {
        "hypothesis": "H4",
        "estimand": "prior_only_80_percent_prediction_interval_calibration",
        "nominal_coverage": NOMINAL_COVERAGE,
        "pre_h4_checkpoint": PRE_H4_CHECKPOINT,
        "policy_freeze_commit": POLICY_FREEZE_COMMIT,
        "preanalysis_code_commit": analysis_commit,
        "analysis_script_sha256": script_sha,
        "stata_audit_sha256": audit_sha,
        "design_freeze_sha256": design_sha,
        "macropulse_source_commit": MACROPULSE_SOURCE_COMMIT,
        "source_backtest_ids": {
            "GDP": GDP_BACKTEST,
            "Inflation": INFLATION_BACKTEST,
            "Labour": LABOUR_BACKTEST,
        },
        "evaluation_start": EVALUATION_START,
        "availability_rule": (
            "A calibration error is admissible only when its stored "
            "actual_release_date is strictly earlier than the current forecast_date."
        ),
        "policy_rule": (
            "Intervals surround the development-frozen research stage-policy forecast; "
            "calibration is same target, same stage, same selected model."
        ),
        "domain_methods": METHODS,
        "rolling_quantile_rule": "NumPy empirical q80 with method='higher'.",
        "inflation_weight_rule": "0.5 ** (age / 18), newest error age zero.",
        "labour_weight_rule": "0.94 ** age, newest error age zero.",
        "gaussian_benchmark_rule": (
            "NormalDist().inv_cdf(0.90) * sqrt(mean(prior signed error^2))."
        ),
        "coverage_inference": (
            "Wilson 95% confidence interval; Christoffersen unconditional coverage, "
            "violation independence, and joint conditional-coverage likelihood-ratio tests."
        ),
        "score_inference": (
            "Primary interval score minus benchmark score; Newey-West HAC SE with "
            "Bartlett weights and bandwidth floor(4*(n/100)^(2/9)); negative favours primary."
        ),
        "sample_rule": (
            "Stage-specific available evaluation cells; no complete-stage balancing. "
            "Cells below the domain minimum calibration history are H4-ineligible."
        ),
        "row_counts": {
            "detail": int(len(detail)),
            "eligibility": int(len(eligibility)),
            "summary": int(len(summary)),
            "method_comparisons": int(len(comparison)),
            "primary_eligible_forecasts": int(len(primary_eligible)),
            "primary_ineligible_forecasts": int(
                ((detail["is_primary"] == 1) & (detail["eligible_h4"] == 0)).sum()
            ),
        },
        "source_stage_policy_sha256": sha256_file(
            paper_root / "freeze" / "research_stage_policy_freeze.csv"
        ),
        "package_versions": package_versions(),
        "output_hashes": {
            detail_path.name: sha256_file(detail_path),
            summary_path.name: sha256_file(summary_path),
            eligibility_path.name: sha256_file(eligibility_path),
            comparison_path.name: sha256_file(comparison_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print()
    print("=" * 96)
    print("H4 PRIMARY STAGE-CELL RESULTS")
    print("=" * 96)
    primary_summary = summary.loc[summary["is_primary"] == 1]
    print(
        primary_summary[
            [
                "domain_name",
                "target_series",
                "forecast_stage",
                "selected_model",
                "n",
                "coverage",
                "wilson_95_low",
                "wilson_95_high",
                "p_uc",
                "p_ind",
                "p_cc",
                "average_interval_width",
                "mean_interval_score",
            ]
        ].to_string(index=False)
    )

    print()
    print("=" * 96)
    print("H4 PRIMARY-vs-BENCHMARK INTERVAL-SCORE COMPARISONS")
    print("Negative score differential favours the primary interval method.")
    print("=" * 96)
    print(
        comparison[
            [
                "domain_name",
                "target_series",
                "forecast_stage",
                "primary_method",
                "benchmark_method",
                "n",
                "mean_score_diff_p_minus_b",
                "hac_se_score",
                "hac_p_score_two_sided",
                "mean_width_diff_p_minus_b",
            ]
        ].to_string(index=False)
    )

    print()
    print("=" * 96)
    print("H4 OUTPUT HASHES")
    print("=" * 96)
    for name, digest in manifest["output_hashes"].items():
        print(f"{name}: {digest}")
    print(f"Manifest: {manifest_path}")

    print()
    print("=" * 96)
    print("CONFIRMATORY H4 EVALUATION COMPLETED SUCCESSFULLY")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
