from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROBUSTNESS_FREEZE_COMMIT = "f9800620ea451ebfef20eaf05042e1623dad1031"
ROBUSTNESS_FREEZE_SHA256 = "c67fa3f3d6d318ef87448bed0ccca538200cb18c77ee27a5d0046535bd530980"
POLICY_FREEZE_COMMIT = "420feaeb51dca3abc79e9426aacca3816fe6ad5a"
MACROPULSE_SOURCE_COMMIT = "c4f357e463354f72eabead3dbc7f3b14ae71bec5"

GDP_BACKTEST = "382b4c6b-ef76-4ca1-b52f-d5e3e1ac66b1"
INFLATION_BACKTEST = "fdd2f573-a425-4abc-8056-f9843955bac2"
LABOUR_BACKTEST = "834e0655-ba81-4b96-b42c-e1cdda73b847"

TIE_TOL = 1e-12
NOMINAL_COVERAGE = 0.80
ALPHA = 0.20

EVALUATION_START = {
    "GDP": "2023Q2",
    "Inflation": "2023-02",
    "Labour": "2023-02",
}
PRIMARY_DEVELOPMENT_END = {
    "GDP": "2022Q4",
    "Inflation": "2022-12",
    "Labour": "2022-12",
}
SHORT_DEVELOPMENT_END = {
    "GDP": "2022Q2",
    "Inflation": "2022-06",
    "Labour": "2022-06",
}
STAGES = {
    "GDP": [
        "early_quarter",
        "after_month_1",
        "after_month_2",
        "quarter_end",
        "pre_advance_release",
    ],
    "Inflation": ["month_open", "mid_month", "month_end", "pre_release"],
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
CANDIDATES = {
    "GDP": [
        "AR(1)",
        "Bridge Ridge",
        "Bridge–DFM Ensemble",
        "Dynamic Factor Model",
        "Rolling Bridge–DFM Ensemble",
    ],
    "Inflation": [
        "Inflation 12-Month Mean",
        "Inflation AR(1)",
        "Inflation Bridge Ridge",
        "Inflation Ridge-AR Ensemble",
    ],
    "Labour": [
        "Labour 12-Month Mean",
        "Labour AR(1)",
        "Labour Bridge Ridge",
        "Labour Equal-Weight Ensemble",
        "Labour Factor Ridge",
    ],
}
R4_VARIANTS = {
    "GDP": [
        {"variant": "short_window", "window": 12, "minimum": 12},
        {"variant": "long_window", "window": 32, "minimum": 12},
    ],
    "Inflation": [
        {"variant": "short_memory", "window": 48, "minimum": 24, "half_life": 12.0},
        {"variant": "long_memory", "window": 48, "minimum": 24, "half_life": 24.0},
    ],
    "Labour": [
        {"variant": "short_memory", "window": 48, "minimum": 24, "decay": 0.90},
        {"variant": "long_memory", "window": 48, "minimum": 24, "decay": 0.97},
    ],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_output(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT
    ).strip()


def git_show_bytes(repo: Path, commit: str, relpath: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{commit}:{relpath}"],
        stderr=subprocess.STDOUT,
    )


def require_commit(repo: Path, commit: str, label: str) -> None:
    rc = subprocess.call(
        ["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if rc != 0:
        raise RuntimeError(f"{label} commit unavailable: {commit}")


def require_ancestor(repo: Path, ancestor: str, descendant: str, label: str) -> None:
    rc = subprocess.call(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if rc != 0:
        raise RuntimeError(f"{label} {ancestor} is not an ancestor of {descendant}.")


def verify_committed_preanalysis(paper_root: Path, macro_root: Path) -> tuple[str, str, str]:
    head = git_output(paper_root, "rev-parse", "HEAD")
    dirty = git_output(paper_root, "status", "--porcelain")
    if dirty:
        raise RuntimeError(
            "Working tree must be clean before robustness analysis. Commit the exact "
            "pre-analysis package and remove any untracked files before running."
        )
    require_commit(paper_root, ROBUSTNESS_FREEZE_COMMIT, "Robustness freeze")
    require_ancestor(paper_root, ROBUSTNESS_FREEZE_COMMIT, head, "Robustness freeze")
    require_commit(paper_root, POLICY_FREEZE_COMMIT, "Research policy freeze")
    require_ancestor(paper_root, POLICY_FREEZE_COMMIT, head, "Research policy freeze")
    require_commit(macro_root, MACROPULSE_SOURCE_COMMIT, "Pinned MacroPulse source")

    freeze_rel = "freeze/robustness_design_freeze.json"
    freeze_path = paper_root / freeze_rel
    if not freeze_path.is_file():
        raise FileNotFoundError(freeze_path)
    if sha256_file(freeze_path) != ROBUSTNESS_FREEZE_SHA256:
        raise RuntimeError("Working robustness freeze SHA256 does not match the canonical freeze.")
    if sha256_bytes(git_show_bytes(paper_root, ROBUSTNESS_FREEZE_COMMIT, freeze_rel)) != ROBUSTNESS_FREEZE_SHA256:
        raise RuntimeError("Committed robustness freeze SHA256 does not match the canonical freeze.")

    script_rel = "python/11_robustness_sensitivity.py"
    audit_rel = "stata/11_robustness_sensitivity_audit.do"
    script_path = paper_root / script_rel
    audit_path = paper_root / audit_rel
    for rel, path, label in [
        (script_rel, script_path, "Python robustness analysis"),
        (audit_rel, audit_path, "Stata robustness audit"),
    ]:
        if not path.is_file():
            raise FileNotFoundError(path)
        committed = git_show_bytes(paper_root, head, rel)
        if committed != path.read_bytes():
            raise RuntimeError(f"Working {label} differs from committed HEAD.")

    return head, sha256_file(script_path), sha256_file(audit_path)


def verify_archived_outputs(paper_root: Path) -> dict[str, str]:
    out = paper_root / "outputs" / "confirmatory"
    manifests = [
        out / "confirmatory_h1_h2_manifest.json",
        out / "confirmatory_h3_manifest.json",
        out / "confirmatory_h4_manifest.json",
    ]
    verified: dict[str, str] = {}
    for manifest_path in manifests:
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest.get("output_hashes", {}).items():
            path = out / name
            if not path.is_file():
                raise FileNotFoundError(path)
            actual = sha256_file(path)
            if actual != expected:
                raise RuntimeError(
                    f"Archived confirmatory artifact changed: {name}; expected={expected} actual={actual}"
                )
            verified[name] = actual
    return verified


def verify_policy_freeze_inputs(paper_root: Path) -> dict:
    manifest_path = paper_root / "freeze" / "research_policy_freeze_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for group, base in [
        ("freeze_files", paper_root / "freeze"),
        ("diagnostic_development_files", paper_root / "outputs" / "tables"),
    ]:
        for name, expected in manifest.get(group, {}).items():
            path = base / name
            if sha256_file(path) != expected:
                raise RuntimeError(f"Frozen policy artifact hash mismatch: {path}")
    return manifest


def sql_list(values: list[str]) -> str:
    return ",".join("'" + x.replace("'", "''") + "'" for x in values)


def period_ord(domain: str, value: str) -> int:
    return int(pd.Period(str(value), freq="Q" if domain == "GDP" else "M").ordinal)


def period_le(domain: str, value: str, cutoff: str) -> bool:
    return period_ord(domain, value) <= period_ord(domain, cutoff)


def period_ge(domain: str, value: str, cutoff: str) -> bool:
    return period_ord(domain, value) >= period_ord(domain, cutoff)


def load_candidate_rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    gdp = con.execute(
        f"""
        SELECT 'GDP' domain_name, 'GDPC1' target_series, target_period,
               forecast_stage, forecast_date, actual_release_date, model_name,
               point_forecast, actual, information_set_hash
        FROM stage_backtest_results
        WHERE stage_backtest_id = ?
          AND model_name IN ({sql_list(CANDIDATES['GDP'])})
        """,
        [GDP_BACKTEST],
    ).fetchdf()
    inf = con.execute(
        f"""
        SELECT 'Inflation' domain_name, target_series, target_period,
               forecast_stage, forecast_date, actual_release_date, model_name,
               point_forecast, actual, information_set_hash
        FROM inflation_vintage_backtest_results
        WHERE backtest_id = ?
          AND model_name IN ({sql_list(CANDIDATES['Inflation'])})
        """,
        [INFLATION_BACKTEST],
    ).fetchdf()
    lab = con.execute(
        f"""
        SELECT 'Labour' domain_name, target_series, target_period,
               forecast_stage, forecast_date, actual_release_date, model_name,
               point_forecast, actual, information_set_hash
        FROM labour_vintage_backtest_results
        WHERE backtest_id = ?
          AND model_name IN ({sql_list(CANDIDATES['Labour'])})
        """,
        [LABOUR_BACKTEST],
    ).fetchdf()
    frame = pd.concat([gdp, inf, lab], ignore_index=True)
    if frame.empty:
        raise RuntimeError("No candidate source rows loaded.")
    frame["target_period"] = frame["target_period"].astype(str)
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"], errors="coerce")
    frame["actual_release_date"] = pd.to_datetime(frame["actual_release_date"], errors="coerce")
    frame["point_forecast"] = pd.to_numeric(frame["point_forecast"], errors="coerce")
    frame["actual"] = pd.to_numeric(frame["actual"], errors="coerce")
    frame["error"] = frame["actual"] - frame["point_forecast"]
    frame["abs_error"] = frame["error"].abs()
    frame["squared_error"] = frame["error"] ** 2
    frame["_period_order"] = [
        period_ord(d, p) for d, p in zip(frame["domain_name"], frame["target_period"])
    ]
    key = ["domain_name", "target_series", "target_period", "forecast_stage", "model_name"]
    if frame.duplicated(key, keep=False).any():
        raise RuntimeError("Duplicate candidate source rows detected.")
    return frame


def common_sample(
    frame: pd.DataFrame, domain: str, target: str, stage: str, cutoff: str
) -> pd.DataFrame:
    candidates = CANDIDATES[domain]
    subset = frame.loc[
        (frame["domain_name"] == domain)
        & (frame["target_series"] == target)
        & (frame["forecast_stage"] == stage)
        & frame["model_name"].isin(candidates)
        & frame["target_period"].map(lambda x: period_le(domain, x, cutoff))
    ].copy()
    subset["valid"] = (
        np.isfinite(subset["actual"]) & np.isfinite(subset["point_forecast"])
    )
    origin = ["domain_name", "target_series", "target_period", "forecast_stage", "forecast_date"]
    grouped = subset.groupby(origin, dropna=False).agg(
        model_count=("model_name", "nunique"),
        row_count=("model_name", "size"),
        valid_count=("valid", "sum"),
        actual_min=("actual", "min"),
        actual_max=("actual", "max"),
    ).reset_index()
    ok = grouped.loc[
        (grouped["model_count"] == len(candidates))
        & (grouped["row_count"] == len(candidates))
        & (grouped["valid_count"] == len(candidates))
        & ((grouped["actual_max"] - grouped["actual_min"]).abs() <= TIE_TOL),
        origin,
    ]
    if ok.empty:
        raise RuntimeError(f"No common sample for {domain}/{target}/{stage} through {cutoff}.")
    common = subset.merge(ok, on=origin, how="inner", validate="many_to_one")
    counts = common.groupby("model_name").size()
    if set(counts.index) != set(candidates) or counts.nunique() != 1:
        raise RuntimeError(f"Unbalanced candidate sample for {domain}/{target}/{stage}.")
    return common


def metrics_for(common: pd.DataFrame) -> pd.DataFrame:
    m = common.groupby("model_name", as_index=False).agg(
        n=("squared_error", "size"),
        mse=("squared_error", "mean"),
        mae=("abs_error", "mean"),
    )
    return m.sort_values(["mse", "mae", "model_name"], kind="mergesort").reset_index(drop=True)


def select_winner(metrics: pd.DataFrame) -> str:
    min_mse = float(metrics["mse"].min())
    x = metrics.loc[(metrics["mse"] - min_mse).abs() <= TIE_TOL].copy()
    min_mae = float(x["mae"].min())
    x = x.loc[(x["mae"] - min_mae).abs() <= TIE_TOL].copy()
    return str(x.sort_values("model_name", kind="mergesort").iloc[0]["model_name"])


def build_short_policy(frame: pd.DataFrame, primary_stage: pd.DataFrame, primary_fixed: pd.DataFrame):
    stage_rows = []
    fixed_rows = []
    for domain in ("GDP", "Inflation", "Labour"):
        cutoff = SHORT_DEVELOPMENT_END[domain]
        for target in TARGETS[domain]:
            pooled = []
            for order, stage in enumerate(STAGES[domain], 1):
                common = common_sample(frame, domain, target, stage, cutoff)
                pooled.append(common)
                m = metrics_for(common)
                winner = select_winner(m)
                w = m.loc[m["model_name"] == winner].iloc[0]
                primary = primary_stage.loc[
                    (primary_stage["domain_name"] == domain)
                    & (primary_stage["target_series"] == target)
                    & (primary_stage["forecast_stage"] == stage),
                    "selected_model",
                ].iloc[0]
                stage_rows.append({
                    "domain_name": domain,
                    "target_series": target,
                    "stage_order": order,
                    "forecast_stage": stage,
                    "selected_model": winner,
                    "development_end": cutoff,
                    "development_n": int(w["n"]),
                    "development_mse": float(w["mse"]),
                    "development_mae": float(w["mae"]),
                    "primary_selected_model": str(primary),
                    "mapping_changed": int(winner != str(primary)),
                })
            pooled_df = pd.concat(pooled, ignore_index=True)
            m = metrics_for(pooled_df)
            winner = select_winner(m)
            w = m.loc[m["model_name"] == winner].iloc[0]
            primary = primary_fixed.loc[
                (primary_fixed["domain_name"] == domain)
                & (primary_fixed["target_series"] == target),
                "selected_model",
            ].iloc[0]
            fixed_rows.append({
                "domain_name": domain,
                "target_series": target,
                "selected_model": winner,
                "development_end": cutoff,
                "development_n": int(w["n"]),
                "development_mse": float(w["mse"]),
                "development_mae": float(w["mae"]),
                "primary_selected_model": str(primary),
                "mapping_changed": int(winner != str(primary)),
            })
    return pd.DataFrame(stage_rows), pd.DataFrame(fixed_rows)


def choose_runner_up_models(
    paper_root: Path, primary_fixed: pd.DataFrame
) -> pd.DataFrame:
    metrics = pd.read_csv(
        paper_root / "outputs" / "tables" / "research_fixed_candidate_development_metrics.csv"
    )
    rows = []
    for domain in ("GDP", "Inflation", "Labour"):
        for target in TARGETS[domain]:
            primary = str(primary_fixed.loc[
                (primary_fixed["domain_name"] == domain)
                & (primary_fixed["target_series"] == target),
                "selected_model",
            ].iloc[0])
            m = metrics.loc[
                (metrics["domain_name"] == domain)
                & (metrics["target_series"] == target)
                & (metrics["model_name"].astype(str) != primary)
            ].copy()
            if m.empty:
                raise RuntimeError(f"No runner-up candidate for {domain}/{target}.")
            m = m.sort_values(["mse", "mae", "model_name"], kind="mergesort")
            r = m.iloc[0]
            rows.append({
                "domain_name": domain,
                "target_series": target,
                "primary_fixed_model": primary,
                "alternative_fixed_model": str(r["model_name"]),
                "development_n": int(r["n"]),
                "development_mse": float(r["mse"]),
                "development_mae": float(r["mae"]),
                "selection_rule": "runner_up_pooled_development_MSE_then_MAE_then_model_name",
            })
    return pd.DataFrame(rows)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def paired_summary(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    n = len(x)
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win": np.nan, "bw": 0, "se": np.nan, "z": np.nan, "p": np.nan}
    mean = float(x.mean())
    med = float(np.median(x))
    win = float(np.mean(x < 0))
    if n >= 2:
        bw = min(max(int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))), 0), n - 1)
        u = x - mean
        lrv = float(np.dot(u, u) / n)
        for lag in range(1, bw + 1):
            gamma = float(np.dot(u[lag:], u[:-lag]) / n)
            lrv += 2 * (1 - lag / (bw + 1.0)) * gamma
        se = math.sqrt(max(lrv, 0.0) / n)
        z = mean / se if se > 0 else np.nan
        p = 2 * (1 - normal_cdf(abs(z))) if np.isfinite(z) else np.nan
    else:
        bw = 0
        se = z = p = np.nan
    return {"n": n, "mean": mean, "median": med, "win": win, "bw": bw, "se": se, "z": z, "p": p}


def evaluation_subset(frame: pd.DataFrame, domain: str, target: str, model: str) -> pd.DataFrame:
    return frame.loc[
        (frame["domain_name"] == domain)
        & (frame["target_series"] == target)
        & (frame["model_name"] == model)
        & frame["target_period"].map(lambda x: period_ge(domain, x, EVALUATION_START[domain]))
    ].copy()


def build_h1_alt(frame: pd.DataFrame, alt_models: pd.DataFrame):
    detail_rows = []
    summary_rows = []
    for rec in alt_models.itertuples(index=False):
        domain, target, model = rec.domain_name, rec.target_series, rec.alternative_fixed_model
        subset = evaluation_subset(frame, domain, target, model)
        for order in range(1, len(STAGES[domain])):
            earlier, later = STAGES[domain][order - 1], STAGES[domain][order]
            cols = ["target_period", "forecast_date", "actual", "point_forecast", "information_set_hash", "squared_error", "abs_error"]
            a = subset.loc[subset["forecast_stage"] == earlier, cols]
            b = subset.loc[subset["forecast_stage"] == later, cols]
            pair = a.merge(b, on="target_period", suffixes=("_earlier", "_later"), validate="one_to_one")
            if pair.empty:
                continue
            if not np.allclose(pair["actual_earlier"], pair["actual_later"], atol=1e-12, rtol=0):
                raise RuntimeError(f"R1 actual mismatch {domain}/{target}/{earlier}->{later}")
            pair["eligible"] = (
                pair["information_set_hash_earlier"].astype(str)
                != pair["information_set_hash_later"].astype(str)
            )
            pair["delta_squared_error"] = pair["squared_error_later"] - pair["squared_error_earlier"]
            pair["delta_abs_error"] = pair["abs_error_later"] - pair["abs_error_earlier"]
            for r in pair.itertuples(index=False):
                detail_rows.append({
                    "domain_name": domain, "target_series": target, "transition_order": order,
                    "earlier_stage": earlier, "later_stage": later, "target_period": r.target_period,
                    "alternative_fixed_model": model, "eligible_h1": int(r.eligible),
                    "actual": float(r.actual_earlier),
                    "earlier_point_forecast": float(r.point_forecast_earlier),
                    "later_point_forecast": float(r.point_forecast_later),
                    "delta_squared_error": float(r.delta_squared_error),
                    "delta_abs_error": float(r.delta_abs_error),
                })
            eligible = pair.loc[pair["eligible"]]
            sq, ae = paired_summary(eligible["delta_squared_error"]), paired_summary(eligible["delta_abs_error"])
            summary_rows.append({
                "domain_name": domain, "target_series": target, "transition_order": order,
                "earlier_stage": earlier, "later_stage": later, "alternative_fixed_model": model,
                "eligible_pairs": int(len(eligible)), "excluded_same_hash_pairs": int((~pair["eligible"]).sum()),
                "mean_delta_squared_error": sq["mean"], "median_delta_squared_error": sq["median"],
                "squared_error_improvement_share": sq["win"], "hac_bw_sq": sq["bw"],
                "hac_se_sq": sq["se"], "hac_z_sq": sq["z"], "hac_p_sq": sq["p"],
                "mean_delta_abs_error": ae["mean"], "median_delta_abs_error": ae["median"],
                "abs_error_improvement_share": ae["win"], "hac_bw_abs": ae["bw"],
                "hac_se_abs": ae["se"], "hac_z_abs": ae["z"], "hac_p_abs": ae["p"],
            })
    return pd.DataFrame(detail_rows), pd.DataFrame(summary_rows)


def build_h2_short(frame: pd.DataFrame, stage_policy: pd.DataFrame, fixed: pd.DataFrame):
    detail_rows = []
    summary_rows = []
    for domain in ("GDP", "Inflation", "Labour"):
        for target in TARGETS[domain]:
            fixed_model = str(fixed.loc[
                (fixed["domain_name"] == domain) & (fixed["target_series"] == target),
                "selected_model"
            ].iloc[0])
            for order, stage in enumerate(STAGES[domain], 1):
                stage_model = str(stage_policy.loc[
                    (stage_policy["domain_name"] == domain)
                    & (stage_policy["target_series"] == target)
                    & (stage_policy["forecast_stage"] == stage),
                    "selected_model"
                ].iloc[0])
                sf = evaluation_subset(frame, domain, target, stage_model)
                sf = sf.loc[sf["forecast_stage"] == stage]
                ff = evaluation_subset(frame, domain, target, fixed_model)
                ff = ff.loc[ff["forecast_stage"] == stage]
                if stage_model == fixed_model:
                    pair = sf.copy()
                    pair["delta_squared_error"] = 0.0
                    pair["delta_abs_error"] = 0.0
                    for r in pair.itertuples(index=False):
                        detail_rows.append({
                            "domain_name": domain, "target_series": target, "stage_order": order,
                            "forecast_stage": stage, "target_period": r.target_period,
                            "stage_policy_model": stage_model, "fixed_model": fixed_model,
                            "same_model": 1, "forecast_date": r.forecast_date,
                            "information_set_hash": r.information_set_hash, "actual": float(r.actual),
                            "stage_policy_point_forecast": float(r.point_forecast),
                            "fixed_point_forecast": float(r.point_forecast),
                            "delta_squared_error": 0.0, "delta_abs_error": 0.0,
                        })
                else:
                    cols = ["target_period", "forecast_date", "actual", "information_set_hash", "point_forecast", "squared_error", "abs_error"]
                    pair = sf[cols].merge(ff[cols], on="target_period", suffixes=("_policy", "_fixed"), validate="one_to_one")
                    if not bool((pair["forecast_date_policy"] == pair["forecast_date_fixed"]).all()):
                        raise RuntimeError(f"R2 forecast date mismatch {domain}/{target}/{stage}")
                    if not bool((pair["information_set_hash_policy"].astype(str) == pair["information_set_hash_fixed"].astype(str)).all()):
                        raise RuntimeError(f"R2 information hash mismatch {domain}/{target}/{stage}")
                    if not np.allclose(pair["actual_policy"], pair["actual_fixed"], atol=1e-12, rtol=0):
                        raise RuntimeError(f"R2 actual mismatch {domain}/{target}/{stage}")
                    pair["delta_squared_error"] = pair["squared_error_policy"] - pair["squared_error_fixed"]
                    pair["delta_abs_error"] = pair["abs_error_policy"] - pair["abs_error_fixed"]
                    for r in pair.itertuples(index=False):
                        detail_rows.append({
                            "domain_name": domain, "target_series": target, "stage_order": order,
                            "forecast_stage": stage, "target_period": r.target_period,
                            "stage_policy_model": stage_model, "fixed_model": fixed_model,
                            "same_model": 0, "forecast_date": r.forecast_date_policy,
                            "information_set_hash": r.information_set_hash_policy, "actual": float(r.actual_policy),
                            "stage_policy_point_forecast": float(r.point_forecast_policy),
                            "fixed_point_forecast": float(r.point_forecast_fixed),
                            "delta_squared_error": float(r.delta_squared_error),
                            "delta_abs_error": float(r.delta_abs_error),
                        })
                d = pd.DataFrame([x for x in detail_rows if x["domain_name"] == domain and x["target_series"] == target and x["forecast_stage"] == stage])
                sq, ae = paired_summary(d["delta_squared_error"]), paired_summary(d["delta_abs_error"])
                summary_rows.append({
                    "domain_name": domain, "target_series": target, "stage_order": order, "forecast_stage": stage,
                    "stage_policy_model": stage_model, "fixed_model": fixed_model,
                    "same_model": int(stage_model == fixed_model), "n": int(len(d)),
                    "mean_delta_squared_error": sq["mean"], "median_delta_squared_error": sq["median"],
                    "squared_error_policy_win_share": sq["win"], "hac_bw_sq": sq["bw"],
                    "hac_se_sq": sq["se"], "hac_z_sq": sq["z"], "hac_p_sq": sq["p"],
                    "mean_delta_abs_error": ae["mean"], "median_delta_abs_error": ae["median"],
                    "abs_error_policy_win_share": ae["win"], "hac_bw_abs": ae["bw"],
                    "hac_se_abs": ae["se"], "hac_z_abs": ae["z"], "hac_p_abs": ae["p"],
                })
    return pd.DataFrame(detail_rows), pd.DataFrame(summary_rows)


def add_primary_concordance(paper_root: Path, r1: pd.DataFrame, r2: pd.DataFrame):
    h1 = pd.read_csv(paper_root / "outputs/confirmatory/h1_information_gain_summary.csv")
    h1 = h1[[
        "domain_name", "target_series", "transition_order",
        "mean_delta_squared_error", "mean_delta_abs_error"
    ]].rename(columns={
        "mean_delta_squared_error": "primary_mean_delta_squared_error",
        "mean_delta_abs_error": "primary_mean_delta_abs_error",
    })
    r1 = r1.merge(h1, on=["domain_name", "target_series", "transition_order"], validate="one_to_one")
    r1["sq_sign_concordant_with_primary"] = (
        np.sign(r1["mean_delta_squared_error"]) == np.sign(r1["primary_mean_delta_squared_error"])
    ).astype(int)
    r1["abs_sign_concordant_with_primary"] = (
        np.sign(r1["mean_delta_abs_error"]) == np.sign(r1["primary_mean_delta_abs_error"])
    ).astype(int)

    h2 = pd.read_csv(paper_root / "outputs/confirmatory/h2_stage_policy_summary.csv")
    h2 = h2[[
        "domain_name", "target_series", "stage_order", "forecast_stage",
        "mean_delta_squared_error", "mean_delta_abs_error", "same_model"
    ]].rename(columns={
        "mean_delta_squared_error": "primary_mean_delta_squared_error",
        "mean_delta_abs_error": "primary_mean_delta_abs_error",
        "same_model": "primary_same_model",
    })
    r2 = r2.merge(
        h2, on=["domain_name", "target_series", "stage_order", "forecast_stage"],
        validate="one_to_one"
    )
    r2["sq_sign_concordant_with_primary"] = (
        np.sign(r2["mean_delta_squared_error"]) == np.sign(r2["primary_mean_delta_squared_error"])
    ).astype(int)
    r2["abs_sign_concordant_with_primary"] = (
        np.sign(r2["mean_delta_abs_error"]) == np.sign(r2["primary_mean_delta_abs_error"])
    ).astype(int)
    return r1, r2


def build_r3(paper_root: Path):
    stage = pd.read_csv(paper_root / "outputs/confirmatory/h3_vintage_summary.csv")
    stage["sq_latest_better"] = (stage["mean_delta_squared_error"] < 0).astype(int)
    stage["abs_latest_better"] = (stage["mean_delta_abs_error"] < 0).astype(int)
    rows = []
    for (domain, target), g in stage.groupby(["domain_name", "target_series"], sort=False):
        abs_sq = g["mean_delta_squared_error"].abs()
        abs_ae = g["mean_delta_abs_error"].abs()
        rows.append({
            "domain_name": domain, "target_series": target, "stage_count": int(len(g)),
            "sq_latest_better_stages": int(g["sq_latest_better"].sum()),
            "abs_latest_better_stages": int(g["abs_latest_better"].sum()),
            "sq_nominal_sig_stages": int((g["hac_p_sq"] < 0.05).sum()),
            "abs_nominal_sig_stages": int((g["hac_p_abs"] < 0.05).sum()),
            "largest_abs_stage_share_sq": float(abs_sq.max() / abs_sq.sum()) if abs_sq.sum() > 0 else np.nan,
            "largest_abs_stage_share_abs": float(abs_ae.max() / abs_ae.sum()) if abs_ae.sum() > 0 else np.nan,
            "all_sq_same_sign": int((g["sq_latest_better"].nunique() == 1)),
            "all_abs_same_sign": int((g["abs_latest_better"].nunique() == 1)),
        })
    return stage, pd.DataFrame(rows)


def higher_quantile(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q, method="higher"))


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values, kind="stable")
    v = values[order]
    w = weights[order]
    cum = np.cumsum(w)
    idx = int(np.searchsorted(cum, q * cum[-1], side="left"))
    return float(v[min(idx, len(v) - 1)])


def interval_score(actual: float, lower: float, upper: float) -> float:
    score = upper - lower
    if actual < lower:
        score += (2 / ALPHA) * (lower - actual)
    elif actual > upper:
        score += (2 / ALPHA) * (actual - upper)
    return float(score)


def wilson(successes: int, n: int, z: float = 1.959963984540054):
    p = successes / n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n))/denom
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))/denom
    return max(0.0, center-half), min(1.0, center+half)


def select_policy_rows(frame: pd.DataFrame, primary_stage: pd.DataFrame) -> pd.DataFrame:
    policy = primary_stage[["domain_name", "target_series", "stage_order", "forecast_stage", "selected_model"]]
    selected = frame.merge(policy, on=["domain_name", "target_series", "forecast_stage"], validate="many_to_one")
    selected = selected.loc[selected["model_name"].astype(str) == selected["selected_model"].astype(str)].copy()
    key = ["domain_name", "target_series", "target_period", "forecast_stage"]
    if selected.duplicated(key, keep=False).any():
        raise RuntimeError("Frozen policy produced duplicate source rows.")
    return selected


def variant_half_width(domain: str, errors: np.ndarray, spec: dict) -> float:
    a = np.abs(errors)
    if domain == "GDP":
        return max(0.0, higher_quantile(a, NOMINAL_COVERAGE))
    ages = np.arange(len(a) - 1, -1, -1, dtype=float)
    if domain == "Inflation":
        weights = np.power(0.5, ages / float(spec["half_life"]))
    else:
        weights = np.power(float(spec["decay"]), ages)
    return max(0.0, weighted_quantile(a, weights, NOMINAL_COVERAGE))


def build_r4(frame: pd.DataFrame, primary_stage: pd.DataFrame, paper_root: Path):
    selected = select_policy_rows(frame, primary_stage)
    current = selected.loc[
        [
            period_ge(d, p, EVALUATION_START[d])
            for d, p in zip(selected["domain_name"], selected["target_period"])
        ]
    ].copy()
    baseline = pd.read_csv(paper_root / "outputs/confirmatory/h4_interval_detail.csv")
    baseline = baseline.loc[baseline["is_primary"] == 1].copy()
    bkey = ["domain_name", "target_series", "forecast_stage", "target_period"]
    if len(baseline) != 1302:
        raise RuntimeError(f"Expected 1302 archived primary H4 rows, got {len(baseline)}.")

    rows = []
    for row in current.itertuples(index=False):
        domain = str(row.domain_name)
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
        prior = history.loc[valid].sort_values(
            ["actual_release_date", "_period_order", "forecast_date"]
        )
        for spec in R4_VARIANTS[domain]:
            window = prior.tail(int(spec["window"]))
            if len(window) < int(spec["minimum"]):
                raise RuntimeError(
                    f"R4 variant unexpectedly ineligible: {domain}/{row.target_series}/{row.forecast_stage}/{row.target_period}/{spec['variant']}"
                )
            hw = variant_half_width(domain, window["error"].to_numpy(float), spec)
            lower = float(row.point_forecast) - hw
            upper = float(row.point_forecast) + hw
            actual = float(row.actual)
            covered = int(lower <= actual <= upper)
            rows.append({
                "domain_name": domain, "target_series": str(row.target_series),
                "stage_order": int(row.stage_order), "forecast_stage": str(row.forecast_stage),
                "target_period": str(row.target_period), "selected_model": str(row.selected_model),
                "variant": spec["variant"], "forecast_date": pd.Timestamp(row.forecast_date).date().isoformat(),
                "actual_release_date": pd.Timestamp(row.actual_release_date).date().isoformat(),
                "point_forecast": float(row.point_forecast), "actual": actual,
                "prior_observable_error_count": int(len(prior)), "calibration_window_count": int(len(window)),
                "interval_half_width": hw, "lower_80": lower, "upper_80": upper,
                "interval_width": 2*hw, "interval_covered": covered,
                "violation": 1-covered, "interval_score": interval_score(actual, lower, upper),
            })
    detail = pd.DataFrame(rows)
    if len(detail) != 2604:
        raise RuntimeError(f"Expected 2604 R4 variant rows, got {len(detail)}.")

    summary_rows = []
    for keys, g in detail.groupby(
        ["domain_name", "target_series", "stage_order", "forecast_stage", "selected_model", "variant"],
        sort=False
    ):
        domain, target, order, stage, model, variant = keys
        covered = int(g["interval_covered"].sum())
        n = len(g)
        lo, hi = wilson(covered, n)
        summary_rows.append({
            "domain_name": domain, "target_series": target, "stage_order": int(order),
            "forecast_stage": stage, "selected_model": model, "variant": variant,
            "n": int(n), "covered": covered, "coverage": covered/n,
            "wilson_95_low": lo, "wilson_95_high": hi,
            "average_interval_width": float(g["interval_width"].mean()),
            "mean_interval_score": float(g["interval_score"].mean()),
        })
    summary = pd.DataFrame(summary_rows)

    merged = detail.merge(
        baseline[bkey + ["interval_score", "interval_width", "interval_covered"]].rename(columns={
            "interval_score": "primary_interval_score",
            "interval_width": "primary_interval_width",
            "interval_covered": "primary_interval_covered",
        }),
        on=bkey, validate="many_to_one"
    )
    merged["score_diff_variant_minus_primary"] = merged["interval_score"] - merged["primary_interval_score"]
    comp_rows = []
    for keys, g in merged.groupby(
        ["domain_name", "target_series", "stage_order", "forecast_stage", "selected_model", "variant"],
        sort=False
    ):
        domain, target, order, stage, model, variant = keys
        ps = paired_summary(g["score_diff_variant_minus_primary"])
        comp_rows.append({
            "domain_name": domain, "target_series": target, "stage_order": int(order),
            "forecast_stage": stage, "selected_model": model, "variant": variant,
            "n": int(ps["n"]), "mean_score_diff_variant_minus_primary": ps["mean"],
            "median_score_diff_variant_minus_primary": ps["median"],
            "hac_bw_score": ps["bw"], "hac_se_score": ps["se"], "hac_z_score": ps["z"],
            "hac_p_score_two_sided": ps["p"],
        })
    return detail, summary, pd.DataFrame(comp_rows)


def holm_adjust(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    out = np.full(len(p), np.nan)
    valid = np.where(np.isfinite(p))[0]
    if len(valid) == 0:
        return out
    order = valid[np.argsort(p[valid], kind="mergesort")]
    m = len(order)
    running = 0.0
    for rank, idx in enumerate(order, start=1):
        adj = min(1.0, (m - rank + 1) * p[idx])
        running = max(running, adj)
        out[idx] = running
    return out


def build_r5(paper_root: Path) -> pd.DataFrame:
    out = paper_root / "outputs/confirmatory"
    families = []

    h1 = pd.read_csv(out / "h1_information_gain_summary.csv")
    for name, col in [
        ("H1_squared_error", "hac_p_value_squared_error_two_sided"),
        ("H1_absolute_error", "hac_p_value_abs_error_two_sided"),
    ]:
        x = h1[["domain_name", "target_series", "transition_order", "earlier_stage", "later_stage", col]].copy()
        x["test_family"] = name
        x["raw_p"] = x[col]
        x["source"] = "h1_information_gain_summary.csv"
        families.append(x)

    h2 = pd.read_csv(out / "h2_stage_policy_summary.csv")
    h2 = h2.loc[h2["same_model"] == 0].copy()
    for name, col in [
        ("H2_squared_error_informative_cells", "hac_p_value_squared_error_two_sided"),
        ("H2_absolute_error_informative_cells", "hac_p_value_abs_error_two_sided"),
    ]:
        x = h2[["domain_name", "target_series", "stage_order", "forecast_stage", col]].copy()
        x["test_family"] = name
        x["raw_p"] = x[col]
        x["source"] = "h2_stage_policy_summary.csv"
        families.append(x)

    h3 = pd.read_csv(out / "h3_vintage_target_summary.csv")
    for name, col in [
        ("H3_target_squared_error", "hac_p_sq"),
        ("H3_target_absolute_error", "hac_p_abs"),
    ]:
        x = h3[["domain_name", "target_series", col]].copy()
        x["test_family"] = name
        x["raw_p"] = x[col]
        x["source"] = "h3_vintage_target_summary.csv"
        families.append(x)

    h4s = pd.read_csv(out / "h4_interval_summary.csv")
    x = h4s.loc[h4s["is_primary"] == 1, [
        "domain_name", "target_series", "stage_order", "forecast_stage", "p_uc"
    ]].copy()
    x["test_family"] = "H4_primary_unconditional_coverage"
    x["raw_p"] = x["p_uc"]
    x["source"] = "h4_interval_summary.csv"
    families.append(x)

    h4c = pd.read_csv(out / "h4_interval_method_comparisons.csv")
    for bench, name in [
        ("gaussian_rmse", "H4_primary_vs_gaussian_interval_score"),
        ("rolling_q80", "H4_primary_vs_rolling_interval_score"),
    ]:
        x = h4c.loc[h4c["benchmark_method"] == bench, [
            "domain_name", "target_series", "stage_order", "forecast_stage",
            "benchmark_method", "hac_p_score_two_sided"
        ]].copy()
        x["test_family"] = name
        x["raw_p"] = x["hac_p_score_two_sided"]
        x["source"] = "h4_interval_method_comparisons.csv"
        families.append(x)

    expected = {
        "H1_squared_error": 28,
        "H1_absolute_error": 28,
        "H2_squared_error_informative_cells": 11,
        "H2_absolute_error_informative_cells": 11,
        "H3_target_squared_error": 8,
        "H3_target_absolute_error": 8,
        "H4_primary_unconditional_coverage": 36,
        "H4_primary_vs_gaussian_interval_score": 36,
        "H4_primary_vs_rolling_interval_score": 31,
    }
    tidy = pd.concat(families, ignore_index=True, sort=False)
    for family, n in expected.items():
        got = int((tidy["test_family"] == family).sum())
        if got != n:
            raise RuntimeError(f"R5 family count mismatch for {family}: expected {n}, got {got}")
    tidy["holm_p"] = np.nan
    for family, idx in tidy.groupby("test_family").groups.items():
        vals = tidy.loc[idx, "raw_p"].to_numpy(float)
        tidy.loc[idx, "holm_p"] = holm_adjust(vals)
    tidy["raw_sig_005"] = (tidy["raw_p"] < 0.05).astype(int)
    tidy["holm_sig_005"] = (tidy["holm_p"] < 0.05).astype(int)
    return tidy


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen post-confirmatory robustness analysis R1-R5.")
    parser.add_argument("--macropulse-root", default="../MacroPulse")
    parser.add_argument("--paper-root", default=".")
    args = parser.parse_args()

    paper_root = Path(args.paper_root).resolve()
    macro_root = Path(args.macropulse_root).resolve()
    db_path = macro_root / "data/macropulse.duckdb"
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    final_out = paper_root / "outputs/robustness"
    if final_out.exists():
        raise RuntimeError(f"{final_out} already exists; refusing to overwrite.")

    print("=" * 96)
    print("ROBUSTNESS AND SENSITIVITY ANALYSIS R1-R5")
    print("=" * 96)
    head, script_sha, audit_sha = verify_committed_preanalysis(paper_root, macro_root)
    print(f"PRE-ANALYSIS CODE COMMIT: {head}")
    print(f"PYTHON SCRIPT SHA256: {script_sha}")
    print(f"STATA AUDIT SHA256: {audit_sha}")
    archived = verify_archived_outputs(paper_root)
    policy_manifest = verify_policy_freeze_inputs(paper_root)
    print(f"CONFIRMATORY ARCHIVES VERIFIED: {len(archived)} files")
    print(f"ROBUSTNESS FREEZE SHA256: {ROBUSTNESS_FREEZE_SHA256}")

    con = duckdb.connect(str(db_path), read_only=True)
    source = load_candidate_rows(con)
    primary_stage = pd.read_csv(paper_root / "freeze/research_stage_policy_freeze.csv")
    primary_fixed = pd.read_csv(paper_root / "freeze/research_fixed_comparator_freeze.csv")

    # R1
    r1_models = choose_runner_up_models(paper_root, primary_fixed)
    r1_detail, r1_summary = build_h1_alt(source, r1_models)

    # R2
    r2_stage, r2_fixed = build_short_policy(source, primary_stage, primary_fixed)
    r2_detail, r2_summary = build_h2_short(source, r2_stage, r2_fixed)
    r1_summary, r2_summary = add_primary_concordance(paper_root, r1_summary, r2_summary)

    # R3: archived H3 only
    r3_stage, r3_target = build_r3(paper_root)

    # R4
    r4_detail, r4_summary, r4_comp = build_r4(source, primary_stage, paper_root)

    # R5
    r5 = build_r5(paper_root)

    tmp_parent = paper_root / "outputs"
    tmp = Path(tempfile.mkdtemp(prefix="robustness_tmp_", dir=str(tmp_parent)))
    try:
        outputs = {
            "r1_alternative_fixed_models.csv": r1_models,
            "r1_h1_alternative_fixed_detail.csv": r1_detail,
            "r1_h1_alternative_fixed_summary.csv": r1_summary,
            "r2_shortdev_stage_policy.csv": r2_stage,
            "r2_shortdev_fixed_comparator.csv": r2_fixed,
            "r2_h2_shortdev_detail.csv": r2_detail,
            "r2_h2_shortdev_summary.csv": r2_summary,
            "r3_h3_stage_heterogeneity.csv": r3_stage,
            "r3_h3_target_stage_concordance.csv": r3_target,
            "r4_h4_memory_detail.csv": r4_detail,
            "r4_h4_memory_summary.csv": r4_summary,
            "r4_h4_memory_comparisons.csv": r4_comp,
            "r5_holm_adjusted_pvalues.csv": r5,
        }
        for name, frame in outputs.items():
            write_csv(frame, tmp / name)

        manifest = {
            "analysis": "post-confirmatory robustness R1-R5",
            "preanalysis_code_commit": head,
            "robustness_freeze_commit": ROBUSTNESS_FREEZE_COMMIT,
            "robustness_freeze_sha256": ROBUSTNESS_FREEZE_SHA256,
            "policy_freeze_commit": POLICY_FREEZE_COMMIT,
            "macropulse_source_commit": MACROPULSE_SOURCE_COMMIT,
            "python_script_sha256": script_sha,
            "stata_audit_sha256": audit_sha,
            "confirmatory_artifacts_verified": archived,
            "policy_development_input_sha256": policy_manifest["development_input_sha256"],
            "output_hashes": {name: sha256_file(tmp / name) for name in outputs},
            "row_counts": {name: int(len(frame)) for name, frame in outputs.items()},
            "r1_rule": "runner-up pooled development MSE model; unchanged confirmatory evaluation; adjacent stage changed-hash pairs",
            "r2_rule": "shortened development end GDP 2022Q2, Inflation/Labour 2022-06; original selection rules; unchanged evaluation",
            "r3_rule": "archived H3 stage summary only; no H3 regeneration",
            "r4_rule": "frozen H4 availability gate and selected model; predefined short/long memory variants",
            "r5_rule": "Holm step-down within the nine predeclared test families; primary raw confirmatory inference remains unchanged",
        }
        (tmp / "robustness_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        final_out.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(final_out)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    print()
    print("=" * 96)
    print("R1 SUMMARY")
    print("=" * 96)
    print(r1_summary[[
        "domain_name", "target_series", "earlier_stage", "later_stage",
        "alternative_fixed_model", "mean_delta_squared_error", "hac_p_sq",
        "sq_sign_concordant_with_primary"
    ]].to_string(index=False))

    print()
    print("=" * 96)
    print("R2 POLICY MAPPING CHANGES")
    print("=" * 96)
    print(f"Stage-policy changes: {int(r2_stage['mapping_changed'].sum())} / {len(r2_stage)}")
    print(f"Fixed-comparator changes: {int(r2_fixed['mapping_changed'].sum())} / {len(r2_fixed)}")
    print(r2_summary.loc[r2_summary["same_model"] == 0, [
        "domain_name", "target_series", "forecast_stage", "stage_policy_model",
        "fixed_model", "mean_delta_squared_error", "hac_p_sq",
        "sq_sign_concordant_with_primary"
    ]].to_string(index=False))

    print()
    print("=" * 96)
    print("R3 TARGET STAGE-CONCORDANCE")
    print("=" * 96)
    print(r3_target.to_string(index=False))

    print()
    print("=" * 96)
    print("R4 MEMORY SENSITIVITY")
    print("=" * 96)
    print(r4_comp[[
        "domain_name", "target_series", "forecast_stage", "variant",
        "mean_score_diff_variant_minus_primary", "hac_p_score_two_sided"
    ]].to_string(index=False))

    print()
    print("=" * 96)
    print("R5 HOLM SURVIVORS")
    print("=" * 96)
    print(
        r5.groupby("test_family", as_index=False).agg(
            tests=("raw_p", "size"),
            raw_sig_005=("raw_sig_005", "sum"),
            holm_sig_005=("holm_sig_005", "sum"),
        ).to_string(index=False)
    )

    print()
    print("=" * 96)
    print("ROBUSTNESS OUTPUT HASHES")
    print("=" * 96)
    manifest = json.loads((final_out / "robustness_manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["output_hashes"].items():
        print(f"{name}: {digest}")
    print(f"Manifest: {final_out / 'robustness_manifest.json'}")
    print()
    print("ROBUSTNESS R1-R5 COMPLETED SUCCESSFULLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
