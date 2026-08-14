from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


GDP_BACKTEST = "382b4c6b-ef76-4ca1-b52f-d5e3e1ac66b1"
INFLATION_BACKTEST = "fdd2f573-a425-4abc-8056-f9843955bac2"
LABOUR_BACKTEST = "834e0655-ba81-4b96-b42c-e1cdda73b847"

ATOL = 1e-12


def changed_frame(a: pd.DataFrame, b: pd.DataFrame) -> int:
    if not a.index.equals(b.index):
        return -1
    if list(a.columns) != list(b.columns):
        return -1
    aa = a.to_numpy(dtype=float)
    bb = b.to_numpy(dtype=float)
    equal = np.isclose(aa, bb, atol=ATOL, rtol=0.0, equal_nan=True)
    return int((~equal).sum())


def changed_series(a: pd.Series, b: pd.Series) -> int:
    if not a.index.equals(b.index):
        return -1
    aa = a.to_numpy(dtype=float)
    bb = b.to_numpy(dtype=float)
    equal = np.isclose(aa, bb, atol=ATOL, rtol=0.0, equal_nan=True)
    return int((~equal).sum())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def quote_sql(items: list[str]) -> str:
    return ",".join("'" + x.replace("'", "''") + "'" for x in items)


def load_rt_snapshot(
    connection: duckdb.DuckDBPyConnection,
    forecast_date,
    series_ids: list[str],
) -> pd.DataFrame:
    placeholders = ",".join(["?"] * len(series_ids))
    sql = f"""
        SELECT series_id, observation_date, value
        FROM historical_snapshots
        WHERE as_of_date = ?
          AND series_id IN ({placeholders})
        ORDER BY series_id, observation_date
    """
    frame = connection.execute(
        sql, [pd.Timestamp(forecast_date).date(), *series_ids]
    ).fetchdf()

    frame["observation_date"] = pd.to_datetime(frame["observation_date"])

    if frame.duplicated(["series_id", "observation_date"]).any():
        raise RuntimeError(
            f"Historical snapshot contains duplicate keys at {forecast_date}."
        )

    return frame


def make_lv_snapshot(
    rt: pd.DataFrame,
    frozen_latest: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    merged = rt.merge(
        frozen_latest[["series_id", "observation_date", "value"]],
        on=["series_id", "observation_date"],
        how="left",
        suffixes=("_rt", "_lv"),
        indicator=True,
        validate="one_to_one",
    )

    comparable = (merged["_merge"] == "both") & merged["value_lv"].notna()

    merged["value_final"] = np.where(
        comparable,
        merged["value_lv"],
        merged["value_rt"],
    )

    fallback_rows = int((~comparable).sum())

    changed = np.isclose(
        merged["value_rt"].to_numpy(dtype=float),
        merged["value_final"].to_numpy(dtype=float),
        atol=ATOL,
        rtol=0.0,
        equal_nan=True,
    )
    changed_rows = int((~changed).sum())

    lv = merged[
        ["series_id", "observation_date", "value_final"]
    ].rename(columns={"value_final": "value"})

    # Hard mask invariant.
    assert len(lv) == len(rt)
    assert list(
        zip(rt["series_id"], rt["observation_date"])
    ) == list(
        zip(lv["series_id"], lv["observation_date"])
    )

    return lv, fallback_rows, changed_rows


def freeze_latest_extract(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    all_series: list[str],
) -> pd.DataFrame:
    if path.exists():
        frame = pd.read_csv(
            path,
            parse_dates=[
                "observation_date",
                "realtime_start",
                "realtime_end",
                "retrieved_at",
            ],
        )
        print(f"Using already-frozen latest extract: {path}")
    else:
        placeholders = ",".join(["?"] * len(all_series))
        sql = f"""
            SELECT
                series_id,
                observation_date,
                realtime_start,
                realtime_end,
                value,
                retrieved_at,
                source
            FROM observations
            WHERE vintage_type = 'latest'
              AND series_id IN ({placeholders})
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY series_id, observation_date
                ORDER BY retrieved_at DESC
            ) = 1
            ORDER BY series_id, observation_date
        """
        frame = connection.execute(sql, all_series).fetchdf()
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        print(f"Created frozen latest extract: {path}")

    frame["observation_date"] = pd.to_datetime(frame["observation_date"])

    if frame.duplicated(["series_id", "observation_date"]).any():
        raise RuntimeError("Frozen latest extract has duplicate series/date keys.")

    return frame


def add_common(
    record: dict,
    domain: str,
    target_series: str,
    target_period: str,
    forecast_stage: str,
    forecast_date,
    builder: str,
    fallback_rows: int,
    raw_changed_rows: int,
) -> dict:
    record.update(
        {
            "domain": domain,
            "target_series": target_series,
            "target_period": target_period,
            "forecast_stage": forecast_stage,
            "forecast_date": pd.Timestamp(forecast_date).date(),
            "builder": builder,
            "raw_fallback_rows": fallback_rows,
            "raw_changed_rows": raw_changed_rows,
        }
    )
    return record


def audit_bridge(rt, lv, definitions, target_period, forecast_date):
    from macropulse.processing.dataset import build_bridge_dataset

    out = {}
    try:
        a = build_bridge_dataset(
            rt,
            definitions,
            "GDPC1",
            target_period=target_period,
            data_as_of=pd.Timestamp(forecast_date),
        )
        out["rt_status"] = "ok"
        out["rt_error"] = ""
    except Exception as exc:
        a = None
        out["rt_status"] = "fail"
        out["rt_error"] = str(exc)

    try:
        b = build_bridge_dataset(
            lv,
            definitions,
            "GDPC1",
            target_period=target_period,
            data_as_of=pd.Timestamp(forecast_date),
        )
        out["lv_status"] = "ok"
        out["lv_error"] = ""
    except Exception as exc:
        b = None
        out["lv_status"] = "fail"
        out["lv_error"] = str(exc)

    if a is None or b is None:
        out.update(
            structure_equal=0,
            imputation_equal=0,
            latest_period_equal=0,
            rt_training_obs=np.nan,
            lv_training_obs=np.nan,
            rt_feature_count=np.nan,
            lv_feature_count=np.nan,
            changed_training_features=np.nan,
            changed_target_history=np.nan,
            changed_forecast_features=np.nan,
        )
        return out

    structure = (
        a.training_frame.index.equals(b.training_frame.index)
        and list(a.training_frame.columns) == list(b.training_frame.columns)
        and a.current_features.index.equals(b.current_features.index)
        and list(a.current_features.columns) == list(b.current_features.columns)
        and a.feature_names == b.feature_names
    )

    out.update(
        structure_equal=int(structure),
        imputation_equal=int(
            sorted(a.imputed_features) == sorted(b.imputed_features)
        ),
        latest_period_equal=1,
        rt_training_obs=len(a.training_frame),
        lv_training_obs=len(b.training_frame),
        rt_feature_count=len(a.feature_names),
        lv_feature_count=len(b.feature_names),
        changed_training_features=changed_frame(
            a.training_frame.drop(columns=["target"]),
            b.training_frame.drop(columns=["target"]),
        ),
        changed_target_history=changed_series(
            a.training_frame["target"],
            b.training_frame["target"],
        ),
        changed_forecast_features=changed_frame(
            a.current_features, b.current_features
        ),
    )
    return out


def audit_dfm(rt, lv, definitions, target_period, forecast_date):
    from macropulse.processing.mixed_frequency import (
        build_mixed_frequency_dataset,
    )

    out = {}

    try:
        a = build_mixed_frequency_dataset(
            rt,
            definitions,
            "GDPC1",
            target_period=target_period,
            data_as_of=pd.Timestamp(forecast_date),
        )
        out["rt_status"] = "ok"
        out["rt_error"] = ""
    except Exception as exc:
        a = None
        out["rt_status"] = "fail"
        out["rt_error"] = str(exc)

    try:
        b = build_mixed_frequency_dataset(
            lv,
            definitions,
            "GDPC1",
            target_period=target_period,
            data_as_of=pd.Timestamp(forecast_date),
        )
        out["lv_status"] = "ok"
        out["lv_error"] = ""
    except Exception as exc:
        b = None
        out["lv_status"] = "fail"
        out["lv_error"] = str(exc)

    if a is None or b is None:
        out.update(
            structure_equal=0,
            imputation_equal=1,
            latest_period_equal=0,
            rt_training_obs=np.nan,
            lv_training_obs=np.nan,
            rt_feature_count=np.nan,
            lv_feature_count=np.nan,
            changed_training_features=np.nan,
            changed_target_history=np.nan,
            changed_forecast_features=np.nan,
        )
        return out

    structure = (
        a.monthly_features.index.equals(b.monthly_features.index)
        and list(a.monthly_features.columns)
        == list(b.monthly_features.columns)
        and a.quarterly_target.index.equals(b.quarterly_target.index)
        and a.feature_names == b.feature_names
    )

    out.update(
        structure_equal=int(structure),
        imputation_equal=1,
        latest_period_equal=int(
            a.last_available_periods == b.last_available_periods
        ),
        rt_training_obs=len(a.monthly_features),
        lv_training_obs=len(b.monthly_features),
        rt_feature_count=len(a.feature_names),
        lv_feature_count=len(b.feature_names),
        changed_training_features=changed_frame(
            a.monthly_features, b.monthly_features
        ),
        changed_target_history=changed_series(
            a.quarterly_target, b.quarterly_target
        ),
        changed_forecast_features=np.nan,
    )
    return out


def audit_monthly_builder(
    rt,
    lv,
    build_function,
    target_series,
    target_period,
):
    out = {}

    try:
        a = build_function(rt, target_series, target_period=target_period)
        out["rt_status"] = "ok"
        out["rt_error"] = ""
    except Exception as exc:
        a = None
        out["rt_status"] = "fail"
        out["rt_error"] = str(exc)

    try:
        b = build_function(lv, target_series, target_period=target_period)
        out["lv_status"] = "ok"
        out["lv_error"] = ""
    except Exception as exc:
        b = None
        out["lv_status"] = "fail"
        out["lv_error"] = str(exc)

    if a is None or b is None:
        out.update(
            structure_equal=0,
            imputation_equal=0,
            latest_period_equal=0,
            rt_training_obs=np.nan,
            lv_training_obs=np.nan,
            rt_feature_count=np.nan,
            lv_feature_count=np.nan,
            changed_training_features=np.nan,
            changed_target_history=np.nan,
            changed_forecast_features=np.nan,
        )
        return out

    structure = (
        a.X.index.equals(b.X.index)
        and list(a.X.columns) == list(b.X.columns)
        and a.y.index.equals(b.y.index)
        and a.forecast_X.index.equals(b.forecast_X.index)
        and list(a.forecast_X.columns) == list(b.forecast_X.columns)
    )

    out.update(
        structure_equal=int(structure),
        imputation_equal=int(
            a.feature_ages == b.feature_ages
            and sorted(a.imputed_features) == sorted(b.imputed_features)
        ),
        latest_period_equal=int(
            a.latest_observed_period == b.latest_observed_period
        ),
        rt_training_obs=len(a.X),
        lv_training_obs=len(b.X),
        rt_feature_count=len(a.X.columns),
        lv_feature_count=len(b.X.columns),
        changed_training_features=changed_frame(a.X, b.X),
        changed_target_history=changed_series(a.y, b.y),
        changed_forecast_features=changed_frame(
            a.forecast_X, b.forecast_X
        ),
    )

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--macropulse-root",
        default="../MacroPulse",
    )
    parser.add_argument(
        "--paper-root",
        default=".",
    )
    args = parser.parse_args()

    paper_root = Path(args.paper_root).resolve()
    macro_root = Path(args.macropulse_root).resolve()

    db_path = macro_root / "data" / "macropulse.duckdb"
    src_path = macro_root / "src"

    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if not src_path.is_dir():
        raise FileNotFoundError(src_path)

    sys.path.insert(0, str(src_path))

    # MacroPulse config loaders are safest when run from repository root.
    os.chdir(macro_root)

    from macropulse.config import get_series_definitions
    from macropulse.inflation.config import (
        target_definitions as inflation_targets,
        feature_definitions as inflation_features,
    )
    from macropulse.inflation.dataset import (
        build_target_dataset as build_inflation_dataset,
    )
    from macropulse.labour.config import (
        target_definitions as labour_targets,
        feature_definitions as labour_features,
    )
    from macropulse.labour.dataset import (
        build_target_dataset as build_labour_dataset,
    )

    gdp_definitions = get_series_definitions()
    inf_definitions = inflation_targets() + inflation_features()
    lab_definitions = labour_targets() + labour_features()

    gdp_series = [x.series_id for x in gdp_definitions]
    inf_series = [x.series_id for x in inf_definitions]
    lab_series = [x.series_id for x in lab_definitions]
    all_series = sorted(set(gdp_series + inf_series + lab_series))

    output_dir = paper_root / "outputs" / "tables"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_dir = paper_root / "data" / "raw" / "vintage"
    raw_dir.mkdir(parents=True, exist_ok=True)

    frozen_path = raw_dir / "latest_vintage_extract.csv"

    connection = duckdb.connect(str(db_path), read_only=True)

    frozen = freeze_latest_extract(
        connection, frozen_path, all_series
    )

    frozen_sha = sha256_file(frozen_path)

    manifest = (
        frozen.groupby("series_id")
        .agg(
            selected_rows=("observation_date", "size"),
            first_observation=("observation_date", "min"),
            last_observation=("observation_date", "max"),
            first_retrieved=("retrieved_at", "min"),
            last_retrieved=("retrieved_at", "max"),
        )
        .reset_index()
    )
    manifest["selection_rule"] = (
        "latest vintage_type; max retrieved_at per series_id/observation_date"
    )
    manifest["extract_sha256"] = frozen_sha
    manifest.to_csv(
        raw_dir / "latest_vintage_manifest.csv",
        index=False,
    )

    # ------------------------------------------------------------
    # Raw-mask audit with the frozen extract.
    # ------------------------------------------------------------
    connection.register("_frozen_latest", frozen)

    domain_specs = {
        "GDP": (
            f"""
            SELECT DISTINCT forecast_date
            FROM stage_backtest_results
            WHERE stage_backtest_id = '{GDP_BACKTEST}'
            """,
            gdp_series,
        ),
        "Inflation": (
            f"""
            SELECT DISTINCT forecast_date
            FROM inflation_vintage_backtest_results
            WHERE backtest_id = '{INFLATION_BACKTEST}'
            """,
            inf_series,
        ),
        "Labour": (
            f"""
            SELECT DISTINCT forecast_date
            FROM labour_vintage_backtest_results
            WHERE backtest_id = '{LABOUR_BACKTEST}'
            """,
            lab_series,
        ),
    }

    raw_rows = []
    fallback_frames = []

    for domain, (origin_sql, series_ids) in domain_specs.items():
        ids = quote_sql(series_ids)

        q = f"""
        WITH origins AS ({origin_sql}),
        p AS (
            SELECT
                h.series_id,
                h.observation_date,
                h.value AS rt_value,
                f.value AS lv_value
            FROM origins o
            JOIN historical_snapshots h
              ON h.as_of_date = o.forecast_date
            LEFT JOIN _frozen_latest f
              ON f.series_id = h.series_id
             AND f.observation_date = h.observation_date
            WHERE h.series_id IN ({ids})
        )
        SELECT
            COUNT(*) AS rows,
            SUM(CASE WHEN lv_value IS NOT NULL THEN 1 ELSE 0 END)
                AS comparable_rows,
            SUM(CASE WHEN lv_value IS NULL THEN 1 ELSE 0 END)
                AS fallback_rows,
            COUNT(
                DISTINCT CASE WHEN lv_value IS NULL
                THEN series_id || '|' || CAST(observation_date AS VARCHAR)
                END
            ) AS fallback_unique_keys,
            SUM(
                CASE WHEN COALESCE(lv_value, rt_value) IS NULL
                THEN 1 ELSE 0 END
            ) AS final_missing_values
        FROM p
        """
        r = connection.execute(q).fetchdf().iloc[0].to_dict()
        r["domain"] = domain
        raw_rows.append(r)

        fq = f"""
        WITH origins AS ({origin_sql})
        SELECT
            '{domain}' AS domain,
            h.series_id,
            h.observation_date,
            COUNT(*) AS snapshot_rows,
            MIN(h.value) AS min_rt_value,
            MAX(h.value) AS max_rt_value
        FROM origins o
        JOIN historical_snapshots h
          ON h.as_of_date = o.forecast_date
        LEFT JOIN _frozen_latest f
          ON f.series_id = h.series_id
         AND f.observation_date = h.observation_date
        WHERE h.series_id IN ({ids})
          AND f.value IS NULL
        GROUP BY h.series_id, h.observation_date
        ORDER BY h.series_id, h.observation_date
        """
        fallback_frames.append(connection.execute(fq).fetchdf())

    raw_audit = pd.DataFrame(raw_rows)[
        [
            "domain",
            "rows",
            "comparable_rows",
            "fallback_rows",
            "fallback_unique_keys",
            "final_missing_values",
        ]
    ]

    fallback_manifest = pd.concat(
        fallback_frames, ignore_index=True
    )

    raw_audit.to_csv(
        output_dir / "vintage_raw_mask_audit.csv",
        index=False,
    )
    fallback_manifest.to_csv(
        output_dir / "vintage_fallback_manifest.csv",
        index=False,
    )

    # ------------------------------------------------------------
    # Forecast-origin/model-input invariance.
    # ------------------------------------------------------------
    results = []

    gdp_origins = connection.execute(
        f"""
        SELECT
            target_period,
            forecast_stage,
            forecast_date,
            MAX(
                CASE WHEN model_name = 'Dynamic Factor Model'
                THEN 1 ELSE 0 END
            ) AS dfm_present
        FROM stage_backtest_results
        WHERE stage_backtest_id = '{GDP_BACKTEST}'
        GROUP BY target_period, forecast_stage, forecast_date
        ORDER BY forecast_date, target_period, forecast_stage
        """
    ).fetchdf()

    inflation_origins = connection.execute(
        f"""
        SELECT DISTINCT
            target_series,
            target_period,
            forecast_stage,
            forecast_date
        FROM inflation_vintage_backtest_results
        WHERE backtest_id = '{INFLATION_BACKTEST}'
        ORDER BY forecast_date, target_series, target_period, forecast_stage
        """
    ).fetchdf()

    labour_origins = connection.execute(
        f"""
        SELECT DISTINCT
            target_series,
            target_period,
            forecast_stage,
            forecast_date
        FROM labour_vintage_backtest_results
        WHERE backtest_id = '{LABOUR_BACKTEST}'
        ORDER BY forecast_date, target_series, target_period, forecast_stage
        """
    ).fetchdf()

    def snapshots_for_date(date_value, series_ids):
        rt = load_rt_snapshot(connection, date_value, series_ids)
        lv, fallback, changed = make_lv_snapshot(
            rt,
            frozen.loc[frozen["series_id"].isin(series_ids)].copy(),
        )
        return rt, lv, fallback, changed

    # GDP
    for n, row in enumerate(gdp_origins.itertuples(index=False), start=1):
        rt, lv, fallback, raw_changed = snapshots_for_date(
            row.forecast_date, gdp_series
        )
        period = pd.Period(str(row.target_period), freq="Q")

        record = audit_bridge(
            rt, lv, gdp_definitions, period, row.forecast_date
        )
        results.append(
            add_common(
                record,
                "GDP",
                "GDPC1",
                str(row.target_period),
                str(row.forecast_stage),
                row.forecast_date,
                "Bridge",
                fallback,
                raw_changed,
            )
        )

        if int(row.dfm_present) == 1:
            record = audit_dfm(
                rt, lv, gdp_definitions, period, row.forecast_date
            )
            results.append(
                add_common(
                    record,
                    "GDP",
                    "GDPC1",
                    str(row.target_period),
                    str(row.forecast_stage),
                    row.forecast_date,
                    "DFM",
                    fallback,
                    raw_changed,
                )
            )

        if n % 50 == 0:
            print(f"GDP origins audited: {n}/{len(gdp_origins)}")

    # Inflation
    for n, row in enumerate(
        inflation_origins.itertuples(index=False), start=1
    ):
        rt, lv, fallback, raw_changed = snapshots_for_date(
            row.forecast_date, inf_series
        )
        period = pd.Period(str(row.target_period), freq="M")

        record = audit_monthly_builder(
            rt,
            lv,
            build_inflation_dataset,
            str(row.target_series),
            period,
        )
        results.append(
            add_common(
                record,
                "Inflation",
                str(row.target_series),
                str(row.target_period),
                str(row.forecast_stage),
                row.forecast_date,
                "InflationDataset",
                fallback,
                raw_changed,
            )
        )

        if n % 100 == 0:
            print(
                f"Inflation origins audited: "
                f"{n}/{len(inflation_origins)}"
            )

    # Labour
    for n, row in enumerate(
        labour_origins.itertuples(index=False), start=1
    ):
        rt, lv, fallback, raw_changed = snapshots_for_date(
            row.forecast_date, lab_series
        )
        period = pd.Period(str(row.target_period), freq="M")

        record = audit_monthly_builder(
            rt,
            lv,
            build_labour_dataset,
            str(row.target_series),
            period,
        )
        results.append(
            add_common(
                record,
                "Labour",
                str(row.target_series),
                str(row.target_period),
                str(row.forecast_stage),
                row.forecast_date,
                "LabourDataset",
                fallback,
                raw_changed,
            )
        )

        if n % 100 == 0:
            print(
                f"Labour origins audited: "
                f"{n}/{len(labour_origins)}"
            )

    audit = pd.DataFrame(results)

    audit["paired_success"] = (
        (audit["rt_status"] == "ok")
        & (audit["lv_status"] == "ok")
    ).astype(int)

    audit["numeric_change_detected"] = (
        audit[
            [
                "changed_training_features",
                "changed_target_history",
                "changed_forecast_features",
            ]
        ]
        .fillna(0)
        .gt(0)
        .any(axis=1)
        .astype(int)
    )

    audit.to_csv(
        output_dir / "vintage_input_invariance_audit.csv",
        index=False,
    )

    summary = (
        audit.groupby(["domain", "builder"], dropna=False)
        .agg(
            origins=("forecast_date", "size"),
            rt_success=("rt_status", lambda x: int((x == "ok").sum())),
            lv_success=("lv_status", lambda x: int((x == "ok").sum())),
            paired_success=("paired_success", "sum"),
            structure_pass=("structure_equal", "sum"),
            imputation_pass=("imputation_equal", "sum"),
            latest_period_pass=("latest_period_equal", "sum"),
            numeric_change_origins=("numeric_change_detected", "sum"),
            raw_fallback_rows=("raw_fallback_rows", "sum"),
        )
        .reset_index()
    )

    summary.to_csv(
        output_dir / "vintage_input_invariance_summary.csv",
        index=False,
    )

    print()
    print("=" * 78)
    print("RAW MASK AUDIT")
    print("=" * 78)
    print(raw_audit.to_string(index=False))

    if not fallback_manifest.empty:
        print()
        print("Fallback keys:")
        print(fallback_manifest.to_string(index=False))

    print()
    print("=" * 78)
    print("MODEL-INPUT INVARIANCE SUMMARY")
    print("=" * 78)
    print(summary.to_string(index=False))

    print()
    print(f"Frozen latest extract SHA256: {frozen_sha}")

    # Hard scientific gates.
    raw_fail = bool(
        (raw_audit["final_missing_values"].astype(float) != 0).any()
    )

    model_fail = audit.loc[
        (audit["rt_status"] == "ok")
        & (
            (audit["lv_status"] != "ok")
            | (audit["structure_equal"] != 1)
            | (audit["imputation_equal"] != 1)
            | (audit["latest_period_equal"] != 1)
        )
    ]

    rt_fail = audit.loc[audit["rt_status"] != "ok"]

    if raw_fail:
        print("\nFAIL: final masked-LV panel still has missing values.")
        return 2

    if not rt_fail.empty:
        print("\nFAIL: production-origin RT builder failures detected:")
        print(
            rt_fail[
                [
                    "domain",
                    "builder",
                    "target_series",
                    "target_period",
                    "forecast_stage",
                    "forecast_date",
                    "rt_error",
                ]
            ].to_string(index=False)
        )
        return 3

    if not model_fail.empty:
        print("\nFAIL: RT/LV model-input invariance violation:")
        print(
            model_fail[
                [
                    "domain",
                    "builder",
                    "target_series",
                    "target_period",
                    "forecast_stage",
                    "forecast_date",
                    "rt_status",
                    "lv_status",
                    "structure_equal",
                    "imputation_equal",
                    "latest_period_equal",
                    "lv_error",
                ]
            ].to_string(index=False)
        )
        return 4

    print()
    print("=" * 78)
    print("VINTAGE INPUT INVARIANCE AUDIT COMPLETED SUCCESSFULLY")
    print("=" * 78)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())