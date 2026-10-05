"""One-page HTML report for ``sever-demo idea`` (Build §4.9): tables and two inline-SVG charts.

    PYTHONPATH=python uv run python -m sever_demo.render artefacts/demo/idea-nq-10k-seed42.json

Writes the report next to the JSON (``.html``) unless ``--out`` is given. No network, no scripts:
the page is self-contained.
"""

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any

Report = dict[str, Any]

CSS = """
:root { --bg:#fff; --fg:#1d1f23; --muted:#5f6670; --line:#d9dce1; --ok:#1a7f37; --bad:#c62828;
        --a:#7a5af8; --b:#e8833a; --c:#1a7f37; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14161a; --fg:#e6e8eb; --muted:#9aa1ab; --line:#2c3038; --ok:#4cc970; --bad:#ff6b6b;
          --a:#a08bff; --b:#f2a46b; --c:#4cc970; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif;
       max-width:1000px; margin:0 auto; padding:24px 16px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 8px; }
.muted { color:var(--muted); } .ok { color:var(--ok); font-weight:600; }
.bad { color:var(--bad); font-weight:600; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { text-align:left; padding:5px 8px; border-bottom:1px solid var(--line); }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
code { font-size:12px; } .wrap { overflow-x:auto; }
svg text { fill:var(--fg); font:12px system-ui, sans-serif; }
"""


def _e(x: object) -> str:
    return html.escape(str(x))


def _short(h: str) -> str:
    return f"{h[:8]}…{h[-4:]}" if len(h) > 12 else h


def _mark(ok: bool) -> str:
    return '<span class="ok">✓</span>' if ok else '<span class="bad">✗</span>'


def _table(head: list[str], rows: list[list[str]], num: set[int] | None = None) -> str:
    num = num or set()
    th = "".join(f"<th{' class=num' if i in num else ''}>{h}</th>" for i, h in enumerate(head))
    body = "".join(
        "<tr>"
        + "".join(f"<td{' class=num' if i in num else ''}>{c}</td>" for i, c in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return f'<div class="wrap"><table><tr>{th}</tr>{body}</table></div>'


def _ghost_chart(r: Report) -> str:
    """Log-scale bars: each system's distance from the survivors-only summary, per touched group.
    SEVER's distance is exactly 0 and is drawn as a labelled zero, not a bar."""
    rows = r["ghost"]["per_group"]
    vals = [
        v for g in rows for v in (g["soft_delete_distance"], g["float_mean_max_abs_diff"]) if v > 0
    ]
    if not rows or not vals:
        return ""
    lo = math.floor(math.log10(min(vals)))
    hi = math.ceil(math.log10(max(vals)))
    hi = max(hi, lo + 1)
    w, left, bar, gap = 640, 190, 9, 10
    plot = w - left - 70
    h = 30 + len(rows) * (3 * bar + gap) + 20

    def x(v: float) -> float:
        return left + plot * (math.log10(v) - lo) / (hi - lo)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="ghost distances">']
    for p in range(lo, hi + 1):
        xp = x(10.0**p)
        parts.append(
            f'<line x1="{xp:.1f}" y1="20" x2="{xp:.1f}" y2="{h - 18}" stroke="var(--line)"/>'
            f'<text x="{xp:.1f}" y="{h - 4}" text-anchor="middle">1e{p}</text>'
        )
    y = 26
    series = (
        ("soft_delete_distance", "var(--a)"),
        ("float_mean_max_abs_diff", "var(--b)"),
        ("sever_max_abs_diff", "var(--c)"),
    )
    for g in rows:
        parts.append(f'<text x="0" y="{y + bar * 1.6:.1f}">{_e(g["group"])}</text>')
        for key, color in series:
            v = float(g[key])
            if v > 0:
                parts.append(
                    f'<rect x="{left}" y="{y}" width="{max(x(v) - left, 1):.1f}" height="{bar - 1}"'
                    f' fill="{color}"/><text x="{x(v) + 4:.1f}" y="{y + bar - 1}">{v:.2e}</text>'
                )
            else:
                parts.append(
                    f'<text x="{left}" y="{y + bar - 1}" fill="{color}">0 (bit-identical)</text>'
                )
            y += bar
        y += gap
    parts.append("</svg>")
    legend = (
        '<p class="muted"><span style="color:var(--a)">■</span> soft-delete IVF: centroid to '
        'survivors\' mean · <span style="color:var(--b)">■</span> float running mean: max abs '
        'difference · <span style="color:var(--c)">■</span> SEVER: S against survivors-only S</p>'
    )
    return "".join(parts) + legend


def _n_chart(r: Report) -> str:
    """n before and after for each touched group."""
    rows = r["groups"]
    if not rows:
        return ""
    top = max(g["n_before"] for g in rows) or 1
    w, left, bar = 640, 190, 10
    plot = w - left - 60
    h = 10 + len(rows) * (2 * bar + 10)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="group sizes">']
    y = 6
    for g in rows:
        parts.append(f'<text x="0" y="{y + bar + 4}">{_e(g["group"])}</text>')
        for key, color in (("n_before", "var(--line)"), ("n_after", "var(--a)")):
            v = g[key]
            end = left + plot * v / top
            parts.append(
                f'<rect x="{left}" y="{y}" width="{end - left:.1f}" height="{bar - 1}"'
                f' fill="{color}"/><text x="{end + 4:.1f}" y="{y + bar - 1}">{v}</text>'
            )
            y += bar
        y += 10
    parts.append("</svg>")
    return "".join(parts)


def render(r: Report) -> str:
    """The report page."""
    b = r["build"]
    groups = [
        [
            f"<code>{_e(g['group'])}</code>",
            str(g["n_before"]),
            str(g["n_after"]),
            f"<code>{_short(g['s_sha_before'])}</code>",
            f"<code>{_short(g['s_sha_after'])}</code>",
            f"<code>{_short(g['blob_sha_after'])}</code>",
            f"<code>{_short(g['survivors_blob_sha'])}</code>",
            _mark(g["exact"]),
        ]
        for g in r["groups"]
    ]
    ghost = [
        [
            _e(s["system"]),
            "yes" if s["deleted_record_still_stored"] else "no",
            f"{s['distance']:.3e}",
            _e(s["measure"]),
        ]
        for s in r["ghost"]["summary"]
    ]
    s = r["search"]
    ex = s.get("example")
    example = ""
    if ex:
        before = ", ".join(_e(i) for i, _ in ex["before"][:5])
        after = ", ".join(_e(i) for i, _ in ex["after"][:5])
        example = (
            f"<p>{_e(ex['query'])}: before, <code>{_e(ex['deleted_record'])}</code> at rank "
            f"{ex['rank_before']} (top 5: {before}).<br>After: {after}.</p>"
        )
    u = r["untouched"]
    checks = [
        (
            "every touched group equals its survivors-only rebuild",
            all(g["exact"] for g in r["groups"]),
        ),
        (
            f"untouched groups unchanged ({u['unchanged']}/{u['groups']})",
            u["unchanged"] == u["groups"],
        ),
        (
            "second delete: AlreadyAbsent, state unchanged",
            r["second_delete"]["all_already_absent"] and r["second_delete"]["state_unchanged"],
        ),
        ("no search returns a deleted record", s["deleted_returned_after"] == 0),
        ("invariants INV-4 … INV-9", r["invariants"] == "ok"),
    ]
    check_rows = "".join(f"<li>{_mark(ok)} {_e(t)}</li>" for t, ok in checks)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEVER Idea Demo</title><style>{CSS}</style></head><body>
<h1>SEVER-DB · Part 1, The Idea</h1>
<p class="muted">data {_e(r["data"])} · seed {r["seed"]} · d = {r["d"]} · spawn size
{r["spawn_target"]} · stream {_e(r["stream_order"])} · artefact
<code>{_short(r["artefact_sha256"])}</code></p>
<ul>{check_rows}</ul>
<h2>1. Build</h2>
<p>{b["accepted"]} of {b["records"]} records accepted in {b["seconds"]:.1f} s ·
{b["frozen"]} frozen + {b["spawned"]} spawned groups (k = {b["k"]}) · N = {b["big_n"]} ·
holding area {b["holding"]} · out of distribution {b["out_of_distribution"]}
({100 * b["ood_rate"]:.2f} %)</p>
<h2>2. Target</h2>
<p>Cohort <strong>{_e(r["target"]["cohort"])}</strong>: {len(r["target"]["record_ids"])} records
({", ".join(_e(i) for i in r["target"]["record_ids"])}) in
{", ".join(f"<code>{_e(g)}</code>" for g in r["target"]["groups"])}.
<span class="muted">Rule: {_e(r["target"]["rule"])}.</span></p>
<h2>3–5. Before and after one <code>delete_user</code></h2>
{
        _table(
            [
                "group",
                "n before",
                "n after",
                "S before",
                "S after",
                "blob after",
                "survivors-only",
                "exact",
            ],
            groups,
            {1, 2},
        )
    }
{_n_chart(r)}
<p>N {r["big_n"][0]} → {r["big_n"][1]} · holding area {r["holding"]["n_before"]} →
{r["holding"]["n_after"]} ({r["holding"]["cohort_members"]} cohort record(s) there)</p>
<h2>6. The ghost <span class="muted">(P1-T14, a measure)</span></h2>
{_table(["system", "deleted record still stored", "distance", "what the distance is"], ghost, {2})}
{_ghost_chart(r)}
<h2>7. Search</h2>
<p>{s["queries"]} real queries, top {s["k"]}: {s["queries_hit_before"]} returned a cohort record
before the deletion; searches returning a deleted record after: {s["deleted_returned_after"]}
{_mark(s["deleted_returned_after"] == 0)}</p>
{example}
</body></html>
"""


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sever-demo-render", description=__doc__)
    ap.add_argument("report", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    data = json.loads(a.report.read_text(encoding="utf-8"))
    if data.get("format") != "sever-demo-idea-1":
        print(f"{a.report}: not a sever-demo idea report", file=sys.stderr)
        return 2
    out: Path = a.out or a.report.with_suffix(".html")
    out.write_text(render(data), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
