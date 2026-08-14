from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


GDP_BACKTEST = "382b4c6b-ef76-4ca1-b52f-d5e3e1ac66b1"
INFLATION_BACKTEST = "fdd2f573-a425-4abc-8056-f9843955bac2"
LABOUR_BACKTEST = "834e0655-ba81-4b96-b42c-e1cdda73b847"

TIE_TOL = 1e-12
ERROR_TOL = 1e-9

SPLITS = {
    "GDP": {
        "development_end": "2022Q4",
        "embargo": "2023Q1",
        "evaluation_start": "2023Q2",
    },
    "Inflation": {
        "development_end": "2022-12",
        "embargo": "2023-01",
        "evaluation_start": "2023-02",
    },
    "Labour": {
        "development_end": "2022-12",
        "embargo": "2023-01",
        "evaluation_start": "2023-02",
    },
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

POLICY_ROWS_EXCLUDED = {
    "GDP": ["Stable Stage Policy", "Robust Stage-Adaptive Policy"]
}


def sql_list(values: list[str]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_frame_hash(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.loc[:, columns].copy()
    ordered = ordered.sort_values(columns, kind="mergesort").reset_index(drop=True)
    payload = ordered.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.17g",
        na_rep="<NA>",
    ).encode("utf-8")
    return sha256_bytes(payload)


def load_development_rows(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    gdp_models = sql_list(CANDIDATES["GDP"])
    inf_models = sql_list(CANDIDATES["Inflation"])
    lab_models = sql_list(CANDIDATES["Labour"])

    gdp = con.execute(
        f"""
        SELECT
            'GDP' AS domain_name,
            'GDPC1' AS target_series,
            target_period,
            forecast_stage,
            forecast_date,
            actual_release_date,
            model_name,
            point_forecast,
            actual,
            error,
            abs_error,
            squared_error
        FROM stage_backtest_results
        WHERE stage_backtest_id = ?
          AND target_period <= ?
          AND model_name IN ({gdp_models})
        ORDER BY target_period, forecast_stage, forecast_date, model_name
        """,
        [GDP_BACKTEST, SPLITS["GDP"]["development_end"]],
    ).fetchdf()

    inflation = con.execute(
        f"""
        SELECT
            'Inflation' AS domain_name,
            target_series,
            target_period,
            forecast_stage,
            forecast_date,
            actual_release_date,
            model_name,
            point_forecast,
            actual,
            error,
            abs_error,
            squared_error
        FROM inflation_vintage_backtest_results
        WHERE backtest_id = ?
          AND target_period <= ?
          AND model_name IN ({inf_models})
        ORDER BY target_series, target_period, forecast_stage, forecast_date, model_name
        """,
        [INFLATION_BACKTEST, SPLITS["Inflation"]["development_end"]],
    ).fetchdf()

    labour = con.execute(
        f"""
        SELECT
            'Labour' AS domain_name,
            target_series,
            target_period,
            forecast_stage,
            forecast_date,
            actual_release_date,
            model_name,
            point_forecast,
            actual,
            error,
            abs_error,
            squared_error
        FROM labour_vintage_backtest_results
        WHERE backtest_id = ?
          AND target_period <= ?
          AND model_name IN ({lab_models})
        ORDER BY target_series, target_period, forecast_stage, forecast_date, model_name
        """,
        [LABOUR_BACKTEST, SPLITS["Labour"]["development_end"]],
    ).fetchdf()

    frame = pd.concat([gdp, inflation, labour], ignore_index=True)
    frame["forecast_date"] = pd.to_datetime(frame["forecast_date"])
    frame["actual_release_date"] = pd.to_datetime(frame["actual_release_date"])
    return frame


def validate_development_input(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "domain_name", "target_series", "target_period", "forecast_stage",
        "forecast_date", "model_name", "point_forecast", "actual",
        "error", "abs_error", "squared_error",
    ]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise RuntimeError(f"Missing required columns: {missing}")
    if frame.empty:
        raise RuntimeError("No development rows were loaded.")

    for domain, end_period in (
        ("GDP", SPLITS["GDP"]["development_end"]),
        ("Inflation", SPLITS["Inflation"]["development_end"]),
        ("Labour", SPLITS["Labour"]["development_end"]),
    ):
        bad = frame.loc[
            (frame["domain_name"] == domain)
            & (frame["target_period"].astype(str) > end_period)
        ]
        if not bad.empty:
            raise RuntimeError(
                f"Evaluation/embargo contamination detected for {domain}: "
                f"{bad['target_period'].unique().tolist()}"
            )

    for domain in ("GDP", "Inflation", "Labour"):
        subset = frame.loc[frame["domain_name"] == domain]
        unknown_models = sorted(set(subset["model_name"]) - set(CANDIDATES[domain]))
        unknown_stages = sorted(set(subset["forecast_stage"]) - set(STAGES[domain]))
        unknown_targets = sorted(set(subset["target_series"]) - set(TARGETS[domain]))
        if unknown_models:
            raise RuntimeError(f"Unknown {domain} candidate models: {unknown_models}")
        if unknown_stages:
            raise RuntimeError(f"Unknown {domain} stages: {unknown_stages}")
        if unknown_targets:
            raise RuntimeError(f"Unknown {domain} targets: {unknown_targets}")

    key_model = [
        "domain_name", "target_series", "target_period",
        "forecast_stage", "forecast_date", "model_name",
    ]
    duplicates = frame.duplicated(key_model, keep=False)
    if duplicates.any():
        raise RuntimeError(
            "Duplicate candidate forecasts detected:\n"
            + frame.loc[duplicates, key_model].head(20).to_string(index=False)
        )

    frame = frame.copy()
    frame["error_recomputed"] = frame["actual"] - frame["point_forecast"]
    frame["abs_error_recomputed"] = frame["error_recomputed"].abs()
    frame["squared_error_recomputed"] = frame["error_recomputed"] ** 2
    valid = frame["actual"].notna() & frame["point_forecast"].notna()

    for stored, recomputed in (
        ("abs_error", "abs_error_recomputed"),
        ("squared_error", "squared_error_recomputed"),
    ):
        check = valid & frame[stored].notna()
        if check.any():
            ok = np.isclose(
                frame.loc[check, stored].astype(float),
                frame.loc[check, recomputed].astype(float),
                atol=ERROR_TOL,
                rtol=1e-10,
                equal_nan=False,
            )
            if not bool(np.all(ok)):
                bad = frame.loc[check].loc[~ok, key_model + [stored, recomputed]]
                raise RuntimeError(
                    f"Stored {stored} does not reproduce from actual/forecast:\n"
                    + bad.head(20).to_string(index=False)
                )
    return frame


def choose_candidate(metrics: pd.DataFrame) -> tuple[str, float, float, int]:
    if metrics.empty:
        raise RuntimeError("Cannot choose from an empty candidate table.")
    min_mse = float(metrics["mse"].min())
    tied = metrics.loc[(metrics["mse"] - min_mse).abs() <= TIE_TOL].copy()
    min_mae = float(tied["mae"].min())
    tied = tied.loc[(tied["mae"] - min_mae).abs() <= TIE_TOL].copy()
    tied = tied.sort_values("model_name", kind="mergesort")
    winner = tied.iloc[0]
    return (
        str(winner["model_name"]),
        float(winner["mse"]),
        float(winner["mae"]),
        int(winner["n"]),
    )


def stage_common_sample(
    frame: pd.DataFrame,
    domain: str,
    target: str,
    stage: str,
) -> tuple[pd.DataFrame, dict]:
    candidates = CANDIDATES[domain]
    subset = frame.loc[
        (frame["domain_name"] == domain)
        & (frame["target_series"] == target)
        & (frame["forecast_stage"] == stage)
        & (frame["model_name"].isin(candidates))
    ].copy()

    origin_cols = [
        "domain_name", "target_series", "target_period",
        "forecast_stage", "forecast_date",
    ]
    subset["valid_forecast"] = (
        subset["actual"].notna()
        & subset["point_forecast"].notna()
        & np.isfinite(subset["actual"].astype(float))
        & np.isfinite(subset["point_forecast"].astype(float))
    )

    grouped = (
        subset.groupby(origin_cols, dropna=False)
        .agg(
            model_count=("model_name", "nunique"),
            row_count=("model_name", "size"),
            valid_count=("valid_forecast", "sum"),
            actual_min=("actual", "min"),
            actual_max=("actual", "max"),
        )
        .reset_index()
    )
    grouped["actual_consistent"] = (
        (grouped["actual_max"] - grouped["actual_min"]).abs() <= TIE_TOL
    ).astype(int)

    common_keys = grouped.loc[
        (grouped["model_count"] == len(candidates))
        & (grouped["row_count"] == len(candidates))
        & (grouped["valid_count"] == len(candidates))
        & (grouped["actual_consistent"] == 1),
        origin_cols,
    ].copy()
    if common_keys.empty:
        raise RuntimeError(f"No common development sample for {domain}/{target}/{stage}.")

    common = subset.merge(common_keys, on=origin_cols, how="inner", validate="many_to_one")
    counts = common.groupby("model_name").size()
    if set(counts.index) != set(candidates):
        raise RuntimeError(
            f"Candidate set mismatch in common sample for {domain}/{target}/{stage}."
        )
    if counts.nunique() != 1 or int(counts.iloc[0]) != len(common_keys):
        raise RuntimeError(
            f"Unbalanced common sample for {domain}/{target}/{stage}: "
            f"{counts.to_dict()}"
        )

    key_hash = canonical_frame_hash(common_keys, origin_cols)
    audit = {
        "domain_name": domain,
        "target_series": target,
        "forecast_stage": stage,
        "candidate_count": len(candidates),
        "candidate_rows_before_common_filter": len(subset),
        "candidate_origins_before_common_filter": len(grouped),
        "common_origins": len(common_keys),
        "common_rows": len(common),
        "actual_consistent": 1,
        "first_target_period": str(common_keys["target_period"].min()),
        "last_target_period": str(common_keys["target_period"].max()),
        "first_forecast_date": common_keys["forecast_date"].min().date().isoformat(),
        "last_forecast_date": common_keys["forecast_date"].max().date().isoformat(),
        "common_key_sha256": key_hash,
    }
    return common, audit


def metrics_for_frame(common: pd.DataFrame) -> pd.DataFrame:
    out = (
        common.groupby("model_name", as_index=False)
        .agg(
            n=("squared_error_recomputed", "size"),
            mse=("squared_error_recomputed", "mean"),
            mae=("abs_error_recomputed", "mean"),
        )
        .sort_values(["mse", "mae", "model_name"], kind="mergesort")
        .reset_index(drop=True)
    )
    out["rmse"] = np.sqrt(out["mse"])
    return out[["model_name", "n", "mse", "rmse", "mae"]]


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False, lineterminator="\n", float_format="%.17g")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze development-only research stage policies and fixed-model "
            "comparators. This script does not read evaluation losses."
        )
    )
    parser.add_argument("--macropulse-root", default="../MacroPulse")
    parser.add_argument("--paper-root", default=".")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Explicitly overwrite an existing freeze. Do not use after evaluation starts.",
    )
    args = parser.parse_args()

    paper_root = Path(args.paper_root).resolve()
    macro_root = Path(args.macropulse_root).resolve()
    db_path = macro_root / "data" / "macropulse.duckdb"
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    freeze_dir = paper_root / "freeze"
    output_dir = paper_root / "outputs" / "tables"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    stage_policy_path = freeze_dir / "research_stage_policy_freeze.csv"
    fixed_path = freeze_dir / "research_fixed_comparator_freeze.csv"
    common_path = freeze_dir / "research_policy_common_sample_audit.csv"
    manifest_path = freeze_dir / "research_policy_freeze_manifest.json"

    protected = [stage_policy_path, fixed_path, common_path, manifest_path]
    existing = [p for p in protected if p.exists()]
    if existing and not args.force:
        raise RuntimeError(
            "Freeze artifacts already exist. Refusing to overwrite:\n"
            + "\n".join(str(p) for p in existing)
            + "\nUse --force only before any evaluation analysis and only if "
              "you intentionally invalidate the previous freeze."
        )

    con = duckdb.connect(str(db_path), read_only=True)

    # The only source-data load. Every query is development-period restricted.
    development = validate_development_input(load_development_rows(con))

    input_hash_columns = [
        "domain_name", "target_series", "target_period", "forecast_stage",
        "forecast_date", "actual_release_date", "model_name",
        "point_forecast", "actual", "error", "abs_error", "squared_error",
    ]
    development_input_sha256 = canonical_frame_hash(
        development, input_hash_columns
    )

    stage_policy_rows = []
    fixed_rows = []
    common_audit_rows = []
    stage_metric_frames = []
    fixed_metric_frames = []

    for domain in ("GDP", "Inflation", "Labour"):
        for target in TARGETS[domain]:
            target_common = []
            for stage_order, stage in enumerate(STAGES[domain], start=1):
                common, audit = stage_common_sample(
                    development, domain, target, stage
                )
                target_common.append(common)
                common_audit_rows.append(audit)

                metrics = metrics_for_frame(common)
                winner, winner_mse, winner_mae, winner_n = choose_candidate(metrics)

                metrics.insert(0, "forecast_stage", stage)
                metrics.insert(0, "stage_order", stage_order)
                metrics.insert(0, "target_series", target)
                metrics.insert(0, "domain_name", domain)
                stage_metric_frames.append(metrics)

                stage_policy_rows.append({
                    "domain_name": domain,
                    "target_series": target,
                    "stage_order": stage_order,
                    "forecast_stage": stage,
                    "selected_model": winner,
                    "development_n": winner_n,
                    "development_mse": winner_mse,
                    "development_rmse": float(np.sqrt(winner_mse)),
                    "development_mae": winner_mae,
                    "selection_rule": "min_MSE_then_MAE_then_model_name",
                    "tie_tolerance": TIE_TOL,
                })

            pooled = pd.concat(target_common, ignore_index=True)
            pooled_counts = pooled.groupby("model_name").size()
            if pooled_counts.nunique() != 1:
                raise RuntimeError(
                    f"Pooled fixed-comparator sample is unbalanced for "
                    f"{domain}/{target}: {pooled_counts.to_dict()}"
                )

            fixed_metrics = metrics_for_frame(pooled)
            fixed_winner, fixed_mse, fixed_mae, fixed_n = choose_candidate(
                fixed_metrics
            )
            fixed_metrics.insert(0, "target_series", target)
            fixed_metrics.insert(0, "domain_name", domain)
            fixed_metric_frames.append(fixed_metrics)

            fixed_rows.append({
                "domain_name": domain,
                "target_series": target,
                "selected_model": fixed_winner,
                "development_n": fixed_n,
                "development_mse": fixed_mse,
                "development_rmse": float(np.sqrt(fixed_mse)),
                "development_mae": fixed_mae,
                "stage_count": len(STAGES[domain]),
                "selection_rule": "pooled_min_MSE_then_MAE_then_model_name",
                "tie_tolerance": TIE_TOL,
            })

    stage_policy = pd.DataFrame(stage_policy_rows)
    fixed_policy = pd.DataFrame(fixed_rows)
    common_audit = pd.DataFrame(common_audit_rows)
    stage_metrics = pd.concat(stage_metric_frames, ignore_index=True)
    fixed_metrics = pd.concat(fixed_metric_frames, ignore_index=True)

    expected_stage_rows = 5 + 4 * 4 + 3 * 5
    expected_fixed_rows = 1 + 4 + 3
    expected_stage_metric_rows = 5 * 5 + (4 * 4 * 4) + (3 * 5 * 5)
    expected_fixed_metric_rows = 5 + (4 * 4) + (3 * 5)

    if len(stage_policy) != expected_stage_rows:
        raise RuntimeError(
            f"Expected {expected_stage_rows} stage-policy rows, got {len(stage_policy)}."
        )
    if len(fixed_policy) != expected_fixed_rows:
        raise RuntimeError(
            f"Expected {expected_fixed_rows} fixed-comparator rows, got {len(fixed_policy)}."
        )
    if len(common_audit) != expected_stage_rows:
        raise RuntimeError(
            f"Expected {expected_stage_rows} common-sample audit rows, got {len(common_audit)}."
        )
    if len(stage_metrics) != expected_stage_metric_rows:
        raise RuntimeError(
            f"Expected {expected_stage_metric_rows} stage metric rows, got {len(stage_metrics)}."
        )
    if len(fixed_metrics) != expected_fixed_metric_rows:
        raise RuntimeError(
            f"Expected {expected_fixed_metric_rows} fixed metric rows, got {len(fixed_metrics)}."
        )

    stage_policy = stage_policy.sort_values(
        ["domain_name", "target_series", "stage_order"], kind="mergesort"
    ).reset_index(drop=True)
    fixed_policy = fixed_policy.sort_values(
        ["domain_name", "target_series"], kind="mergesort"
    ).reset_index(drop=True)
    common_audit = common_audit.sort_values(
        ["domain_name", "target_series", "forecast_stage"], kind="mergesort"
    ).reset_index(drop=True)
    stage_metrics = stage_metrics.sort_values(
        ["domain_name", "target_series", "stage_order", "mse", "mae", "model_name"],
        kind="mergesort",
    ).reset_index(drop=True)
    fixed_metrics = fixed_metrics.sort_values(
        ["domain_name", "target_series", "mse", "mae", "model_name"],
        kind="mergesort",
    ).reset_index(drop=True)

    stage_metrics_path = output_dir / "research_stage_candidate_development_metrics.csv"
    fixed_metrics_path = output_dir / "research_fixed_candidate_development_metrics.csv"

    write_csv_atomic(stage_metrics, stage_metrics_path)
    write_csv_atomic(fixed_metrics, fixed_metrics_path)
    write_csv_atomic(stage_policy, stage_policy_path)
    write_csv_atomic(fixed_policy, fixed_path)
    write_csv_atomic(common_audit, common_path)

    script_path = Path(__file__).resolve()
    manifest = {
        "freeze_type": "MacroPulse research policy freeze",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_scope": "development_sample_only",
        "evaluation_losses_read": False,
        "evaluation_rows_read": 0,
        "tie_tolerance": TIE_TOL,
        "loss_selection_rule": {
            "stage_policy": (
                "minimum common-sample MSE, then MAE, then alphabetical model name"
            ),
            "fixed_comparator": (
                "minimum pooled common-sample MSE across all stages, "
                "then MAE, then alphabetical model name"
            ),
        },
        "splits": SPLITS,
        "stages": STAGES,
        "targets": TARGETS,
        "candidate_models": CANDIDATES,
        "excluded_policy_rows": POLICY_ROWS_EXCLUDED,
        "source_backtest_ids": {
            "GDP": GDP_BACKTEST,
            "Inflation": INFLATION_BACKTEST,
            "Labour": LABOUR_BACKTEST,
        },
        "development_input_sha256": development_input_sha256,
        "development_input_rows": int(len(development)),
        "script_sha256": sha256_file(script_path),
        "freeze_files": {
            stage_policy_path.name: sha256_file(stage_policy_path),
            fixed_path.name: sha256_file(fixed_path),
            common_path.name: sha256_file(common_path),
        },
        "diagnostic_development_files": {
            stage_metrics_path.name: sha256_file(stage_metrics_path),
            fixed_metrics_path.name: sha256_file(fixed_metrics_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 88)
    print("DEVELOPMENT-ONLY RESEARCH STAGE POLICY")
    print("=" * 88)
    print(stage_policy[
        ["domain_name", "target_series", "forecast_stage", "selected_model",
         "development_n", "development_rmse", "development_mae"]
    ].to_string(index=False))

    print()
    print("=" * 88)
    print("DEVELOPMENT-ONLY FIXED COMPARATORS")
    print("=" * 88)
    print(fixed_policy[
        ["domain_name", "target_series", "selected_model",
         "development_n", "development_rmse", "development_mae"]
    ].to_string(index=False))

    print()
    print("=" * 88)
    print("FREEZE HASHES")
    print("=" * 88)
    print(f"Development input SHA256: {development_input_sha256}")
    for name, digest in manifest["freeze_files"].items():
        print(f"{name}: {digest}")
    print(f"Manifest: {manifest_path}")
    print()
    print("EVALUATION LOSSES READ: NO")
    print("EVALUATION ROWS READ: 0")
    print()
    print("=" * 88)
    print("RESEARCH POLICY FREEZE COMPLETED SUCCESSFULLY")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
