from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

POLICY_FREEZE_COMMIT = "420feaeb51dca3abc79e9426aacca3816fe6ad5a"
H3_INPUT_COMMIT = "6e6c6464d930c0782dbd998b551fad2eaf42c7ec"
ORIGINAL_H3_PREANALYSIS_COMMIT = "275797fd3109140737bf1095edc968252a18b925"
MACROPULSE_SOURCE_COMMIT = "c4f357e463354f72eabead3dbc7f3b14ae71bec5"

FROZEN_LATEST_SHA256 = "1f418a21ed774796da4e4426f3270340d296ecca571b205c98b24d81be1346af"
FROZEN_MANIFEST_SHA256 = "fd6bbf7f94cc41ef2c88b913ea061f33571959c635dd19db87dc41dcde196bf0"
FROZEN_STAGE_POLICY_SHA256 = "e243be0c4a02ea73e95da274436d280dcc12b7b137bef56b8cb2074e96a75964"

GDP_BACKTEST = "382b4c6b-ef76-4ca1-b52f-d5e3e1ac66b1"
INFLATION_BACKTEST = "fdd2f573-a425-4abc-8056-f9843955bac2"
LABOUR_BACKTEST = "834e0655-ba81-4b96-b42c-e1cdda73b847"

EVALUATION_START = {
    "GDP": pd.Period("2023Q2", freq="Q"),
    "Inflation": pd.Period("2023-02", freq="M"),
    "Labour": pd.Period("2023-02", freq="M"),
}

STAGES = {
    "GDP": ["early_quarter", "after_month_1", "after_month_2", "quarter_end", "pre_advance_release"],
    "Inflation": ["month_open", "mid_month", "month_end", "pre_release"],
    "Labour": ["month_open", "after_week_1", "after_week_2", "month_end", "pre_employment_report"],
}

TARGETS = {
    "GDP": ["GDPC1"],
    "Inflation": ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"],
    "Labour": ["CES0500000003", "PAYEMS", "UNRATE"],
}

RT_REPRO_TOL = 1e-6
ATOL = 1e-12


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_show_bytes(repo: Path, commit: str, relpath: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{relpath}"], stderr=subprocess.STDOUT)


def require_commit(repo: Path, commit: str) -> None:
    code = subprocess.call(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if code != 0:
        raise RuntimeError(f"Required commit {commit} is unavailable in {repo}.")


def verify_preanalysis_boundaries(paper_root: Path, macro_root: Path) -> tuple[str, str]:
    for commit in (POLICY_FREEZE_COMMIT, H3_INPUT_COMMIT, ORIGINAL_H3_PREANALYSIS_COMMIT):
        require_commit(paper_root, commit)
    require_commit(macro_root, MACROPULSE_SOURCE_COMMIT)

    head = subprocess.check_output(["git", "-C", str(paper_root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.call(["git", "-C", str(paper_root), "merge-base", "--is-ancestor", H3_INPUT_COMMIT, head], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise RuntimeError("H3 input freeze is not an ancestor of the current paper HEAD.")
    if subprocess.call(["git", "-C", str(paper_root), "merge-base", "--is-ancestor", ORIGINAL_H3_PREANALYSIS_COMMIT, head], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        raise RuntimeError("Original H3 preanalysis commit is not an ancestor of the current paper HEAD.")

    relpath = "python/09_confirmatory_h3_vintage.py"
    script_path = paper_root / relpath
    if not script_path.is_file():
        raise FileNotFoundError(script_path)
    try:
        committed = git_show_bytes(paper_root, head, relpath)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("H3 analysis script is not committed at HEAD.") from exc
    working = script_path.read_bytes()
    if committed != working:
        raise RuntimeError("Working H3 script differs from committed HEAD.")

    checks = [
        (paper_root / "data/raw/vintage/latest_vintage_extract.csv", FROZEN_LATEST_SHA256),
        (paper_root / "data/raw/vintage/latest_vintage_manifest.csv", FROZEN_MANIFEST_SHA256),
        (paper_root / "freeze/research_stage_policy_freeze.csv", FROZEN_STAGE_POLICY_SHA256),
    ]
    for path, expected in checks:
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"Working hash mismatch for {path}: expected={expected} actual={actual}")

    committed_checks = [
        (H3_INPUT_COMMIT, "data/raw/vintage/latest_vintage_extract.csv", FROZEN_LATEST_SHA256),
        (H3_INPUT_COMMIT, "data/raw/vintage/latest_vintage_manifest.csv", FROZEN_MANIFEST_SHA256),
        (POLICY_FREEZE_COMMIT, "freeze/research_stage_policy_freeze.csv", FROZEN_STAGE_POLICY_SHA256),
    ]
    for commit, rel, expected in committed_checks:
        actual = sha256_bytes(git_show_bytes(paper_root, commit, rel))
        if actual != expected:
            raise RuntimeError(f"Committed hash mismatch at {commit}:{rel}: expected={expected} actual={actual}")

    return head, sha256_bytes(working)


def extract_pinned_macropulse(macro_root: Path, destination: Path) -> None:
    archive = subprocess.check_output(
        ["git", "-C", str(macro_root), "archive", "--format=tar", MACROPULSE_SOURCE_COMMIT, "src/macropulse", "config"],
        stderr=subprocess.STDOUT,
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
        tf.extractall(destination)


def period_value(domain: str, value: str) -> pd.Period:
    return pd.Period(str(value), freq="Q" if domain == "GDP" else "M")


def is_evaluation(domain: str, value: str) -> bool:
    return period_value(domain, value) >= EVALUATION_START[domain]


def mask_hash(frame: pd.DataFrame) -> str:
    keys = frame[["series_id", "observation_date"]].copy()
    keys["observation_date"] = pd.to_datetime(keys["observation_date"]).dt.strftime("%Y-%m-%d")
    keys = keys.sort_values(["series_id", "observation_date"])
    payload = "\n".join(keys["series_id"].astype(str) + "|" + keys["observation_date"].astype(str))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_rt_snapshot(con: duckdb.DuckDBPyConnection, forecast_date, series_ids: list[str]) -> pd.DataFrame:
    placeholders = ",".join(["?"] * len(series_ids))
    frame = con.execute(
        f"""
        SELECT series_id, observation_date, value,
               as_of_date AS realtime_start, as_of_date AS realtime_end
        FROM historical_snapshots
        WHERE as_of_date = ? AND series_id IN ({placeholders})
        ORDER BY series_id, observation_date
        """,
        [pd.Timestamp(forecast_date).date(), *series_ids],
    ).fetchdf()
    if frame.empty:
        raise RuntimeError(f"Empty RT snapshot at {forecast_date}.")
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    frame["realtime_start"] = pd.to_datetime(frame["realtime_start"])
    frame["realtime_end"] = pd.to_datetime(frame["realtime_end"])
    if frame.duplicated(["series_id", "observation_date"]).any():
        raise RuntimeError(f"Duplicate RT series/date keys at {forecast_date}.")
    return frame


def make_lv_snapshot(rt: pd.DataFrame, frozen_latest: pd.DataFrame) -> tuple[pd.DataFrame, int, int, int]:
    merged = rt.merge(
        frozen_latest[["series_id", "observation_date", "value"]],
        on=["series_id", "observation_date"],
        how="left",
        suffixes=("_rt", "_lv"),
        indicator=True,
        validate="one_to_one",
    )
    comparable = (merged["_merge"] == "both") & merged["value_lv"].notna()
    merged["value_final"] = np.where(comparable, merged["value_lv"], merged["value_rt"])
    fallback_rows = int((~comparable).sum())
    equal = np.isclose(
        merged["value_rt"].to_numpy(dtype=float),
        merged["value_final"].to_numpy(dtype=float),
        atol=ATOL,
        rtol=0.0,
        equal_nan=True,
    )
    changed_rows = int((~equal).sum())
    final_missing = int(pd.isna(merged["value_final"]).sum())
    lv = rt.copy()
    lv["value"] = merged["value_final"].to_numpy()
    if mask_hash(lv) != mask_hash(rt):
        raise RuntimeError("LV/RT mask invariant failed.")
    return lv, fallback_rows, changed_rows, final_missing


def close_enough(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= RT_REPRO_TOL * max(1.0, abs(float(a)), abs(float(b)))


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def paired_summary(diff: pd.Series) -> dict:
    x = pd.to_numeric(diff, errors="coerce").dropna().to_numpy(dtype=float)
    n = int(len(x))
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win_share": np.nan, "hac_bw": 0, "hac_se": np.nan, "hac_z": np.nan, "hac_p": np.nan}
    mean = float(np.mean(x))
    median = float(np.median(x))
    win_share = float(np.mean(x < 0))
    if n >= 2:
        bw = min(max(int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))), 0), n - 1)
        u = x - mean
        lrv = float(np.dot(u, u) / n)
        for lag in range(1, bw + 1):
            gamma_l = float(np.dot(u[lag:], u[:-lag]) / n)
            lrv += 2.0 * (1.0 - lag / (bw + 1.0)) * gamma_l
        lrv = max(lrv, 0.0)
        se = math.sqrt(lrv / n)
        z = mean / se if se > 0 else np.nan
        p = 2.0 * (1.0 - normal_cdf(abs(z))) if np.isfinite(z) else np.nan
    else:
        bw = 0
        se = z = p = np.nan
    return {"n": n, "mean": mean, "median": median, "win_share": win_share, "hac_bw": bw, "hac_se": se, "hac_z": z, "hac_p": p}


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def load_source_rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    gdp = con.execute(
        """SELECT 'GDP' domain_name, 'GDPC1' target_series, target_period,
                  forecast_stage, forecast_date, model_name, point_forecast,
                  actual, information_set_hash
           FROM stage_backtest_results WHERE stage_backtest_id = ?""",
        [GDP_BACKTEST],
    ).fetchdf()
    inf = con.execute(
        """SELECT 'Inflation' domain_name, target_series, target_period,
                  forecast_stage, forecast_date, model_name, point_forecast,
                  actual, information_set_hash
           FROM inflation_vintage_backtest_results WHERE backtest_id = ?""",
        [INFLATION_BACKTEST],
    ).fetchdf()
    lab = con.execute(
        """SELECT 'Labour' domain_name, target_series, target_period,
                  forecast_stage, forecast_date, model_name, point_forecast,
                  actual, information_set_hash
           FROM labour_vintage_backtest_results WHERE backtest_id = ?""",
        [LABOUR_BACKTEST],
    ).fetchdf()
    frame = pd.concat([gdp, inf, lab], ignore_index=True)
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"])
    frame["point_forecast"] = pd.to_numeric(frame["point_forecast"], errors="raise")
    frame["actual"] = pd.to_numeric(frame["actual"], errors="raise")
    key = ["domain_name", "target_series", "target_period", "forecast_stage", "model_name"]
    if frame.duplicated(key).any():
        raise RuntimeError("Duplicate source backtest rows detected.")
    origin = ["domain_name", "target_series", "target_period", "forecast_stage"]
    audit = frame.groupby(origin, dropna=False).agg(
        actual_min=("actual", "min"), actual_max=("actual", "max"),
        forecast_dates=("forecast_date", "nunique"), info_hashes=("information_set_hash", "nunique")
    ).reset_index()
    if not np.allclose(audit["actual_min"], audit["actual_max"], atol=ATOL, rtol=0.0):
        raise RuntimeError("Source candidate rows do not share a common actual.")
    if (audit["forecast_dates"] != 1).any() or (audit["info_hashes"] != 1).any():
        raise RuntimeError("Source candidate rows disagree on cutoff or information hash.")
    return frame


def stored_row(source, domain, target, target_period, stage, model_name) -> pd.Series:
    rows = source.loc[
        (source.domain_name == domain) & (source.target_series == target)
        & (source.target_period.astype(str) == str(target_period))
        & (source.forecast_stage == stage) & (source.model_name == model_name)
    ]
    if len(rows) != 1:
        raise RuntimeError(f"Expected one source row for {domain}/{target}/{target_period}/{stage}/{model_name}; found {len(rows)}")
    return rows.iloc[0]


def origin_rows(source, domain, target) -> pd.DataFrame:
    cols = ["domain_name", "target_series", "target_period", "forecast_stage", "forecast_date", "actual", "information_set_hash"]
    return source.loc[(source.domain_name == domain) & (source.target_series == target), cols].drop_duplicates().copy()


def make_detail(**k) -> dict:
    rt_error = float(k["actual"] - k["rt_point"])
    lv_error = float(k["actual"] - k["lv_point"])
    return {
        "domain_name": k["domain"], "target_series": k["target"], "stage_order": int(k["stage_order"]),
        "forecast_stage": k["stage"], "target_period": str(k["target_period"]),
        "forecast_date": pd.Timestamp(k["forecast_date"]).date(), "selected_model": k["selected_model"],
        "actual": float(k["actual"]), "rt_point_forecast": float(k["rt_point"]), "lv_point_forecast": float(k["lv_point"]),
        "forecast_revision": float(k["lv_point"] - k["rt_point"]),
        "rt_error": rt_error, "lv_error": lv_error,
        "rt_squared_error": rt_error**2, "lv_squared_error": lv_error**2,
        "delta_squared_error": lv_error**2 - rt_error**2,
        "rt_abs_error": abs(rt_error), "lv_abs_error": abs(lv_error), "delta_abs_error": abs(lv_error) - abs(rt_error),
        "rt_info_hash": k["snap"]["rt_hash"], "lv_info_hash": k["snap"]["lv_hash"],
        "rt_mask_hash": k["snap"]["rt_mask_hash"], "lv_mask_hash": k["snap"]["lv_mask_hash"],
        "mask_equal": int(k["snap"]["rt_mask_hash"] == k["snap"]["lv_mask_hash"]), "rt_hash_verified": 1,
        "raw_changed_rows": int(k["snap"]["changed"]), "raw_fallback_rows": int(k["snap"]["fallback"]),
        "final_missing_values": int(k["snap"]["final_missing"]),
        "rolling_rt_repro_gap": k.get("rolling_rt_repro_gap"),
        "rolling_rt_w_bridge": k.get("rolling_rt_w_bridge"), "rolling_lv_w_bridge": k.get("rolling_lv_w_bridge"),
    }


def run_h3(con, source, stage_policy, frozen_latest, M) -> pd.DataFrame:
    gdp_defs = M["get_series_definitions"]()
    inf_defs = M["get_inflation_series_definitions"]()
    lab_defs = M["get_labour_series_definitions"]()
    series = {
        "GDP": [x.series_id for x in gdp_defs],
        "Inflation": [x.series_id for x in inf_defs],
        "Labour": [x.series_id for x in lab_defs],
    }
    frozen_domain = {d: frozen_latest.loc[frozen_latest.series_id.isin(ids)].copy() for d, ids in series.items()}
    cache = {}

    def snapshots(domain, forecast_date, expected_hash):
        key = (domain, pd.Timestamp(forecast_date))
        if key not in cache:
            rt = load_rt_snapshot(con, forecast_date, series[domain])
            rt_hash = M["information_set_hash"](rt)
            lv, fallback, changed, final_missing = make_lv_snapshot(rt, frozen_domain[domain])
            cache[key] = {
                "rt": rt, "lv": lv, "rt_hash": rt_hash, "lv_hash": M["information_set_hash"](lv),
                "rt_mask_hash": mask_hash(rt), "lv_mask_hash": mask_hash(lv),
                "fallback": fallback, "changed": changed, "final_missing": final_missing,
            }
        out = cache[key]
        if str(out["rt_hash"]) != str(expected_hash):
            raise RuntimeError(f"RT information-set hash mismatch for {domain} at {pd.Timestamp(forecast_date).date()}: stored={expected_hash} reconstructed={out['rt_hash']}")
        if out["rt_mask_hash"] != out["lv_mask_hash"] or out["final_missing"] != 0:
            raise RuntimeError("H3 mask/final-missing invariant failed.")
        return out

    pol = stage_policy.set_index(["domain_name", "target_series", "forecast_stage"])["selected_model"].to_dict()
    order = stage_policy.set_index(["domain_name", "target_series", "forecast_stage"])["stage_order"].to_dict()
    rows = []

    registry = M["load_registry"]()
    gdp_alpha = float(registry["model"].get("ridge_alpha", 10.0))
    gdp_interval = float(registry["model"].get("prediction_interval", 0.80))
    dfm_cfg = registry.get("dynamic_factor", {})

    def fit_gdp(snapshot, target_period, forecast_date):
        p = pd.Period(str(target_period), freq="Q")
        cutoff = pd.Timestamp(forecast_date)
        bds = M["build_bridge_dataset"](observations=snapshot, definitions=gdp_defs, target_series="GDPC1", target_period=p, data_as_of=cutoff)
        bridge = M["fit_gdp_bridge"](bds.training_frame, bds.current_features, alpha=gdp_alpha, interval=gdp_interval)
        mds = M["build_mixed_frequency_dataset"](observations=snapshot, definitions=gdp_defs, target_series="GDPC1", target_period=p, data_as_of=cutoff)
        dfm = M["fit_dynamic_factor"](
            dataset=mds, interval=gdp_interval, factors=int(dfm_cfg.get("factors", 1)),
            factor_orders=int(dfm_cfg.get("factor_orders", 1)), idiosyncratic_ar1=bool(dfm_cfg.get("idiosyncratic_ar1", True)),
            maxiter=int(dfm_cfg.get("maxiter", 100)), tolerance=float(dfm_cfg.get("tolerance", 1e-4)),
            require_convergence=bool(dfm_cfg.get("require_convergence", False)),
        )
        fixed = M["combine_weighted"]([bridge, dfm], {"Bridge Ridge": 0.5, "Dynamic Factor Model": 0.5}, model_name="Bridge–DFM Ensemble", interval=gdp_interval, diagnostics={"weight_method": "equal"})
        return bridge, dfm, fixed

    # GDP quarter-end recursive path.
    qend = origin_rows(source, "GDP", "GDPC1")
    qend = qend.loc[qend.forecast_stage == "quarter_end"].copy()
    qend["_p"] = qend.target_period.map(lambda x: pd.Period(str(x), freq="Q"))
    qend = qend.sort_values("_p")
    rt_hist, lv_hist = [], []
    for rec in qend.itertuples(index=False):
        tp = str(rec.target_period)
        snap = snapshots("GDP", rec.forecast_date, str(rec.information_set_hash))
        rt_b = stored_row(source, "GDP", "GDPC1", tp, "quarter_end", "Bridge Ridge")
        rt_d = stored_row(source, "GDP", "GDPC1", tp, "quarter_end", "Dynamic Factor Model")
        rt_r = stored_row(source, "GDP", "GDPC1", tp, "quarter_end", "Rolling Bridge–DFM Ensemble")
        rt_w, _ = M["estimate_inverse_rmse_weights"](pd.DataFrame(rt_hist), model_names=("Bridge Ridge", "Dynamic Factor Model"), window=12, min_history=8, min_weight=.10, max_weight=.70)
        rt_repro = rt_w["Bridge Ridge"] * float(rt_b.point_forecast) + rt_w["Dynamic Factor Model"] * float(rt_d.point_forecast)
        gap = float(rt_repro - float(rt_r.point_forecast))
        if not close_enough(rt_repro, float(rt_r.point_forecast)):
            raise RuntimeError(f"Stored GDP rolling forecast cannot be reproduced at {tp}: gap={gap}")
        lv_b, lv_d, _ = fit_gdp(snap["lv"], tp, rec.forecast_date)
        lv_w, _ = M["estimate_inverse_rmse_weights"](pd.DataFrame(lv_hist), model_names=("Bridge Ridge", "Dynamic Factor Model"), window=12, min_history=8, min_weight=.10, max_weight=.70)
        lv_roll = lv_w["Bridge Ridge"] * float(lv_b.point_forecast) + lv_w["Dynamic Factor Model"] * float(lv_d.point_forecast)
        if is_evaluation("GDP", tp):
            selected = pol[("GDP", "GDPC1", "quarter_end")]
            if selected != "Rolling Bridge–DFM Ensemble":
                raise RuntimeError("Frozen GDP quarter-end policy changed unexpectedly.")
            rows.append(make_detail(
                domain="GDP", target="GDPC1", stage_order=order[("GDP", "GDPC1", "quarter_end")], stage="quarter_end",
                target_period=tp, forecast_date=rec.forecast_date, selected_model=selected, actual=float(rt_r.actual),
                rt_point=float(rt_r.point_forecast), lv_point=float(lv_roll), snap=snap,
                rolling_rt_repro_gap=gap, rolling_rt_w_bridge=float(rt_w["Bridge Ridge"]), rolling_lv_w_bridge=float(lv_w["Bridge Ridge"]),
            ))
        for hist, bp, dp in [(rt_hist, float(rt_b.point_forecast), float(rt_d.point_forecast)), (lv_hist, float(lv_b.point_forecast), float(lv_d.point_forecast))]:
            hist.extend([
                {"model_name": "Bridge Ridge", "forecast_date": pd.Timestamp(rec.forecast_date), "point_forecast": bp, "actual": float(rec.actual)},
                {"model_name": "Dynamic Factor Model", "forecast_date": pd.Timestamp(rec.forecast_date), "point_forecast": dp, "actual": float(rec.actual)},
            ])

    # GDP remaining evaluation stages.
    g = origin_rows(source, "GDP", "GDPC1")
    g = g.loc[g.target_period.map(lambda x: is_evaluation("GDP", str(x))) & (g.forecast_stage != "quarter_end")].copy()
    g["_p"] = g.target_period.map(lambda x: pd.Period(str(x), freq="Q"))
    g["_s"] = g.forecast_stage.map({x:i for i,x in enumerate(STAGES["GDP"],1)})
    for rec in g.sort_values(["_p","_s"]).itertuples(index=False):
        stage, tp = str(rec.forecast_stage), str(rec.target_period)
        selected = pol[("GDP", "GDPC1", stage)]
        snap = snapshots("GDP", rec.forecast_date, str(rec.information_set_hash))
        rt = stored_row(source, "GDP", "GDPC1", tp, stage, selected)
        lv_b, lv_d, lv_f = fit_gdp(snap["lv"], tp, rec.forecast_date)
        if selected == "Dynamic Factor Model":
            lv_point = float(lv_d.point_forecast)
        elif selected == "Bridge–DFM Ensemble":
            lv_point = float(lv_f.point_forecast)
            rb = stored_row(source, "GDP", "GDPC1", tp, stage, "Bridge Ridge")
            rd = stored_row(source, "GDP", "GDPC1", tp, stage, "Dynamic Factor Model")
            if not close_enough(.5*(float(rb.point_forecast)+float(rd.point_forecast)), float(rt.point_forecast)):
                raise RuntimeError(f"Stored GDP fixed ensemble cannot be reproduced at {tp}/{stage}.")
        else:
            raise RuntimeError(f"Unsupported frozen GDP policy model: {selected}")
        rows.append(make_detail(domain="GDP", target="GDPC1", stage_order=order[("GDP","GDPC1",stage)], stage=stage, target_period=tp, forecast_date=rec.forecast_date, selected_model=selected, actual=float(rt.actual), rt_point=float(rt.point_forecast), lv_point=lv_point, snap=snap))

    # Inflation evaluation.
    inf_cfg = M["get_inflation_model_config"]()
    coverage = float(inf_cfg.get("interval_coverage", .80))
    def fit_inf(snapshot, target, tp):
        ds = M["build_inflation_dataset"](snapshot, target, target_period=pd.Period(str(tp), freq="M"))
        ridge = M["inflation_fit_bridge"](ds.X, ds.y, ds.forecast_X, alpha=float(inf_cfg.get("ridge_alpha",8.0)), coverage=coverage)
        ar1 = M["inflation_fit_ar1"](ds.y, coverage=coverage)
        mean = M["inflation_fit_mean"](ds.y, window=int(inf_cfg.get("rolling_mean_window",12)), coverage=coverage)
        ens = M["inflation_combine"](ridge, ar1, ds.y, coverage=coverage)
        return {x.model_name:x for x in [ridge, ar1, mean, ens]}
    for target in TARGETS["Inflation"]:
        o = origin_rows(source, "Inflation", target)
        o = o.loc[o.target_period.map(lambda x:is_evaluation("Inflation",str(x)))].copy()
        o["_p"] = o.target_period.map(lambda x:pd.Period(str(x),freq="M"))
        o["_s"] = o.forecast_stage.map({x:i for i,x in enumerate(STAGES["Inflation"],1)})
        for rec in o.sort_values(["_p","_s"]).itertuples(index=False):
            stage,tp = str(rec.forecast_stage),str(rec.target_period)
            selected = pol[("Inflation",target,stage)]
            snap = snapshots("Inflation",rec.forecast_date,str(rec.information_set_hash))
            rt = stored_row(source,"Inflation",target,tp,stage,selected)
            suite = fit_inf(snap["lv"],target,tp)
            if selected not in suite:
                raise RuntimeError(f"Frozen inflation model not in production suite: {selected}")
            if selected == "Inflation Ridge-AR Ensemble":
                rr = stored_row(source,"Inflation",target,tp,stage,"Inflation Bridge Ridge")
                ra = stored_row(source,"Inflation",target,tp,stage,"Inflation AR(1)")
                if not close_enough(.5*(float(rr.point_forecast)+float(ra.point_forecast)),float(rt.point_forecast)):
                    raise RuntimeError(f"Stored inflation ensemble cannot be reproduced at {target}/{tp}/{stage}.")
            rows.append(make_detail(domain="Inflation",target=target,stage_order=order[("Inflation",target,stage)],stage=stage,target_period=tp,forecast_date=rec.forecast_date,selected_model=selected,actual=float(rt.actual),rt_point=float(rt.point_forecast),lv_point=float(suite[selected].point_forecast),snap=snap))

    # Labour evaluation.
    lab_cfg = M["get_labour_model_config"]()
    for target in TARGETS["Labour"]:
        o = origin_rows(source,"Labour",target)
        o = o.loc[o.target_period.map(lambda x:is_evaluation("Labour",str(x)))].copy()
        o["_p"] = o.target_period.map(lambda x:pd.Period(str(x),freq="M"))
        o["_s"] = o.forecast_stage.map({x:i for i,x in enumerate(STAGES["Labour"],1)})
        for rec in o.sort_values(["_p","_s"]).itertuples(index=False):
            stage,tp = str(rec.forecast_stage),str(rec.target_period)
            selected = pol[("Labour",target,stage)]
            snap = snapshots("Labour",rec.forecast_date,str(rec.information_set_hash))
            rt = stored_row(source,"Labour",target,tp,stage,selected)
            ds = M["build_labour_dataset"](snap["lv"],target,target_period=pd.Period(tp,freq="M"))
            suite = {x.model_name:x for x in M["labour_fit_suite"](ds.X,ds.y,ds.forecast_X,lab_cfg)}
            if selected not in suite:
                raise RuntimeError(f"Frozen labour model not in production suite: {selected}")
            if selected == "Labour Equal-Weight Ensemble":
                members = ["Labour Bridge Ridge","Labour AR(1)","Labour Factor Ridge"]
                rt_repro = float(np.mean([float(stored_row(source,"Labour",target,tp,stage,m).point_forecast) for m in members]))
                if not close_enough(rt_repro,float(rt.point_forecast)):
                    raise RuntimeError(f"Stored labour ensemble cannot be reproduced at {target}/{tp}/{stage}.")
            rows.append(make_detail(domain="Labour",target=target,stage_order=order[("Labour",target,stage)],stage=stage,target_period=tp,forecast_date=rec.forecast_date,selected_model=selected,actual=float(rt.actual),rt_point=float(rt.point_forecast),lv_point=float(suite[selected].point_forecast),snap=snap))

    detail = pd.DataFrame(rows)
    ids = ["domain_name","target_series","target_period","forecast_stage"]
    if detail.empty or detail.duplicated(ids).any():
        raise RuntimeError("H3 output is empty or contains duplicate evaluation cells.")
    if (detail.mask_equal != 1).any() or (detail.rt_hash_verified != 1).any() or (detail.final_missing_values != 0).any():
        raise RuntimeError("H3 structural gates failed.")
    # Primary H3 stage-cell inference retains every available paired RT/LV
    # target-stage cell. Some end-of-sample inflation target periods are
    # structurally unbalanced in the frozen source backtests.
    return detail.sort_values(["domain_name","target_series","target_period","stage_order"]).reset_index(drop=True)


def build_sample_audit(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (domain, target, target_period), g in detail.groupby(
        ["domain_name", "target_series", "target_period"], sort=False
    ):
        expected = STAGES[str(domain)]
        observed_set = set(g["forecast_stage"].astype(str))
        unexpected = sorted(observed_set.difference(expected))
        if unexpected:
            raise RuntimeError(
                f"Unexpected H3 stage(s) for {domain}/{target}/{target_period}: "
                + ",".join(unexpected)
            )
        present = [stage for stage in expected if stage in observed_set]
        missing = [stage for stage in expected if stage not in observed_set]
        complete = int(len(missing) == 0)
        rows.append({
            "domain_name": domain,
            "target_series": target,
            "target_period": str(target_period),
            "expected_stage_count": len(expected),
            "observed_stage_count": len(present),
            "present_stages": "|".join(present),
            "missing_stages": "|".join(missing),
            "complete_stage_set": complete,
            "primary_stage_cell_included": 1,
            "secondary_target_summary_included": complete,
        })
    audit = pd.DataFrame(rows)
    if audit.empty:
        raise RuntimeError("H3 sample audit is empty.")
    return audit.sort_values(
        ["domain_name", "target_series", "target_period"]
    ).reset_index(drop=True)


def summarise(detail: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    stage_rows=[]
    for keys,g in detail.groupby(["domain_name","target_series","stage_order","forecast_stage","selected_model"],sort=False):
        domain,target,order,stage,model=keys
        g=g.copy(); g["_p"]=g.target_period.map(lambda x:period_value(domain,str(x))); g=g.sort_values("_p")
        sq,ae=paired_summary(g.delta_squared_error),paired_summary(g.delta_abs_error)
        stage_rows.append({
            "domain_name":domain,"target_series":target,"stage_order":int(order),"forecast_stage":stage,"selected_model":model,"n":int(sq["n"]),
            "mean_delta_squared_error":sq["mean"],"median_delta_squared_error":sq["median"],"squared_error_lv_win_share":sq["win_share"],
            "hac_bw_sq":int(sq["hac_bw"]),"hac_se_sq":sq["hac_se"],"hac_z_sq":sq["hac_z"],"hac_p_sq":sq["hac_p"],
            "mean_delta_abs_error":ae["mean"],"median_delta_abs_error":ae["median"],"abs_error_lv_win_share":ae["win_share"],
            "hac_bw_abs":int(ae["hac_bw"]),"hac_se_abs":ae["hac_se"],"hac_z_abs":ae["hac_z"],"hac_p_abs":ae["hac_p"],
            "mean_forecast_revision":float(g.forecast_revision.mean()),"mean_raw_changed_rows":float(g.raw_changed_rows.mean()),"fallback_rows_total":int(g.raw_fallback_rows.sum()),
        })
    stage_summary=pd.DataFrame(stage_rows)

    # Secondary target-level inference uses only target periods with the
    # complete predeclared stage set, so the within-period average has fixed
    # composition. This restriction does not alter the primary stage-cell
    # samples above.
    sample_audit = build_sample_audit(detail)
    complete_keys = sample_audit.loc[
        sample_audit["secondary_target_summary_included"] == 1,
        ["domain_name","target_series","target_period"],
    ]
    complete_detail = detail.merge(
        complete_keys,
        on=["domain_name","target_series","target_period"],
        how="inner",
        validate="many_to_one",
    )
    if complete_detail.empty:
        raise RuntimeError("No complete-stage periods available for target summary.")

    per=complete_detail.groupby(["domain_name","target_series","target_period"],as_index=False).agg(delta_squared_error=("delta_squared_error","mean"),delta_abs_error=("delta_abs_error","mean"),forecast_revision=("forecast_revision","mean"))
    target_rows=[]
    for (domain,target),g in per.groupby(["domain_name","target_series"],sort=False):
        g=g.copy(); g["_p"]=g.target_period.map(lambda x:period_value(domain,str(x))); g=g.sort_values("_p")
        sq,ae=paired_summary(g.delta_squared_error),paired_summary(g.delta_abs_error)
        observed_periods = int(((sample_audit.domain_name == domain) & (sample_audit.target_series == target)).sum())
        target_rows.append({
            "domain_name":domain,"target_series":target,"periods":int(sq["n"]),
            "observed_periods":observed_periods,"incomplete_periods_excluded":observed_periods-int(sq["n"]),
            "mean_stageavg_delta_sq":sq["mean"],"median_stageavg_delta_sq":sq["median"],"stageavg_sq_lv_win_share":sq["win_share"],
            "hac_bw_sq":int(sq["hac_bw"]),"hac_se_sq":sq["hac_se"],"hac_z_sq":sq["hac_z"],"hac_p_sq":sq["hac_p"],
            "mean_stageavg_delta_abs":ae["mean"],"median_stageavg_delta_abs":ae["median"],"stageavg_abs_lv_win_share":ae["win_share"],
            "hac_bw_abs":int(ae["hac_bw"]),"hac_se_abs":ae["hac_se"],"hac_z_abs":ae["hac_z"],"hac_p_abs":ae["hac_p"],
            "mean_forecast_revision":float(g.forecast_revision.mean()),
        })
    return stage_summary,pd.DataFrame(target_rows),sample_audit


def package_versions() -> dict:
    out={"python":platform.python_version()}
    for name in ["duckdb","numpy","pandas","scikit-learn","statsmodels","scipy"]:
        try: out[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: out[name]="unavailable"
    return out


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--paper-root",default=".")
    ap.add_argument("--macropulse-root",default="../MacroPulse")
    args=ap.parse_args()
    paper_root=Path(args.paper_root).resolve(); macro_root=Path(args.macropulse_root).resolve()
    db_path=macro_root/"data/macropulse.duckdb"
    if not db_path.is_file(): raise FileNotFoundError(db_path)

    print("="*96); print("CONFIRMATORY H3 — REAL-TIME VS LATEST-VINTAGE COUNTERFACTUAL"); print("="*96)
    analysis_commit,script_sha=verify_preanalysis_boundaries(paper_root,macro_root)
    print(f"Policy freeze commit: {POLICY_FREEZE_COMMIT}")
    print(f"H3 input freeze commit: {H3_INPUT_COMMIT}")
    print(f"Pre-analysis code commit: {analysis_commit}")
    print(f"Analysis script SHA256: {script_sha}")
    print(f"Pinned MacroPulse source: {MACROPULSE_SOURCE_COMMIT}")
    print("PRE-ANALYSIS BOUNDARY VERIFICATION: PASS")

    stage_policy=pd.read_csv(paper_root/"freeze/research_stage_policy_freeze.csv")
    if len(stage_policy)!=36: raise RuntimeError(f"Expected 36 frozen stage-policy rows, got {len(stage_policy)}")
    frozen=pd.read_csv(paper_root/"data/raw/vintage/latest_vintage_extract.csv",parse_dates=["observation_date","realtime_start","realtime_end","retrieved_at"])
    if frozen.duplicated(["series_id","observation_date"]).any(): raise RuntimeError("Frozen latest extract has duplicate keys.")

    oldcwd=Path.cwd()
    with tempfile.TemporaryDirectory(prefix="macropulse_h3_pinned_") as tmp:
        root=Path(tmp); extract_pinned_macropulse(macro_root,root); sys.path.insert(0,str(root/"src")); os.chdir(root)
        from macropulse.backtesting.metrics import estimate_inverse_rmse_weights
        from macropulse.config import get_series_definitions,load_registry
        from macropulse.governance.versioning import information_set_hash
        from macropulse.inflation.config import get_inflation_model_config,get_inflation_series_definitions
        from macropulse.inflation.dataset import build_target_dataset as build_inflation_dataset
        from macropulse.inflation.models import combine_equal_weight as inflation_combine,fit_ar1 as inflation_fit_ar1,fit_ridge_bridge as inflation_fit_bridge,fit_rolling_mean as inflation_fit_mean
        from macropulse.labour.config import get_labour_model_config,get_labour_series_definitions
        from macropulse.labour.dataset import build_target_dataset as build_labour_dataset
        from macropulse.labour.models import fit_model_suite as labour_fit_suite
        from macropulse.models.baseline import combine_weighted,fit_bridge_ridge as fit_gdp_bridge
        from macropulse.models.dynamic_factor import fit_dynamic_factor
        from macropulse.processing.dataset import build_bridge_dataset
        from macropulse.processing.mixed_frequency import build_mixed_frequency_dataset
        M=locals().copy()
        con=duckdb.connect(str(db_path),read_only=True)
        try:
            source=load_source_rows(con); detail=run_h3(con,source,stage_policy,frozen,M)
        finally:
            con.close(); os.chdir(oldcwd); sys.path.pop(0)

    stage_summary,target_summary,sample_audit=summarise(detail)
    out=paper_root/"outputs/confirmatory"; out.mkdir(parents=True,exist_ok=True)
    detail_path=out/"h3_vintage_detail.csv"; summary_path=out/"h3_vintage_summary.csv"; target_path=out/"h3_vintage_target_summary.csv"; sample_path=out/"h3_vintage_sample_audit.csv"; manifest_path=out/"confirmatory_h3_manifest.json"
    write_csv(detail,detail_path); write_csv(stage_summary,summary_path); write_csv(target_summary,target_path); write_csv(sample_audit,sample_path)
    manifest={
        "hypothesis":"H3","estimand":"loss_latest_vintage_minus_loss_real_time","negative_value_interpretation":"latest-vintage counterfactual improves accuracy",
        "primary_loss":"squared_error","secondary_loss":"absolute_error","policy_freeze_commit":POLICY_FREEZE_COMMIT,"h3_input_freeze_commit":H3_INPUT_COMMIT,
        "original_h3_preanalysis_commit":ORIGINAL_H3_PREANALYSIS_COMMIT,"preanalysis_code_commit":analysis_commit,"analysis_script_sha256":script_sha,"macropulse_source_commit":MACROPULSE_SOURCE_COMMIT,
        "frozen_latest_sha256":FROZEN_LATEST_SHA256,"frozen_latest_manifest_sha256":FROZEN_MANIFEST_SHA256,"stage_policy_sha256":FROZEN_STAGE_POLICY_SHA256,
        "source_backtest_ids":{"GDP":GDP_BACKTEST,"Inflation":INFLATION_BACKTEST,"Labour":LABOUR_BACKTEST},
        "evaluation_start":{"GDP":"2023Q2","Inflation":"2023-02","Labour":"2023-02"},
        "mask_rule":"Latest-vintage values replace RT values only on the exact RT series/date mask; missing frozen-latest keys fall back to RT.",
        "outcome_rule":"same stored initial-release outcome in both arms",
        "gdp_rolling_rule":"Each arm uses its own prior same-stage Bridge/DFM forecast errors; window=12, min_history=8, weights in [0.10,0.70]; current errors enter only subsequent weights.",
        "inference":"Newey-West HAC SE, Bartlett weights, bandwidth floor(4*(n/100)^(2/9)).",
        "primary_sample_rule":"All available paired RT/LV target-stage cells are retained stage by stage; stage-cell n may differ at the end of sample.","target_summary_rule":"Secondary target summary uses only target periods with the complete predeclared stage set, averages stage loss differentials within period, then applies HAC across periods.","structural_hotfix_reason":"The original preanalysis code incorrectly required every target period to contain every stage. A structure-only diagnostic identified end-of-sample inflation periods with missing source stages; no H3 output files were produced by the failed run.",
        "rt_reproduction_tolerance":RT_REPRO_TOL,"package_versions":package_versions(),
        "row_counts":{"detail":int(len(detail)),"stage_summary":int(len(stage_summary)),"target_summary":int(len(target_summary)),"sample_audit":int(len(sample_audit)),"incomplete_target_periods":int((sample_audit.complete_stage_set==0).sum()),"fallback_rows_total":int(detail.raw_fallback_rows.sum()),"origins_with_changed_values":int((detail.raw_changed_rows>0).sum())},
        "output_hashes":{detail_path.name:sha256_file(detail_path),summary_path.name:sha256_file(summary_path),target_path.name:sha256_file(target_path),sample_path.name:sha256_file(sample_path)},
    }
    manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")

    print(); print("="*96); print("H3 STAGE-CELL RESULTS"); print("Negative loss differential means latest-vintage data improve accuracy."); print("="*96)
    print(stage_summary[["domain_name","target_series","forecast_stage","selected_model","n","mean_delta_squared_error","hac_se_sq","hac_p_sq","mean_delta_abs_error"]].to_string(index=False))
    incomplete=sample_audit.loc[sample_audit.complete_stage_set==0]
    print(); print("="*96); print("H3 SAMPLE AUDIT — INCOMPLETE TARGET PERIODS"); print("="*96)
    print(incomplete.to_string(index=False) if len(incomplete) else "NONE")
    print(); print("="*96); print("H3 TARGET-LEVEL STAGE-AVERAGED RESULTS — COMPLETE-STAGE PERIODS ONLY"); print("="*96)
    print(target_summary[["domain_name","target_series","periods","observed_periods","incomplete_periods_excluded","mean_stageavg_delta_sq","hac_se_sq","hac_p_sq","mean_stageavg_delta_abs"]].to_string(index=False))
    print(); print("="*96); print("H3 OUTPUT HASHES"); print("="*96)
    for n,h in manifest["output_hashes"].items(): print(f"{n}: {h}")
    print(f"Manifest: {manifest_path}")
    print(); print("="*96); print("CONFIRMATORY H3 EVALUATION COMPLETED SUCCESSFULLY"); print("="*96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
