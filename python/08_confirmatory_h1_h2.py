from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


FREEZE_COMMIT = "420feaeb51dca3abc79e9426aacca3816fe6ad5a"

GDP_BACKTEST = "382b4c6b-ef76-4ca1-b52f-d5e3e1ac66b1"
INFLATION_BACKTEST = "fdd2f573-a425-4abc-8056-f9843955bac2"
LABOUR_BACKTEST = "834e0655-ba81-4b96-b42c-e1cdda73b847"

EVALUATION_START = {
    "GDP": "2023Q2",
    "Inflation": "2023-02",
    "Labour": "2023-02",
}

STAGES = {
    "GDP": [
        "early_quarter",
        "after_month_1",
        "after_month_2",
        "quarter_end",
        "pre_advance_release",
    ],
    "Inflation": [
        "month_open",
        "mid_month",
        "month_end",
        "pre_release",
    ],
    "Labour": [
        "month_open",
        "after_week_1",
        "after_week_2",
        "month_end",
        "pre_employment_report",
    ],
}

TARGETS = {
    "GDP": ["GDPC1"],
    "Inflation": ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"],
    "Labour": ["CES0500000003", "PAYEMS", "UNRATE"],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_show_bytes(repo: Path, commit: str, relpath: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{commit}:{relpath}"],
        stderr=subprocess.STDOUT,
    )


def verify_freeze(paper_root: Path) -> dict:
    manifest_path = paper_root / "freeze" / "research_policy_freeze_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    for group_name, base in [
        ("freeze_files", paper_root / "freeze"),
        ("diagnostic_development_files", paper_root / "outputs" / "tables"),
    ]:
        for name, expected in manifest.get(group_name, {}).items():
            path = base / name
            if not path.is_file():
                failures.append(f"missing working file: {path}")
                continue
            actual = sha256_file(path)
            if actual != expected:
                failures.append(
                    f"working hash mismatch: {path} expected={expected} actual={actual}"
                )

    try:
        subprocess.check_call(
            ["git", "-C", str(paper_root), "cat-file", "-e", f"{FREEZE_COMMIT}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Canonical freeze commit {FREEZE_COMMIT} is not available locally."
        ) from exc

    committed_manifest = json.loads(
        git_show_bytes(
            paper_root,
            FREEZE_COMMIT,
            "freeze/research_policy_freeze_manifest.json",
        ).decode("utf-8")
    )
    if committed_manifest != manifest:
        failures.append("working freeze manifest differs from canonical freeze commit")

    for group_name, prefix in [
        ("freeze_files", "freeze/"),
        ("diagnostic_development_files", "outputs/tables/"),
    ]:
        for name, expected in manifest.get(group_name, {}).items():
            actual = sha256_bytes(
                git_show_bytes(paper_root, FREEZE_COMMIT, prefix + name)
            )
            if actual != expected:
                failures.append(
                    f"committed hash mismatch: {prefix + name} expected={expected} actual={actual}"
                )

    if failures:
        raise RuntimeError("Freeze verification failed:\n" + "\n".join(failures))
    return manifest




def verify_analysis_script_committed(paper_root: Path) -> tuple[str, str]:
    """Require the confirmatory analysis code to be committed before evaluation."""
    relpath = "python/08_confirmatory_h1_h2.py"
    script_path = paper_root / relpath
    if not script_path.is_file():
        raise FileNotFoundError(script_path)
    head = subprocess.check_output(
        ["git", "-C", str(paper_root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    try:
        committed = git_show_bytes(paper_root, head, relpath)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Confirmatory script is not committed at HEAD. Commit the exact 08 script before opening evaluation losses."
        ) from exc
    working = script_path.read_bytes()
    if committed != working:
        raise RuntimeError(
            "Working confirmatory script differs from the committed HEAD version. "
            "Commit the exact script before opening evaluation losses."
        )
    return head, sha256_bytes(working)

def load_freeze_tables(paper_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    stage_policy = pd.read_csv(
        paper_root / "freeze" / "research_stage_policy_freeze.csv"
    )
    fixed = pd.read_csv(
        paper_root / "freeze" / "research_fixed_comparator_freeze.csv"
    )
    if len(stage_policy) != 36:
        raise RuntimeError(f"Expected 36 frozen stage-policy rows, got {len(stage_policy)}.")
    if len(fixed) != 8:
        raise RuntimeError(f"Expected 8 frozen fixed comparators, got {len(fixed)}.")
    return stage_policy, fixed


def sql_list(values: list[str]) -> str:
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


def load_evaluation_rows(
    con: duckdb.DuckDBPyConnection,
    stage_policy: pd.DataFrame,
    fixed: pd.DataFrame,
) -> pd.DataFrame:
    needed: dict[str, set[str]] = {"GDP": set(), "Inflation": set(), "Labour": set()}
    for domain in needed:
        needed[domain].update(
            fixed.loc[fixed["domain_name"] == domain, "selected_model"].astype(str)
        )
        needed[domain].update(
            stage_policy.loc[
                stage_policy["domain_name"] == domain, "selected_model"
            ].astype(str)
        )

    gdp_models = sql_list(sorted(needed["GDP"]))
    inf_models = sql_list(sorted(needed["Inflation"]))
    lab_models = sql_list(sorted(needed["Labour"]))

    gdp = con.execute(
        f"""
        SELECT 'GDP' AS domain_name, 'GDPC1' AS target_series,
               target_period, forecast_stage, forecast_date,
               actual_release_date, model_name, point_forecast,
               actual, information_set_hash
        FROM stage_backtest_results
        WHERE stage_backtest_id = ?
          AND target_period >= ?
          AND model_name IN ({gdp_models})
        ORDER BY target_period, forecast_stage, model_name
        """,
        [GDP_BACKTEST, EVALUATION_START["GDP"]],
    ).fetchdf()

    inflation = con.execute(
        f"""
        SELECT 'Inflation' AS domain_name, target_series,
               target_period, forecast_stage, forecast_date,
               actual_release_date, model_name, point_forecast,
               actual, information_set_hash
        FROM inflation_vintage_backtest_results
        WHERE backtest_id = ?
          AND target_period >= ?
          AND model_name IN ({inf_models})
        ORDER BY target_series, target_period, forecast_stage, model_name
        """,
        [INFLATION_BACKTEST, EVALUATION_START["Inflation"]],
    ).fetchdf()

    labour = con.execute(
        f"""
        SELECT 'Labour' AS domain_name, target_series,
               target_period, forecast_stage, forecast_date,
               actual_release_date, model_name, point_forecast,
               actual, information_set_hash
        FROM labour_vintage_backtest_results
        WHERE backtest_id = ?
          AND target_period >= ?
          AND model_name IN ({lab_models})
        ORDER BY target_series, target_period, forecast_stage, model_name
        """,
        [LABOUR_BACKTEST, EVALUATION_START["Labour"]],
    ).fetchdf()

    frame = pd.concat([gdp, inflation, labour], ignore_index=True)
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"])
    frame["actual_release_date"] = pd.to_datetime(frame["actual_release_date"])
    frame["error_recomputed"] = frame["actual"] - frame["point_forecast"]
    frame["abs_error_recomputed"] = frame["error_recomputed"].abs()
    frame["squared_error_recomputed"] = frame["error_recomputed"] ** 2
    return frame


def validate_evaluation_rows(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise RuntimeError("No confirmatory evaluation rows were loaded.")

    key = [
        "domain_name",
        "target_series",
        "target_period",
        "forecast_stage",
        "model_name",
    ]
    dup = frame.duplicated(key, keep=False)
    if dup.any():
        raise RuntimeError(
            "Duplicate evaluation forecasts detected:\n"
            + frame.loc[dup, key].head(20).to_string(index=False)
        )

    valid = (
        frame["actual"].notna()
        & frame["point_forecast"].notna()
        & np.isfinite(pd.to_numeric(frame["actual"], errors="coerce"))
        & np.isfinite(pd.to_numeric(frame["point_forecast"], errors="coerce"))
    )
    if not bool(valid.all()):
        bad = frame.loc[~valid, key + ["actual", "point_forecast"]]
        raise RuntimeError(
            "Missing/nonfinite evaluation actuals or forecasts:\n"
            + bad.head(20).to_string(index=False)
        )

    for domain in ("GDP", "Inflation", "Labour"):
        subset = frame.loc[frame["domain_name"] == domain]
        if subset.empty:
            raise RuntimeError(f"No evaluation rows loaded for {domain}.")
        unknown_stages = sorted(set(subset["forecast_stage"]) - set(STAGES[domain]))
        unknown_targets = sorted(set(subset["target_series"]) - set(TARGETS[domain]))
        if unknown_stages:
            raise RuntimeError(f"Unknown {domain} stages: {unknown_stages}")
        if unknown_targets:
            raise RuntimeError(f"Unknown {domain} targets: {unknown_targets}")


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def paired_summary(diff: pd.Series) -> dict:
    """Summarise a chronological loss-differential series.

    Confirmatory inference uses a Newey-West HAC standard error for the mean
    with Bartlett weights and the predeclared automatic bandwidth
        floor(4 * (n / 100) ** (2 / 9)).
    The bandwidth depends only on sample size, not on observed performance.
    """
    x = pd.to_numeric(diff, errors="coerce").dropna().to_numpy(dtype=float)
    n = int(len(x))
    if n == 0:
        return {
            "n": 0,
            "mean_diff": np.nan,
            "median_diff": np.nan,
            "improvement_share": np.nan,
            "hac_bandwidth": 0,
            "hac_se_mean": np.nan,
            "hac_z_mean": np.nan,
            "hac_p_value_mean_two_sided": np.nan,
        }

    mean = float(np.mean(x))
    median = float(np.median(x))
    improvement_share = float(np.mean(x < 0))

    if n >= 2:
        bandwidth = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
        bandwidth = min(max(bandwidth, 0), n - 1)
        u = x - mean
        gamma0 = float(np.dot(u, u) / n)
        lrv = gamma0
        for lag in range(1, bandwidth + 1):
            gamma_l = float(np.dot(u[lag:], u[:-lag]) / n)
            weight = 1.0 - lag / (bandwidth + 1.0)
            lrv += 2.0 * weight * gamma_l
        lrv = max(lrv, 0.0)
        se = math.sqrt(lrv / n)
        z = mean / se if se > 0 else np.nan
        p = 2.0 * (1.0 - normal_cdf(abs(z))) if np.isfinite(z) else np.nan
    else:
        bandwidth = 0
        se = z = p = np.nan

    return {
        "n": n,
        "mean_diff": mean,
        "median_diff": median,
        "improvement_share": improvement_share,
        "hac_bandwidth": bandwidth,
        "hac_se_mean": se,
        "hac_z_mean": z,
        "hac_p_value_mean_two_sided": p,
    }


def build_h1(
    frame: pd.DataFrame,
    fixed: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []

    for domain in ("GDP", "Inflation", "Labour"):
        for target in TARGETS[domain]:
            fixed_rows = fixed.loc[
                (fixed["domain_name"] == domain)
                & (fixed["target_series"] == target)
            ]
            if len(fixed_rows) != 1:
                raise RuntimeError(f"Expected one fixed comparator for {domain}/{target}.")
            model = str(fixed_rows.iloc[0]["selected_model"])

            subset = frame.loc[
                (frame["domain_name"] == domain)
                & (frame["target_series"] == target)
                & (frame["model_name"] == model)
            ].copy()

            for transition_order in range(1, len(STAGES[domain])):
                stage_0 = STAGES[domain][transition_order - 1]
                stage_1 = STAGES[domain][transition_order]

                cols = [
                    "target_period",
                    "forecast_date",
                    "actual",
                    "point_forecast",
                    "information_set_hash",
                    "squared_error_recomputed",
                    "abs_error_recomputed",
                ]
                left = subset.loc[subset["forecast_stage"] == stage_0, cols].copy()
                right = subset.loc[subset["forecast_stage"] == stage_1, cols].copy()

                pair = left.merge(
                    right,
                    on="target_period",
                    how="inner",
                    suffixes=("_earlier", "_later"),
                    validate="one_to_one",
                )
                if pair.empty:
                    continue

                actual_ok = np.isclose(
                    pair["actual_earlier"].astype(float),
                    pair["actual_later"].astype(float),
                    atol=1e-12,
                    rtol=0,
                )
                if not bool(np.all(actual_ok)):
                    raise RuntimeError(
                        f"H1 actual mismatch for {domain}/{target}/{stage_0}->{stage_1}."
                    )

                pair["hash_changed"] = (
                    pair["information_set_hash_earlier"].astype(str)
                    != pair["information_set_hash_later"].astype(str)
                )
                pair["eligible_h1"] = pair["hash_changed"]

                for rec in pair.itertuples(index=False):
                    rows.append(
                        {
                            "domain_name": domain,
                            "target_series": target,
                            "transition_order": transition_order,
                            "earlier_stage": stage_0,
                            "later_stage": stage_1,
                            "target_period": rec.target_period,
                            "fixed_model": model,
                            "earlier_forecast_date": rec.forecast_date_earlier,
                            "later_forecast_date": rec.forecast_date_later,
                            "earlier_information_set_hash": rec.information_set_hash_earlier,
                            "later_information_set_hash": rec.information_set_hash_later,
                            "hash_changed": int(rec.hash_changed),
                            "eligible_h1": int(rec.eligible_h1),
                            "actual": rec.actual_earlier,
                            "earlier_point_forecast": rec.point_forecast_earlier,
                            "later_point_forecast": rec.point_forecast_later,
                            "earlier_squared_error": rec.squared_error_recomputed_earlier,
                            "later_squared_error": rec.squared_error_recomputed_later,
                            "delta_squared_error": (
                                rec.squared_error_recomputed_later
                                - rec.squared_error_recomputed_earlier
                            ),
                            "earlier_abs_error": rec.abs_error_recomputed_earlier,
                            "later_abs_error": rec.abs_error_recomputed_later,
                            "delta_abs_error": (
                                rec.abs_error_recomputed_later
                                - rec.abs_error_recomputed_earlier
                            ),
                        }
                    )

    detail = pd.DataFrame(rows)
    if detail.empty:
        raise RuntimeError("H1 detail table is empty.")

    summary_rows: list[dict] = []
    eligible = detail.loc[detail["eligible_h1"] == 1].copy()
    for keys, group in eligible.groupby(
        ["domain_name", "target_series", "transition_order", "earlier_stage", "later_stage"],
        sort=False,
    ):
        domain, target, order, stage_0, stage_1 = keys
        sq = paired_summary(group["delta_squared_error"])
        ae = paired_summary(group["delta_abs_error"])
        summary_rows.append(
            {
                "domain_name": domain,
                "target_series": target,
                "transition_order": order,
                "earlier_stage": stage_0,
                "later_stage": stage_1,
                "fixed_model": group["fixed_model"].iloc[0],
                "eligible_pairs": int(len(group)),
                "excluded_same_hash_pairs": int(
                    len(
                        detail.loc[
                            (detail["domain_name"] == domain)
                            & (detail["target_series"] == target)
                            & (detail["transition_order"] == order)
                            & (detail["eligible_h1"] == 0)
                        ]
                    )
                ),
                "mean_delta_squared_error": sq["mean_diff"],
                "median_delta_squared_error": sq["median_diff"],
                "squared_error_improvement_share": sq["improvement_share"],
                "hac_bandwidth_squared_error": sq["hac_bandwidth"],
                "hac_se_mean_delta_squared_error": sq["hac_se_mean"],
                "hac_z_mean_delta_squared_error": sq["hac_z_mean"],
                "hac_p_value_squared_error_two_sided": sq["hac_p_value_mean_two_sided"],
                "mean_delta_abs_error": ae["mean_diff"],
                "median_delta_abs_error": ae["median_diff"],
                "abs_error_improvement_share": ae["improvement_share"],
                "hac_bandwidth_abs_error": ae["hac_bandwidth"],
                "hac_se_mean_delta_abs_error": ae["hac_se_mean"],
                "hac_z_mean_delta_abs_error": ae["hac_z_mean"],
                "hac_p_value_abs_error_two_sided": ae["hac_p_value_mean_two_sided"],
            }
        )
    return detail, pd.DataFrame(summary_rows)


def build_h2(
    frame: pd.DataFrame,
    stage_policy: pd.DataFrame,
    fixed: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []

    for domain in ("GDP", "Inflation", "Labour"):
        for target in TARGETS[domain]:
            fixed_rows = fixed.loc[
                (fixed["domain_name"] == domain)
                & (fixed["target_series"] == target)
            ]
            if len(fixed_rows) != 1:
                raise RuntimeError(f"Expected one fixed comparator for {domain}/{target}.")
            fixed_model = str(fixed_rows.iloc[0]["selected_model"])

            for stage_order, stage in enumerate(STAGES[domain], start=1):
                policy_rows = stage_policy.loc[
                    (stage_policy["domain_name"] == domain)
                    & (stage_policy["target_series"] == target)
                    & (stage_policy["forecast_stage"] == stage)
                ]
                if len(policy_rows) != 1:
                    raise RuntimeError(
                        f"Expected one stage policy for {domain}/{target}/{stage}."
                    )
                stage_model = str(policy_rows.iloc[0]["selected_model"])

                policy_fc = frame.loc[
                    (frame["domain_name"] == domain)
                    & (frame["target_series"] == target)
                    & (frame["forecast_stage"] == stage)
                    & (frame["model_name"] == stage_model)
                ].copy()

                fixed_fc = frame.loc[
                    (frame["domain_name"] == domain)
                    & (frame["target_series"] == target)
                    & (frame["forecast_stage"] == stage)
                    & (frame["model_name"] == fixed_model)
                ].copy()

                if stage_model == fixed_model:
                    if policy_fc.empty:
                        continue
                    for rec in policy_fc.itertuples(index=False):
                        rows.append(
                            {
                                "domain_name": domain,
                                "target_series": target,
                                "stage_order": stage_order,
                                "forecast_stage": stage,
                                "target_period": rec.target_period,
                                "stage_policy_model": stage_model,
                                "fixed_model": fixed_model,
                                "forecast_date": rec.forecast_date,
                                "information_set_hash": rec.information_set_hash,
                                "actual": rec.actual,
                                "stage_policy_point_forecast": rec.point_forecast,
                                "fixed_point_forecast": rec.point_forecast,
                                "stage_policy_squared_error": rec.squared_error_recomputed,
                                "fixed_squared_error": rec.squared_error_recomputed,
                                "delta_squared_error": 0.0,
                                "stage_policy_abs_error": rec.abs_error_recomputed,
                                "fixed_abs_error": rec.abs_error_recomputed,
                                "delta_abs_error": 0.0,
                            }
                        )
                    continue

                cols = [
                    "target_period",
                    "forecast_date",
                    "actual",
                    "information_set_hash",
                    "point_forecast",
                    "squared_error_recomputed",
                    "abs_error_recomputed",
                ]
                left = policy_fc[cols].copy()
                right = fixed_fc[cols].copy()
                pair = left.merge(
                    right,
                    on="target_period",
                    how="inner",
                    suffixes=("_policy", "_fixed"),
                    validate="one_to_one",
                )
                if pair.empty:
                    continue

                if not bool((pair["forecast_date_policy"] == pair["forecast_date_fixed"]).all()):
                    raise RuntimeError(f"H2 forecast-date mismatch for {domain}/{target}/{stage}.")
                if not bool(
                    (
                        pair["information_set_hash_policy"].astype(str)
                        == pair["information_set_hash_fixed"].astype(str)
                    ).all()
                ):
                    raise RuntimeError(
                        f"H2 information-set mismatch for {domain}/{target}/{stage}."
                    )
                actual_ok = np.isclose(
                    pair["actual_policy"].astype(float),
                    pair["actual_fixed"].astype(float),
                    atol=1e-12,
                    rtol=0,
                )
                if not bool(np.all(actual_ok)):
                    raise RuntimeError(f"H2 actual mismatch for {domain}/{target}/{stage}.")

                for rec in pair.itertuples(index=False):
                    rows.append(
                        {
                            "domain_name": domain,
                            "target_series": target,
                            "stage_order": stage_order,
                            "forecast_stage": stage,
                            "target_period": rec.target_period,
                            "stage_policy_model": stage_model,
                            "fixed_model": fixed_model,
                            "forecast_date": rec.forecast_date_policy,
                            "information_set_hash": rec.information_set_hash_policy,
                            "actual": rec.actual_policy,
                            "stage_policy_point_forecast": rec.point_forecast_policy,
                            "fixed_point_forecast": rec.point_forecast_fixed,
                            "stage_policy_squared_error": rec.squared_error_recomputed_policy,
                            "fixed_squared_error": rec.squared_error_recomputed_fixed,
                            "delta_squared_error": (
                                rec.squared_error_recomputed_policy
                                - rec.squared_error_recomputed_fixed
                            ),
                            "stage_policy_abs_error": rec.abs_error_recomputed_policy,
                            "fixed_abs_error": rec.abs_error_recomputed_fixed,
                            "delta_abs_error": (
                                rec.abs_error_recomputed_policy
                                - rec.abs_error_recomputed_fixed
                            ),
                        }
                    )

    detail = pd.DataFrame(rows)
    if detail.empty:
        raise RuntimeError("H2 detail table is empty.")

    summary_rows: list[dict] = []
    for keys, group in detail.groupby(
        ["domain_name", "target_series", "stage_order", "forecast_stage"],
        sort=False,
    ):
        domain, target, order, stage = keys
        sq = paired_summary(group["delta_squared_error"])
        ae = paired_summary(group["delta_abs_error"])
        summary_rows.append(
            {
                "domain_name": domain,
                "target_series": target,
                "stage_order": order,
                "forecast_stage": stage,
                "stage_policy_model": group["stage_policy_model"].iloc[0],
                "fixed_model": group["fixed_model"].iloc[0],
                "n": int(len(group)),
                "same_model": int(
                    group["stage_policy_model"].iloc[0]
                    == group["fixed_model"].iloc[0]
                ),
                "mean_delta_squared_error": sq["mean_diff"],
                "median_delta_squared_error": sq["median_diff"],
                "squared_error_policy_win_share": sq["improvement_share"],
                "hac_bandwidth_squared_error": sq["hac_bandwidth"],
                "hac_se_mean_delta_squared_error": sq["hac_se_mean"],
                "hac_z_mean_delta_squared_error": sq["hac_z_mean"],
                "hac_p_value_squared_error_two_sided": sq["hac_p_value_mean_two_sided"],
                "mean_delta_abs_error": ae["mean_diff"],
                "median_delta_abs_error": ae["median_diff"],
                "abs_error_policy_win_share": ae["improvement_share"],
                "hac_bandwidth_abs_error": ae["hac_bandwidth"],
                "hac_se_mean_delta_abs_error": ae["hac_se_mean"],
                "hac_z_mean_delta_abs_error": ae["hac_z_mean"],
                "hac_p_value_abs_error_two_sided": ae["hac_p_value_mean_two_sided"],
            }
        )
    return detail, pd.DataFrame(summary_rows)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Confirmatory H1/H2 evaluation from the immutable policy freeze."
    )
    parser.add_argument("--macropulse-root", default="../MacroPulse")
    parser.add_argument("--paper-root", default=".")
    args = parser.parse_args()

    paper_root = Path(args.paper_root).resolve()
    macro_root = Path(args.macropulse_root).resolve()
    db_path = macro_root / "data" / "macropulse.duckdb"
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    print("=" * 92)
    print("CONFIRMATORY H1/H2 EVALUATION")
    print("=" * 92)
    print(f"Canonical freeze commit: {FREEZE_COMMIT}")
    manifest = verify_freeze(paper_root)
    print("FREEZE VERIFICATION: PASS")
    print(f"Development input SHA256: {manifest['development_input_sha256']}")
    preanalysis_commit, analysis_script_sha256 = verify_analysis_script_committed(paper_root)
    print(f"PRE-ANALYSIS CODE COMMIT: {preanalysis_commit}")
    print(f"ANALYSIS SCRIPT SHA256: {analysis_script_sha256}")

    stage_policy, fixed = load_freeze_tables(paper_root)
    con = duckdb.connect(str(db_path), read_only=True)
    evaluation = load_evaluation_rows(con, stage_policy, fixed)
    validate_evaluation_rows(evaluation)

    h1_detail, h1_summary = build_h1(evaluation, fixed)
    h2_detail, h2_summary = build_h2(evaluation, stage_policy, fixed)

    out = paper_root / "outputs" / "confirmatory"
    h1_detail_path = out / "h1_information_gain_detail.csv"
    h1_summary_path = out / "h1_information_gain_summary.csv"
    h2_detail_path = out / "h2_stage_policy_detail.csv"
    h2_summary_path = out / "h2_stage_policy_summary.csv"

    write_csv(h1_detail, h1_detail_path)
    write_csv(h1_summary, h1_summary_path)
    write_csv(h2_detail, h2_detail_path)
    write_csv(h2_summary, h2_summary_path)

    audit = {
        "canonical_freeze_commit": FREEZE_COMMIT,
        "preanalysis_code_commit": preanalysis_commit,
        "analysis_script_sha256": analysis_script_sha256,
        "freeze_manifest_sha256": sha256_file(
            paper_root / "freeze" / "research_policy_freeze_manifest.json"
        ),
        "source_backtest_ids": {
            "GDP": GDP_BACKTEST,
            "Inflation": INFLATION_BACKTEST,
            "Labour": LABOUR_BACKTEST,
        },
        "evaluation_start": EVALUATION_START,
        "paper_error_convention": "actual - point_forecast",
        "primary_loss": "squared error",
        "secondary_loss": "absolute error",
        "inference": "Newey-West HAC mean-loss-differential test with Bartlett kernel and bandwidth floor(4*(n/100)^(2/9))",
        "h1_rule": (
            "same frozen fixed model; adjacent stages only; include only "
            "pairs with changed information_set_hash"
        ),
        "h2_rule": (
            "frozen development-selected stage policy versus frozen target-specific "
            "fixed comparator at identical target/stage/information set"
        ),
        "output_hashes": {
            h1_detail_path.name: sha256_file(h1_detail_path),
            h1_summary_path.name: sha256_file(h1_summary_path),
            h2_detail_path.name: sha256_file(h2_detail_path),
            h2_summary_path.name: sha256_file(h2_summary_path),
        },
        "row_counts": {
            "evaluation_source_rows": int(len(evaluation)),
            "h1_detail_rows_total": int(len(h1_detail)),
            "h1_detail_rows_eligible": int(h1_detail["eligible_h1"].sum()),
            "h1_same_hash_exclusions": int((h1_detail["eligible_h1"] == 0).sum()),
            "h2_detail_rows": int(len(h2_detail)),
        },
    }
    audit_path = out / "confirmatory_h1_h2_manifest.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 92)
    print("H1 — FIXED MODEL, CHANGING INFORMATION")
    print("Negative loss differential means the later information set improves accuracy.")
    print("=" * 92)
    print(
        h1_summary[
            [
                "domain_name",
                "target_series",
                "earlier_stage",
                "later_stage",
                "fixed_model",
                "eligible_pairs",
                "excluded_same_hash_pairs",
                "mean_delta_squared_error",
                "mean_delta_abs_error",
            ]
        ].to_string(index=False)
    )

    print()
    print("=" * 92)
    print("H2 — FROZEN STAGE POLICY VS FROZEN FIXED COMPARATOR")
    print("Negative loss differential means the stage-dependent policy is better.")
    print("=" * 92)
    print(
        h2_summary[
            [
                "domain_name",
                "target_series",
                "forecast_stage",
                "stage_policy_model",
                "fixed_model",
                "n",
                "same_model",
                "mean_delta_squared_error",
                "mean_delta_abs_error",
            ]
        ].to_string(index=False)
    )

    print()
    print("=" * 92)
    print("CONFIRMATORY OUTPUT HASHES")
    print("=" * 92)
    for name, digest in audit["output_hashes"].items():
        print(f"{name}: {digest}")
    print(f"Manifest: {audit_path}")

    print()
    print("=" * 92)
    print("CONFIRMATORY H1/H2 EVALUATION COMPLETED SUCCESSFULLY")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
