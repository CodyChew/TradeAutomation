from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Any

from lp_force_strike_dashboard_metadata import dashboard_page_links, dashboard_pages, load_dashboard_metadata


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "index.html"


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _fact_grid(facts: list[list[str]]) -> str:
    return "".join(
        f'<div class="fact"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
        for label, value in facts
    )


def _card(page: dict[str, Any]) -> str:
    status_kind = page.get("status_kind", "neutral")
    return f"""
    <section class="card">
      <div class="status status-{_escape(status_kind)}">{_escape(page['status_label'])}</div>
      <h2>{_escape(page['title'])}</h2>
      <p>{_escape(page['conclusion'])}</p>
      <div class="facts">
        {_fact_grid(page.get("facts", []))}
      </div>
      <a class="button" href="{_escape(page['page'])}">Open {_escape(page['nav_label'])} Dashboard</a>
    </section>
    """


def _baseline_card(home: dict[str, Any]) -> str:
    baseline = home["current_baseline"]
    return f"""
    <section class="card featured">
      <div class="status status-active">{_escape(baseline['status_label'])}</div>
      <h2>{_escape(baseline['title'])}</h2>
      <p>{_escape(baseline['description'])}</p>
      <div class="facts">
        {_fact_grid(baseline.get("facts", []))}
      </div>
      <a class="button" href="{_escape(baseline['button_href'])}">{_escape(baseline['button_label'])}</a>
    </section>
    """


def build_index(output: Path = DEFAULT_OUTPUT) -> Path:
    metadata = load_dashboard_metadata()
    home = metadata["home"]
    pages = sorted(dashboard_pages(metadata), key=lambda page: int(page["index_order"]))
    cards = [_baseline_card(home)] + [_card(page) for page in pages]
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(home['title'])}</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #627181;
      --line: #d8e0e8;
      --accent: #22577a;
      --good: #2e7d50;
      --bad: #a23b3b;
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.5 Inter, Segoe UI, Roboto, Arial, sans-serif;
      overflow-x: hidden;
    }}
    header {{
      background: #17202a;
      color: white;
      padding: 34px max(18px, 6vw);
      border-bottom: 4px solid #57a773;
    }}
    header h1 {{
      margin: 0 0 8px;
      font-size: clamp(24px, 5vw, 30px);
    }}
    header p {{
      margin: 0;
      color: #d8e0e8;
      max-width: 920px;
      overflow-wrap: anywhere;
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }}
    nav a {{
      color: white;
      text-decoration: none;
      border: 1px solid rgba(255,255,255,.25);
      padding: 7px 10px;
      border-radius: 6px;
      background: rgba(255,255,255,.08);
      min-height: 34px;
    }}
    nav a.active {{
      background: #57a773;
      border-color: #57a773;
      color: #17202a;
      font-weight: 700;
    }}
    main {{
      padding: 28px max(18px, 6vw) 48px;
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 2px rgba(23,32,42,.05);
    }}
    .featured {{
      border-top: 4px solid var(--accent);
    }}
    .card h2 {{
      margin: 0 0 8px;
      font-size: 20px;
    }}
    .card p {{
      color: var(--muted);
      margin: 0 0 16px;
    }}
    .status {{
      display: inline-block;
      border-radius: 999px;
      padding: 5px 9px;
      margin-bottom: 10px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      color: var(--muted);
      background: #f7f9fb;
    }}
    .status-active {{
      color: var(--good);
      border-color: #b9dbc7;
      background: #edf8f1;
    }}
    .status-rejected {{
      color: var(--bad);
      border-color: #e7bcbc;
      background: #fff1f1;
    }}
    .facts {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 18px;
      font-size: 13px;
    }}
    .fact {{
      background: #f8fafb;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
    }}
    .fact strong {{
      display: block;
      font-size: 18px;
      color: var(--ink);
    }}
    a.button {{
      display: inline-block;
      background: var(--accent);
      color: white;
      text-decoration: none;
      padding: 9px 12px;
      border-radius: 6px;
      font-weight: 700;
    }}
    footer {{
      padding: 0 max(18px, 6vw) 32px;
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      header {{ padding: 24px 16px; }}
      nav a {{ flex: 1 1 auto; text-align: center; }}
      main {{ padding: 18px 12px 36px; }}
      .card {{ padding: 16px; }}
      .facts {{ grid-template-columns: 1fr; }}
      a.button {{ display: block; text-align: center; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_escape(home['title'])}</h1>
    <p>{_escape(home['intro'])}</p>
    <nav aria-label="Dashboard pages">
      {dashboard_page_links("index.html", metadata)}
    </nav>
  </header>
  <main>
    {"".join(cards)}
  </main>
  <footer>Generated dashboards are static research snapshots. Strategy behavior remains in tested Python modules.</footer>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(line.rstrip() for line in html_text.splitlines()) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the LP + Force Strike dashboard index page.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    args = parser.parse_args()
    result = build_index(Path(args.output))
    print(f"dashboard_index={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
