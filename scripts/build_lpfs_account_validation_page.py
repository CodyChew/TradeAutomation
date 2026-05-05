from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import (
    dashboard_base_css,
    dashboard_header_html,
    metric_glossary_html,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "account_validation.html"
AUDIT_ROOT = REPO_ROOT / "reports" / "mt5_account_validation" / "lpfs_new_account"
NEW_ACCOUNT_REPORT_ROOT = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_experiment_v22_new_mt5_account"
COMMISSION_SENSITIVITY_ROOT = REPO_ROOT / "reports" / "strategies" / "lp_force_strike_account_commission_sensitivity"
BASELINE_CONFIG = REPO_ROOT / "configs" / "strategies" / "lp_force_strike_experiment_v22_lp_fs_separation.json"
NEW_ACCOUNT_CONFIG = REPO_ROOT / "configs" / "strategies" / "lp_force_strike_experiment_v22_new_mt5_account.example.json"
FTMO_COMMISSION_SOURCE = "https://ftmo.com/en/trading-updates/trading-update-25-sep-2025/"
IC_COMMISSION_SOURCE = "https://www.icmarkets.com/global/en/trading-pricing/spreads"


FALLBACK_AUDIT = {
    "account": {
        "company": "Raw Trading Ltd",
        "currency": "USD",
        "server": "ICMarketsSC-MT5-2",
    },
    "summary": {
        "symbols_available": 28,
        "symbols_missing": 0,
        "symbols_not_visible": 0,
        "symbols_requested": 28,
        "timeframe_probes": 140,
        "timeframe_probes_failed": 0,
        "timeframe_probes_ok": 140,
        "timeframes": ["H4", "H8", "H12", "D1", "W1"],
    },
    "symbol_specs": [
        {
            "volume_min": 0.01,
            "volume_step": 0.01,
            "trade_stops_level": 0,
            "trade_freeze_level": 0,
            "filling_mode": 2,
            "trade_contract_size": 100000.0,
        }
    ],
}

FALLBACK_DATASET_PULL = [
    {
        "coverage_start_utc": "2016-05-09T00:00:00+00:00",
        "coverage_end_utc": "2026-05-05T12:00:00+00:00",
        "rows": 15548,
        "status": "ok",
        "symbol": "AUDCAD",
        "timeframe": "H4",
    }
]

FALLBACK_COMPARISON = {
    "metrics": [
        {"metric": "trades", "baseline": 11834.0, "new_account": 11937.0, "delta": 103.0},
        {"metric": "total_net_r", "baseline": 1487.5480671924233, "new_account": 2010.5920812372938, "delta": 523.0440140448704},
        {"metric": "avg_net_r", "baseline": 0.12570120561031126, "new_account": 0.1684336165902064, "delta": 0.042732410979895136},
        {"metric": "win_rate", "baseline": 0.5837417610275477, "new_account": 0.5909357459998325, "delta": 0.007193984972284739},
        {"metric": "profit_factor", "baseline": 1.289241400249402, "new_account": 1.4057272048660299, "delta": 0.11648580461662794},
        {"metric": "max_drawdown_r", "baseline": 26.04029021072313, "new_account": 18.0, "delta": -8.040290210723128},
        {
            "metric": "bucket_efficient_reserved_max_drawdown_pct",
            "baseline": 5.075853010179827,
            "new_account": 4.100972595869134,
            "delta": -0.974880414310693,
        },
    ]
}

FALLBACK_COMMISSION_SENSITIVITY = {
    "variant": "exclude_lp_pivot_inside_fs",
    "comparison": [
        {"metric": "trades", "baseline": 11834.0, "new_account": 11937.0, "delta": 103.0},
        {"metric": "win_rate", "baseline": 0.5836572587459862, "new_account": 0.5908519728575019, "delta": 0.007194714111515732},
        {"metric": "total_net_r", "baseline": 1141.7552826970334, "new_account": 1531.1315888012118, "delta": 389.3763061041784},
        {"metric": "avg_net_r", "baseline": 0.09648092637291139, "new_account": 0.1282677045154739, "delta": 0.031786778142562505},
        {"metric": "profit_factor", "baseline": 1.21565037619627, "new_account": 1.2966597561956792, "delta": 0.08100937999940916},
        {"metric": "max_drawdown_r", "baseline": 29.9235970006661, "new_account": 24.10738622153326, "delta": -5.816210779132838},
        {"metric": "return_to_drawdown_r", "baseline": 38.155683044107896, "new_account": 63.5129654758495, "delta": 25.357282431741602},
        {"metric": "total_commission_r", "baseline": 345.79278449539004, "new_account": 479.4604924360819, "delta": 133.66770794069186},
        {"metric": "avg_commission_r", "baseline": 0.02922027923739987, "new_account": 0.0401659120747325, "delta": 0.010945632837332634},
    ],
    "risk_bucket_study": {
        "comparison": [
            {
                "comparison_label": "Adopted live row",
                "baseline_h4_h8_risk_pct": 0.20,
                "baseline_h12_d1_risk_pct": 0.30,
                "baseline_w1_risk_pct": 0.75,
                "new_account_h4_h8_risk_pct": 0.20,
                "new_account_h12_d1_risk_pct": 0.30,
                "new_account_w1_risk_pct": 0.75,
                "total_return_pct_baseline": 305.0964701406732,
                "total_return_pct_new_account": 386.84202957214984,
                "total_return_pct_delta": 81.74555943147664,
                "reserved_max_drawdown_pct_baseline": 11.225293202720891,
                "reserved_max_drawdown_pct_new_account": 7.226066149705824,
                "return_to_reserved_drawdown_baseline": 27.179376487620036,
                "return_to_reserved_drawdown_new_account": 53.53424969516759,
            },
            {
                "comparison_label": "Growth alternative",
                "baseline_h4_h8_risk_pct": 0.25,
                "baseline_h12_d1_risk_pct": 0.30,
                "baseline_w1_risk_pct": 0.60,
                "new_account_h4_h8_risk_pct": 0.25,
                "new_account_h12_d1_risk_pct": 0.30,
                "new_account_w1_risk_pct": 0.60,
                "total_return_pct_baseline": 327.20349878056766,
                "total_return_pct_new_account": 426.7029784739505,
                "total_return_pct_delta": 99.49947969338285,
                "reserved_max_drawdown_pct_baseline": 10.824374148310895,
                "reserved_max_drawdown_pct_new_account": 9.551263380078398,
                "return_to_reserved_drawdown_baseline": 30.228398824483225,
                "return_to_reserved_drawdown_new_account": 44.67503004512981,
            },
            {
                "comparison_label": "Highest-return practical row",
                "baseline_h4_h8_risk_pct": 0.20,
                "baseline_h12_d1_risk_pct": 0.20,
                "baseline_w1_risk_pct": 0.75,
                "new_account_h4_h8_risk_pct": 0.25,
                "new_account_h12_d1_risk_pct": 0.30,
                "new_account_w1_risk_pct": 0.75,
                "total_return_pct_baseline": 253.22551278103117,
                "total_return_pct_new_account": 433.92742920933813,
                "total_return_pct_delta": 180.70191642830696,
                "reserved_max_drawdown_pct_baseline": 9.771102501770125,
                "reserved_max_drawdown_pct_new_account": 9.551263380078396,
                "return_to_reserved_drawdown_baseline": 25.915756459944724,
                "return_to_reserved_drawdown_new_account": 45.43141696986441,
            },
        ]
    },
}


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _read_json(path: Path, fallback: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return fallback


def _latest_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    dirs = [path for path in root.iterdir() if path.is_dir()]
    return max(dirs, key=lambda path: path.name) if dirs else None


def _latest_new_account_run() -> Path | None:
    dirs = []
    if NEW_ACCOUNT_REPORT_ROOT.exists():
        for path in NEW_ACCOUNT_REPORT_ROOT.iterdir():
            if path.is_dir() and (path / "comparison_to_current_v22" / "comparison_summary.json").exists():
                dirs.append(path)
    return max(dirs, key=lambda path: path.name) if dirs else None


def _fmt_number(value: Any, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _escape(value)
    return f"{number:,.{digits}f}"


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return _escape(value)


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return _escape(value)


def _fmt_plain_pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return _escape(value)


def _metric_map(comparison: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("metric")): row for row in comparison.get("metrics", [])}


def _metric_rows_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("metric")): row for row in rows}


def _metric_row(metrics: dict[str, dict[str, Any]], key: str, label: str, formatter: Any) -> list[str]:
    row = metrics.get(key, {})
    return [
        label,
        formatter(row.get("baseline")),
        formatter(row.get("new_account")),
        formatter(row.get("delta")),
    ]


def _table(headers: list[str], rows: list[list[str]], *, class_name: str = "data-table") -> str:
    head = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"""
      <div class="table-scroll">
        <table class="{_escape(class_name)}">
          <thead><tr>{head}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    """


def _kpis(items: list[tuple[str, str, str]]) -> str:
    return "\n".join(
        f"""
        <article class="kpi">
          <span>{_escape(label)}</span>
          <strong>{_escape(value)}</strong>
          <div class="kpi-note">{_escape(note)}</div>
        </article>
        """
        for label, value, note in items
    )


def _unique_values(rows: list[dict[str, Any]], key: str) -> str:
    values = sorted({row.get(key) for row in rows if row.get(key) is not None})
    if not values:
        return "n/a"
    return ", ".join(_fmt_number(value, 2).rstrip("0").rstrip(".") for value in values)


def _coverage_summary(dataset_pull: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [row for row in dataset_pull if row.get("status") == "ok"]
    starts = [str(row.get("coverage_start_utc")) for row in ok_rows if row.get("coverage_start_utc")]
    ends = [str(row.get("coverage_end_utc")) for row in ok_rows if row.get("coverage_end_utc")]
    return {
        "total": len(dataset_pull),
        "ok": len(ok_rows),
        "failed": len(dataset_pull) - len(ok_rows),
        "start": min(starts) if starts else "n/a",
        "end": max(ends) if ends else "n/a",
        "rows": sum(int(row.get("rows") or 0) for row in ok_rows),
    }


def _short_path(path: Path | None) -> str:
    if path is None:
        return "fallback values"
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _costs(config_path: Path) -> dict[str, Any]:
    config = _read_json(config_path, {})
    return config.get("costs", {})


def _risk_schedule(row: dict[str, Any], prefix: str) -> str:
    return " / ".join(
        [
            _fmt_plain_pct(row.get(f"{prefix}_h4_h8_risk_pct"), 2),
            _fmt_plain_pct(row.get(f"{prefix}_h12_d1_risk_pct"), 2),
            _fmt_plain_pct(row.get(f"{prefix}_w1_risk_pct"), 2),
        ]
    )


def _risk_bucket_rows(rows: list[dict[str, Any]]) -> list[list[str]]:
    selected = [
        row
        for row in rows
        if row.get("comparison_label") in {"Adopted live row", "Growth alternative", "Highest-return practical row"}
    ]
    return [
        [
            _escape(row.get("comparison_label", "")),
            _escape(_risk_schedule(row, "baseline")),
            _escape(_risk_schedule(row, "new_account")),
            _fmt_plain_pct(row.get("total_return_pct_baseline")),
            _fmt_plain_pct(row.get("total_return_pct_new_account")),
            _fmt_plain_pct(row.get("reserved_max_drawdown_pct_baseline")),
            _fmt_plain_pct(row.get("reserved_max_drawdown_pct_new_account")),
            _fmt_number(row.get("return_to_reserved_drawdown_baseline"), 2),
            _fmt_number(row.get("return_to_reserved_drawdown_new_account"), 2),
        ]
        for row in selected
    ]


def _risk_bucket_detail_schedule(row: dict[str, Any]) -> str:
    return " / ".join(
        [
            _fmt_plain_pct(row.get("lower_risk_pct"), 2),
            _fmt_plain_pct(row.get("middle_risk_pct"), 2),
            _fmt_plain_pct(row.get("w1_risk_pct"), 2),
        ]
    )


def _risk_bucket_decision_rows(account_rows: dict[str, Any]) -> list[list[str]]:
    candidates = [
        (
            "Adopted FTMO-style reference",
            "adopted_live_row",
            "Keeps the current live bucket shape; smoother IC drawdown and highest return/DD among growth-relevant rows.",
        ),
        (
            "IC growth practical",
            "highest_return_practical_row",
            "Recommended for ICMarketsSC-MT5-2 when growth is acceptable: best practical return, under 10% reserved DD, under 6% max open risk.",
        ),
        (
            "Conservative efficiency",
            "most_efficient_practical_row",
            "Best return/DD and shortest underwater period, but gives up too much growth for the stated IC account objective.",
        ),
        (
            "Lower-W1 growth alternative",
            "growth_alternative",
            "Nearly the same drawdown as the IC recommendation but lower return, so keep it as a fallback if W1 exposure needs trimming.",
        ),
    ]
    rows: list[list[str]] = []
    for label, key, decision in candidates:
        row = account_rows.get(key)
        if not isinstance(row, dict):
            continue
        rows.append(
            [
                _escape(label),
                _escape(_risk_bucket_detail_schedule(row)),
                _fmt_plain_pct(row.get("total_return_pct")),
                _fmt_plain_pct(row.get("reserved_max_drawdown_pct")),
                _fmt_plain_pct(row.get("max_reserved_open_risk_pct")),
                _fmt_plain_pct(row.get("worst_month_pct")),
                f"{_fmt_number(row.get('reserved_longest_underwater_days'), 0)} days",
                _escape(decision),
            ]
        )
    return rows


def build_account_validation_page(output: Path = DEFAULT_OUTPUT) -> Path:
    audit_dir = _latest_dir(AUDIT_ROOT)
    new_run_dir = _latest_new_account_run()
    commission_dir = _latest_dir(COMMISSION_SENSITIVITY_ROOT)

    audit = _read_json(audit_dir / "account_audit.json", FALLBACK_AUDIT) if audit_dir else FALLBACK_AUDIT
    dataset_pull = (
        _read_json(audit_dir / "dataset_pull_result.json", FALLBACK_DATASET_PULL)
        if audit_dir
        else FALLBACK_DATASET_PULL
    )
    comparison = (
        _read_json(new_run_dir / "comparison_to_current_v22" / "comparison_summary.json", FALLBACK_COMPARISON)
        if new_run_dir
        else FALLBACK_COMPARISON
    )
    commission_sensitivity = (
        _read_json(commission_dir / "commission_sensitivity_summary.json", FALLBACK_COMMISSION_SENSITIVITY)
        if commission_dir
        else FALLBACK_COMMISSION_SENSITIVITY
    )

    account = audit.get("account", {})
    summary = audit.get("summary", {})
    specs = audit.get("symbol_specs", [])
    coverage = _coverage_summary(dataset_pull)
    metrics = _metric_map(comparison)
    commission_metrics = _metric_rows_map(commission_sensitivity.get("comparison", []))
    risk_study = commission_sensitivity.get("risk_bucket_study", {})
    risk_comparison_rows = _risk_bucket_rows(risk_study.get("comparison", []))
    risk_decision_rows = _risk_bucket_decision_rows(risk_study.get("new_account", {}))
    new_costs = _costs(NEW_ACCOUNT_CONFIG)
    baseline_costs = _costs(BASELINE_CONFIG)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    comparison_rows = [
        _metric_row(metrics, "trades", "Trades", _fmt_int),
        _metric_row(metrics, "total_net_r", "Total R", lambda value: f"{_fmt_number(value, 1)}R"),
        _metric_row(metrics, "avg_net_r", "Average R", lambda value: f"{_fmt_number(value, 4)}R"),
        _metric_row(metrics, "win_rate", "Win rate", _fmt_pct),
        _metric_row(metrics, "profit_factor", "Profit factor", lambda value: _fmt_number(value, 3)),
        _metric_row(metrics, "max_drawdown_r", "Max drawdown", lambda value: f"{_fmt_number(value, 1)}R"),
        _metric_row(
            metrics,
            "bucket_efficient_reserved_max_drawdown_pct",
            "Efficient bucket reserved DD",
            _fmt_plain_pct,
        ),
    ]

    commission_rows = [
        [
            "FTMO Forex",
            "$2.50",
            "$5.00",
            "About 0.5 pip / 5 points on USD-quoted 1-lot FX pairs",
            f'<a href="{FTMO_COMMISSION_SOURCE}">FTMO trading update</a>',
        ],
        [
            "IC Markets Raw Spread MetaTrader",
            "$3.50",
            "$7.00",
            "About 0.7 pip / 7 points on USD-quoted 1-lot FX pairs",
            f'<a href="{IC_COMMISSION_SOURCE}">IC Markets spreads page</a>',
        ],
    ]

    cost_rows = [
        [
            "Current V22 FTMO-backed baseline",
            _escape(str(baseline_costs.get("use_candle_spread", "n/a"))),
            _escape(str(baseline_costs.get("round_turn_commission_points", "n/a"))),
            _escape(str(baseline_costs.get("entry_slippage_points", "n/a"))),
            _escape(str(baseline_costs.get("exit_slippage_points", "n/a"))),
        ],
        [
            "IC Markets Raw Spread rerun",
            _escape(str(new_costs.get("use_candle_spread", "n/a"))),
            _escape(str(new_costs.get("round_turn_commission_points", "n/a"))),
            _escape(str(new_costs.get("entry_slippage_points", "n/a"))),
            _escape(str(new_costs.get("exit_slippage_points", "n/a"))),
        ],
    ]

    adjusted_rows = [
        _metric_row(commission_metrics, "trades", "Trades", _fmt_int),
        _metric_row(commission_metrics, "total_net_r", "Total R after commission", lambda value: f"{_fmt_number(value, 1)}R"),
        _metric_row(commission_metrics, "avg_net_r", "Average R after commission", lambda value: f"{_fmt_number(value, 4)}R"),
        _metric_row(commission_metrics, "win_rate", "Win rate", _fmt_pct),
        _metric_row(commission_metrics, "profit_factor", "Profit factor", lambda value: _fmt_number(value, 3)),
        _metric_row(commission_metrics, "max_drawdown_r", "Max drawdown", lambda value: f"{_fmt_number(value, 1)}R"),
        _metric_row(commission_metrics, "return_to_drawdown_r", "Return / DD", lambda value: _fmt_number(value, 2)),
        _metric_row(commission_metrics, "total_commission_r", "Total modeled commission", lambda value: f"{_fmt_number(value, 1)}R"),
        _metric_row(commission_metrics, "avg_commission_r", "Average commission per trade", lambda value: f"{_fmt_number(value, 4)}R"),
    ]

    spec_rows = [
        ["Volume min", _escape(_unique_values(specs, "volume_min"))],
        ["Volume step", _escape(_unique_values(specs, "volume_step"))],
        ["Volume max", _escape(_unique_values(specs, "volume_max"))],
        ["Stops level", _escape(_unique_values(specs, "trade_stops_level"))],
        ["Freeze level", _escape(_unique_values(specs, "trade_freeze_level"))],
        ["Filling modes", _escape(_unique_values(specs, "filling_mode"))],
        ["Contract size", _escape(_unique_values(specs, "trade_contract_size"))],
    ]

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LPFS Account Validation</title>
  <style>
    {dashboard_base_css(table_min_width="760px", extra_css="""
    .source-note {
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }
    .split-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(330px, 100%), 1fr));
      gap: 14px;
    }
    .source-list {
      margin: 0;
      padding-left: 20px;
      color: var(--muted);
    }
    .source-list a {
      color: var(--accent);
      font-weight: 700;
    }
    """)}
  </style>
</head>
<body>
  {dashboard_header_html(
      title="LPFS Account Validation",
      subtitle_html="Local IC Markets Raw Spread validation alongside the current FTMO-backed V22 baseline. This page is the dashboard entry for broker-data comparison and commission caveats before any new-account execution work.",
      current_page="account_validation.html",
      section_links=[
          ("#account-audit", "Account Audit"),
          ("#broker-data", "Broker Data"),
          ("#v22-comparison", "V22 Comparison"),
          ("#commission", "Commission"),
          ("#commission-adjusted", "Adjusted Net"),
          ("#risk-buckets", "Risk Buckets"),
          ("#cost-model", "Cost Model"),
          ("#next-actions", "Next Actions"),
      ],
  )}
  <main>
    <section id="account-audit" aria-labelledby="account-audit-title">
      <h2 id="account-audit-title">Read-Only Account Audit</h2>
      <p class="note">This validation was run on the local PC MT5 terminal. It did not change the VPS MT5 login and did not touch the guarded <code>LPFS_Live</code> runner.</p>
      <div class="kpis">
        {_kpis([
          ("Broker server", str(account.get("server", "n/a")), str(account.get("company", "Raw Trading Ltd"))),
          ("Account currency", str(account.get("currency", "n/a")), "Non-secret account metadata only"),
          ("Symbols visible", f"{summary.get('symbols_available', 0)}/{summary.get('symbols_requested', 0)}", "28-pair LPFS FX universe"),
          ("Timeframe probes", f"{summary.get('timeframe_probes_ok', 0)}/{summary.get('timeframe_probes', 0)}", "H4/H8/H12/D1/W1"),
        ])}
      </div>
      {_table(["Spec", "Audited Values"], spec_rows, class_name="data-table spec-table")}
      <p class="source-note">Audit artifact: <code>{_escape(_short_path(audit_dir))}</code></p>
    </section>

    <section id="broker-data" aria-labelledby="broker-data-title">
      <h2 id="broker-data-title">Broker Data Pull</h2>
      <div class="kpis">
        {_kpis([
          ("Datasets written", f"{coverage['ok']}/{coverage['total']}", f"{coverage['failed']} failed"),
          ("Total rows", _fmt_int(coverage["rows"]), "Across all pulled frames"),
          ("Coverage start", str(coverage["start"])[:10], "Earliest OK frame"),
          ("Coverage end", str(coverage["end"])[:10], "Latest OK frame"),
        ])}
      </div>
      <p class="note">Dataset path is intentionally separate from the FTMO-backed dataset: <code>data/raw/lpfs_new_mt5_account/forex</code>.</p>
    </section>

    <section id="v22-comparison" aria-labelledby="v22-comparison-title">
      <h2 id="v22-comparison-title">V22 LP/FS Separation: IC Markets vs Current Baseline</h2>
      <p class="note">The baseline contract remains V13 mechanics + V15 risk buckets + V22 LP/FS separation. The IC run compares broker-feed behavior, not final account profitability.</p>
      {_table(["Metric", "Current V22 Baseline", "IC Markets Raw Spread", "Delta"], comparison_rows, class_name="data-table comparison-table")}
      <p class="source-note">Comparison artifact: <code>{_escape(_short_path(new_run_dir / "comparison_to_current_v22" if new_run_dir else None))}</code></p>
    </section>

    <section id="commission" aria-labelledby="commission-title">
      <h2 id="commission-title">Commission Comparison</h2>
      <p class="note warning">Commission is materially different. FTMO currently documents Forex at $2.50 per lot per side, while IC Markets Raw Spread MetaTrader documents $3.50 per lot per side. IC is $2.00 more expensive per 1-lot round turn, about 40% higher before pair-specific pip-value effects.</p>
      {_table(["Account / Broker", "Per Lot Per Side", "Round Turn Per Lot", "Rough FX Point Equivalent", "Official Source"], commission_rows, class_name="data-table commission-table")}
      <p class="source-note">Point equivalents assume a USD account and a USD-quoted major where one 1-lot pip is about $10. Crosses and non-USD profit currencies need symbol-specific conversion.</p>
    </section>

    <section id="commission-adjusted" aria-labelledby="commission-adjusted-title">
      <h2 id="commission-adjusted-title">Commission-Adjusted V22 Result</h2>
      <p class="note">This symbol-aware overlay applies $5.00 round-turn commission per lot to the FTMO-backed baseline and $7.00 round-turn commission per lot to the IC Markets Raw Spread account. The selected variant is the adopted V22 LP/FS-separated baseline.</p>
      {_table(["Metric", "FTMO Baseline", "IC Markets Raw Spread", "Delta"], adjusted_rows, class_name="data-table adjusted-table")}
      <p class="source-note">Sensitivity artifact: <code>{_escape(_short_path(commission_dir))}</code>. Script: <code>scripts/run_lpfs_account_commission_sensitivity.py</code>.</p>
    </section>

    <section id="risk-buckets" aria-labelledby="risk-buckets-title">
      <h2 id="risk-buckets-title">Risk Bucket Study</h2>
      <p class="note">The same V15 64-row H4/H8, H12/D1, and W1 risk grid was rerun on commission-adjusted R streams. The current FTMO live reference remains <code>0.20% / 0.30% / 0.75%</code>. For ICMarketsSC-MT5-2, the analysis recommendation is the separate growth-practical bucket <code>0.25% / 0.30% / 0.75%</code>.</p>
      <p class="note warning">The per-trade cap is an execution guardrail, not a backtest signal rule. It defaults to <code>0.75%</code>; the ignored IC local dry-run config raises <code>max_risk_pct_per_trade</code> to <code>1.50%</code> only for scale-2 order-check validation.</p>
      {_table(["Row", "FTMO Buckets", "IC Buckets", "FTMO Return", "IC Return", "FTMO Reserved DD", "IC Reserved DD", "FTMO Return/DD", "IC Return/DD"], risk_comparison_rows, class_name="data-table risk-table")}
      <h3>IC decision candidates</h3>
      {_table(["Decision", "IC Buckets", "IC Return", "IC Reserved DD", "Max Open Risk", "Worst Month", "Reserved Underwater", "Use"], risk_decision_rows, class_name="data-table risk-decision-table")}
      <p class="source-note">Interpretation: IC Markets keeps the FTMO-style row structurally intact after commission and improves that row from 305.10% to 386.84% total return while reducing reserved DD from 11.23% to 7.23%. Because the IC account can accept more growth, the recommended IC analysis bucket is 0.25% / 0.30% / 0.75%: 433.93% return, 9.55% reserved DD, 5.80% max open risk, -4.46% worst month, and 153 reserved underwater days. More aggressive H12/D1 0.40% or 0.50% rows are not recommended because they breach the 6% practical max-open-risk cap.</p>
    </section>

    <section id="cost-model" aria-labelledby="cost-model-title">
      <h2 id="cost-model-title">Backtest Cost Model Used Here</h2>
      <p class="note warning">The original V22 comparison included candle spreads but did not include explicit commission or slippage. The commission-adjusted section above is now the net-R reference for broker comparison, but it is still an overlay on historical trade rows rather than a dry-run or live-send approval.</p>
      {_table(["Run", "use_candle_spread", "round_turn_commission_points", "entry_slippage_points", "exit_slippage_points"], cost_rows, class_name="data-table cost-table")}
      <div class="split-grid">
        <article class="fact">
          <span>Current dry-run evidence</span>
          <strong>3 order_check passes</strong>
          <p class="source-note">Latest scale-2 IC dry-run saw AUDCHF H8, GBPCAD H12, and NZDCHF W1 setups. All three created pending intents and passed MT5 order_check.</p>
        </article>
        <article class="fact">
          <span>Local smoke live-send</span>
          <strong>sent, canceled, clean</strong>
          <p class="source-note">A one-cycle local IC smoke test sent AUDCHF H8 ticket 4419969921, then the user manually canceled it. MT5 and smoke state now show 0 pending orders and 0 positions.</p>
        </article>
      </div>
    </section>

    <section id="next-actions" aria-labelledby="next-actions-title">
      <h2 id="next-actions-title">Next Actions Before Any New-Account Execution</h2>
      <ol>
        <li>Review the commission-adjusted symbol/timeframe contribution files before interpreting the portfolio-level IC improvement as robust.</li>
        <li>Keep the local IC account in manual smoke-test mode only unless a separate runtime plan is approved.</li>
        <li>Plan a separate runtime/config/account boundary before any continuous IC live-send discussion.</li>
      </ol>
      <ul class="source-list">
        <li><a href="lpfs_new_mt5_account_validation.md">New MT5 account validation workflow</a></li>
        <li><a href="strategy.html">Current strategy contract</a></li>
        <li><a href="live_ops.html">Live Ops safety boundary</a></li>
      </ul>
    </section>

    {metric_glossary_html()}
  </main>
  <footer>Generated {generated_at}. Official commission schedules can change; refresh source links before trading decisions.</footer>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LPFS account validation dashboard page.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    result = build_account_validation_page(Path(args.output))
    print(f"account_validation_page={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
