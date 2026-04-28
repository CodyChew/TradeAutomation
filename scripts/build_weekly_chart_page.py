from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import sys

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "shared" / "market_data_lab" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_data_lab import load_dataset_config, rates_parquet_path


def _weekly_symbol_data(data_root: Path, symbol: str) -> list[dict[str, float | str]]:
    path = rates_parquet_path(data_root, symbol, "W1")
    frame = pd.read_parquet(path, columns=["time_utc", "open", "high", "low", "close"])
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True)
    frame = frame.sort_values("time_utc").reset_index(drop=True)
    rows = []
    for row in frame.itertuples(index=False):
        rows.append(
            {
                "time": row.time_utc.strftime("%Y-%m-%d"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
            }
        )
    return rows


def _load_weekly_data(config_path: Path) -> dict[str, list[dict[str, float | str]]]:
    config = load_dataset_config(config_path)
    data_root = Path(config.data_root)
    payload = {}
    for symbol in config.symbols:
        payload[symbol] = _weekly_symbol_data(data_root, symbol)
    return payload


def _page_template(title: str, data: dict[str, list[dict[str, float | str]]]) -> str:
    payload = json.dumps(data, separators=(",", ":"))
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --ink: #1e2428;
      --muted: #6a7278;
      --line: #d9ddd7;
      --green: #18895a;
      --red: #b64242;
      --blue: #315f9e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
    }}
    header {{
      padding: 18px 22px 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    main {{
      padding: 16px 22px 22px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 12px;
    }}
    select, button {{
      min-height: 34px;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      border-radius: 6px;
      padding: 0 10px;
      font-size: 14px;
    }}
    button {{
      cursor: pointer;
    }}
    button:hover, select:hover {{
      border-color: #aab2aa;
    }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-left: auto;
      color: var(--muted);
      font-size: 13px;
    }}
    .chart-shell {{
      position: relative;
      width: 100%;
      height: min(72vh, 760px);
      min-height: 460px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      overflow: hidden;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    .tooltip {{
      position: absolute;
      pointer-events: none;
      min-width: 170px;
      padding: 8px 9px;
      border: 1px solid rgba(0,0,0,.12);
      border-radius: 6px;
      background: rgba(255,255,255,.96);
      box-shadow: 0 4px 18px rgba(0,0,0,.08);
      font-size: 12px;
      line-height: 1.45;
      display: none;
      white-space: nowrap;
    }}
    .hint {{
      margin-top: 9px;
      color: var(--muted);
      font-size: 12px;
    }}
    @media (max-width: 720px) {{
      main {{ padding: 12px; }}
      .stats {{ width: 100%; margin-left: 0; }}
      .chart-shell {{ min-height: 390px; height: 68vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escaped_title}</h1>
  </header>
  <main>
    <div class="toolbar">
      <button id="prevButton" type="button">Prev</button>
      <select id="symbolSelect"></select>
      <button id="nextButton" type="button">Next</button>
      <select id="rangeSelect">
        <option value="all">All data</option>
        <option value="5">Last 5 years</option>
        <option value="3">Last 3 years</option>
        <option value="1">Last 1 year</option>
      </select>
      <div class="stats">
        <span id="coverage"></span>
        <span id="extremes"></span>
        <span id="bars"></span>
      </div>
    </div>
    <div class="chart-shell" id="chartShell">
      <canvas id="chart"></canvas>
      <div class="tooltip" id="tooltip"></div>
    </div>
    <div class="hint">Weekly candles from local FTMO Parquet data. Green closes above open; red closes below open.</div>
  </main>
  <script>
    const DATA = {payload};
    const symbols = Object.keys(DATA).sort();
    const select = document.getElementById('symbolSelect');
    const rangeSelect = document.getElementById('rangeSelect');
    const prevButton = document.getElementById('prevButton');
    const nextButton = document.getElementById('nextButton');
    const canvas = document.getElementById('chart');
    const shell = document.getElementById('chartShell');
    const tooltip = document.getElementById('tooltip');
    const coverage = document.getElementById('coverage');
    const extremes = document.getElementById('extremes');
    const bars = document.getElementById('bars');
    const ctx = canvas.getContext('2d');
    let hoverIndex = null;

    for (const symbol of symbols) {{
      const option = document.createElement('option');
      option.value = symbol;
      option.textContent = symbol;
      select.appendChild(option);
    }}

    function visibleRows() {{
      const rows = DATA[select.value] || [];
      const range = rangeSelect.value;
      if (range === 'all' || rows.length === 0) return rows;
      const last = new Date(rows[rows.length - 1].time + 'T00:00:00Z');
      const cutoff = new Date(last);
      cutoff.setUTCFullYear(cutoff.getUTCFullYear() - Number(range));
      return rows.filter(row => new Date(row.time + 'T00:00:00Z') >= cutoff);
    }}

    function priceDecimals() {{
      return select.value.includes('JPY') ? 3 : 5;
    }}

    function fitCanvas() {{
      const ratio = window.devicePixelRatio || 1;
      const rect = shell.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      canvas.style.width = rect.width + 'px';
      canvas.style.height = rect.height + 'px';
    }}

    function draw() {{
      fitCanvas();
      const rows = visibleRows();
      const rect = shell.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, w, h);

      if (!rows.length) return;
      const left = 58;
      const right = 16;
      const top = 18;
      const bottom = 36;
      const plotW = w - left - right;
      const plotH = h - top - bottom;
      const lows = rows.map(row => row.low);
      const highs = rows.map(row => row.high);
      let minPrice = Math.min(...lows);
      let maxPrice = Math.max(...highs);
      const pad = (maxPrice - minPrice) * 0.05 || Math.abs(maxPrice) * 0.01 || 1;
      minPrice -= pad;
      maxPrice += pad;
      const decimals = priceDecimals();
      const xStep = plotW / rows.length;
      const bodyW = Math.max(2, Math.min(9, xStep * 0.66));
      const yOf = price => top + (maxPrice - price) / (maxPrice - minPrice) * plotH;
      const xOf = index => left + index * xStep + xStep / 2;

      ctx.strokeStyle = '#e4e7e2';
      ctx.lineWidth = 1;
      ctx.fillStyle = '#687077';
      ctx.font = '12px Arial';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      for (let i = 0; i <= 5; i++) {{
        const y = top + (plotH / 5) * i;
        const price = maxPrice - (maxPrice - minPrice) / 5 * i;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(w - right, y);
        ctx.stroke();
        ctx.fillText(price.toFixed(decimals), left - 8, y);
      }}

      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      let lastYearX = -999;
      for (let i = 0; i < rows.length; i++) {{
        const year = rows[i].time.slice(0, 4);
        const prevYear = i === 0 ? null : rows[i - 1].time.slice(0, 4);
        if (i === 0 || year !== prevYear) {{
          const x = xOf(i);
          if (x - lastYearX > 42) {{
            ctx.fillText(year, x, h - bottom + 12);
            ctx.strokeStyle = '#eef0ed';
            ctx.beginPath();
            ctx.moveTo(x, top);
            ctx.lineTo(x, h - bottom);
            ctx.stroke();
            lastYearX = x;
          }}
        }}
      }}

      for (let i = 0; i < rows.length; i++) {{
        const row = rows[i];
        const x = xOf(i);
        const up = row.close >= row.open;
        const color = up ? '#18895a' : '#b64242';
        const yHigh = yOf(row.high);
        const yLow = yOf(row.low);
        const yOpen = yOf(row.open);
        const yClose = yOf(row.close);
        const bodyTop = Math.min(yOpen, yClose);
        const bodyBottom = Math.max(yOpen, yClose);

        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        ctx.fillStyle = color;
        ctx.fillRect(x - bodyW / 2, bodyTop, bodyW, Math.max(1, bodyBottom - bodyTop));
      }}

      if (hoverIndex !== null && hoverIndex >= 0 && hoverIndex < rows.length) {{
        const x = xOf(hoverIndex);
        ctx.strokeStyle = '#315f9e';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, h - bottom);
        ctx.stroke();
      }}

      const first = rows[0];
      const last = rows[rows.length - 1];
      coverage.textContent = `${{first.time}} to ${{last.time}}`;
      extremes.textContent = `Low ${{Math.min(...lows).toFixed(decimals)}} / High ${{Math.max(...highs).toFixed(decimals)}}`;
      bars.textContent = `${{rows.length}} weekly bars`;
    }}

    function updateTooltip(event) {{
      const rows = visibleRows();
      if (!rows.length) return;
      const rect = canvas.getBoundingClientRect();
      const left = 58;
      const right = 16;
      const plotW = rect.width - left - right;
      const x = event.clientX - rect.left;
      const idx = Math.max(0, Math.min(rows.length - 1, Math.floor((x - left) / (plotW / rows.length))));
      hoverIndex = idx;
      const row = rows[idx];
      const decimals = priceDecimals();
      tooltip.innerHTML = `<strong>${{select.value}} ${{row.time}}</strong><br>` +
        `O ${{row.open.toFixed(decimals)}}<br>` +
        `H ${{row.high.toFixed(decimals)}}<br>` +
        `L ${{row.low.toFixed(decimals)}}<br>` +
        `C ${{row.close.toFixed(decimals)}}`;
      const tx = Math.min(rect.width - 190, Math.max(8, event.clientX - rect.left + 12));
      const ty = Math.min(rect.height - 120, Math.max(8, event.clientY - rect.top + 12));
      tooltip.style.left = tx + 'px';
      tooltip.style.top = ty + 'px';
      tooltip.style.display = 'block';
      draw();
    }}

    function changeSymbol(delta) {{
      const current = symbols.indexOf(select.value);
      const next = (current + delta + symbols.length) % symbols.length;
      select.value = symbols[next];
      hoverIndex = null;
      tooltip.style.display = 'none';
      draw();
    }}

    select.addEventListener('change', () => {{ hoverIndex = null; tooltip.style.display = 'none'; draw(); }});
    rangeSelect.addEventListener('change', () => {{ hoverIndex = null; tooltip.style.display = 'none'; draw(); }});
    prevButton.addEventListener('click', () => changeSymbol(-1));
    nextButton.addEventListener('click', () => changeSymbol(1));
    canvas.addEventListener('mousemove', updateTooltip);
    canvas.addEventListener('mouseleave', () => {{ hoverIndex = null; tooltip.style.display = 'none'; draw(); }});
    window.addEventListener('resize', draw);

    select.value = symbols[0];
    draw();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a static weekly candlestick chart page from local Parquet data.")
    parser.add_argument("--config", default="configs/datasets/forex_major_crosses_10y.json")
    parser.add_argument("--output", default="reports/datasets/forex_weekly_charts.html")
    args = parser.parse_args()

    data = _load_weekly_data(Path(args.config))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_page_template("FTMO Forex Weekly Candles", data), encoding="utf-8")
    total_bars = sum(len(rows) for rows in data.values())
    print(f"wrote={output}")
    print(f"symbols={len(data)} weekly_bars={total_bars}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
