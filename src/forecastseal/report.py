"""Self-contained HTML report: no scripts, no external requests, every string escaped."""
from __future__ import annotations

import datetime as dt
import html
import math

from . import __version__, stats, workflow
from .ledger import Ledger

CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--fg:#14181f;--muted:#586272;--line:#d8dee5;--accent:#0a7a74;--soft:#dff1ef;--warn:#a85a06;--warnbg:#f8ead7;--bad:#b3342a;--badbg:#fbe4e1}
@media (prefers-color-scheme:dark){:root{--bg:#11161b;--panel:#181f26;--fg:#e8edf1;--muted:#9aa7b4;--line:#2b3541;--accent:#4cc7bd;--soft:#14312f;--warn:#e3a35a;--warnbg:#382a15;--bad:#ee7d72;--badbg:#3b1d1a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;padding:28px max(16px,env(safe-area-inset-right,0px)) 56px max(16px,env(safe-area-inset-left,0px))}
main{max-width:900px;margin:0 auto;display:flex;flex-direction:column;gap:30px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:0 0 8px}p{margin:0 0 8px}
.muted{color:var(--muted)}.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12.5px;word-break:break-all}
section{display:flex;flex-direction:column;gap:12px;min-width:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px;min-width:0}
.card b{display:block;font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.card span{font-size:20px;font-weight:600}
.ok{border-color:var(--accent);background:var(--soft)}.bad{border-color:var(--bad);background:var(--badbg)}
.note{background:var(--warnbg);border-left:3px solid var(--warn);padding:9px 13px;border-radius:0 6px 6px 0;font-size:14px}
.scroll{overflow-x:auto;max-width:100%;border:1px solid var(--line);border-radius:6px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--muted);background:var(--bg)}tr:last-child td{border-bottom:0}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
svg{display:block;max-width:100%;height:auto;color:var(--fg)}svg text{fill:currentColor;font-family:system-ui,sans-serif}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px}figcaption{font-size:13px;color:var(--muted)}
"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def _f(x, d=4) -> str:
    return "n/a" if (x is None or (isinstance(x, float) and math.isnan(x))) else f"{x:.{d}f}"


def _short(s: str, n: int = 26) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _score_chart(items: list[tuple[str, float, float, float]]) -> str:
    """items: (name, mean, lo, hi). The axis always includes 0 and may extend below it."""
    amin = min(0.0, min(lo for _, _, lo, _ in items))
    amax = max(0.0, max(hi for _, _, _, hi in items))
    span = (amax - amin) or 1.0
    amin -= span * 0.04 if amin < 0 else 0.0
    amax += span * 0.04
    w, lab, pad = 560, 150, 14
    h = 26 * len(items) + 34
    x = lambda v: lab + ((v - amin) / (amax - amin)) * (w - lab - pad)
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Mean value per forecaster or system with 95% bootstrap intervals">']
    for i, (name, m, lo, hi) in enumerate(items):
        y = 10 + i * 26
        bx = min(x(0), x(m))
        out.append(f'<text x="{lab - 8}" y="{y + 12}" font-size="12" text-anchor="end">{esc(_short(name))}</text>')
        out.append(f'<rect x="{bx:.1f}" y="{y}" width="{max(1.0, abs(x(m) - x(0))):.1f}" height="16" fill="var(--accent)" opacity="0.8"/>')
        out.append(f'<line x1="{x(lo):.1f}" y1="{y + 8}" x2="{x(hi):.1f}" y2="{y + 8}" stroke="currentColor" stroke-width="1.5"/>')
        out.append(f'<line x1="{x(lo):.1f}" y1="{y + 3}" x2="{x(lo):.1f}" y2="{y + 13}" stroke="currentColor" stroke-width="1.5"/>')
        out.append(f'<line x1="{x(hi):.1f}" y1="{y + 3}" x2="{x(hi):.1f}" y2="{y + 13}" stroke="currentColor" stroke-width="1.5"/>')
    base = 10 + len(items) * 26 + 6
    out.append(f'<line x1="{x(0):.1f}" y1="4" x2="{x(0):.1f}" y2="{base - 4}" stroke="currentColor" opacity="0.4"/>')
    out.append(f'<text x="{x(0):.1f}" y="{base + 12}" font-size="11" text-anchor="middle">0</text>')
    out.append(f'<text x="{w - pad}" y="{base + 12}" font-size="11" text-anchor="end">{amax:.3f}</text>')
    if amin < 0:
        out.append(f'<text x="{lab}" y="{base + 12}" font-size="11" text-anchor="start">{amin:.3f}</text>')
    out.append("</svg>")
    return "".join(out)


def _calibration_chart(name: str, cal: dict) -> str:
    s, o = 200, 34
    nmax = max((b["n"] for b in cal["bins"]), default=1)
    out = [f'<svg viewBox="0 0 {s + o + 10} {s + o + 12}" role="img" aria-label="Reliability diagram for {esc(name)}">']
    out.append(f'<rect x="{o}" y="6" width="{s}" height="{s}" fill="none" stroke="currentColor" opacity="0.3"/>')
    out.append(f'<line x1="{o}" y1="{s + 6}" x2="{o + s}" y2="6" stroke="currentColor" stroke-dasharray="4 3" opacity="0.6"/>')
    for b in cal["bins"]:
        cx, cy = o + b["mean_pred"] * s, 6 + (1 - b["freq"]) * s
        r = 2.5 + 5.5 * math.sqrt(b["n"] / nmax)
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="var(--accent)" opacity="0.75"/>')
    out.append(f'<text x="{o + s / 2}" y="{s + o + 6}" font-size="11" text-anchor="middle">predicted</text>')
    out.append(f'<text x="10" y="{6 + s / 2}" font-size="11" text-anchor="middle" transform="rotate(-90 10 {6 + s / 2})">observed</text>')
    out.append("</svg>")
    return "".join(out)


def _interval_chart(res: dict) -> str:
    lo, hi, m = res["ci"][0], res["ci"][1], res["mean_diff"]
    left, right = (res["b"], res["a"]) if res.get("higher_is_better") else (res["a"], res["b"])   # negative side, positive side
    span = max(abs(lo), abs(hi), abs(m)) * 1.35 or 1.0
    w = 560
    x = lambda v: w / 2 + v / span * (w / 2 - 20)
    return (f'<svg viewBox="0 0 {w} 70" role="img" aria-label="Difference between {esc(res["a"])} and {esc(res["b"])} with its interval">'
            f'<line x1="{w / 2}" y1="6" x2="{w / 2}" y2="40" stroke="currentColor" opacity="0.5"/>'
            f'<line x1="{x(lo):.1f}" y1="23" x2="{x(hi):.1f}" y2="23" stroke="currentColor" stroke-width="2"/>'
            f'<circle cx="{x(m):.1f}" cy="23" r="5" fill="var(--accent)"/>'
            f'<text x="20" y="62" font-size="11">← favours {esc(_short(left, 14))}</text>'
            f'<text x="{w - 20}" y="62" font-size="11" text-anchor="end">favours {esc(_short(right, 14))} →</text></svg>')


def build(led: Ledger, protocol_hash: str | None = None, compare: list[tuple[str, str]] | None = None,
          interim: bool = False, seed: int = 43, now: str | None = None) -> str:
    problems = led.verify()
    protos = led.protocols()
    if protocol_hash is None:
        if len(protos) != 1:
            raise workflow.LedgerError("several protocols are registered; pass --protocol <hash>")
        protocol_hash = next(iter(protos))
    proto = workflow.protocol_of(led, protocol_hash)
    rows = led.items_for(protocol_hash)
    metric = proto["metric"]
    is_measure = proto.get("kind", "forecast") == "measure"
    hib = proto.get("direction") == "higher_is_better"
    unit = "Items" if is_measure else "Events"
    losses = stats.loss_lists(rows, metric) if rows else {}
    n_done = len({r["event"] for r in rows})
    comps = [workflow.compare_logged(led, protocol_hash, a, b, interim=interim, seed=seed) for a, b in (compare or [])]
    st = led.status()
    gen = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    man = led.protocols()[protocol_hash]["body"].get("manifest")
    manifest_row = (f'<tr><th>Sealed item set</th><td>{esc(man["count"])} items · <span class="mono">{esc(man["sha256"])}</span></td></tr>' if man else "")
    parts: list[str] = []
    ok = not problems
    parts.append(f'<header><h1>{esc(proto["name"])}</h1><p class="muted">forecastseal report · metric: {esc(metric)} ({esc(workflow.direction_text(proto))}) · generated {esc(gen)}</p></header>')
    parts.append('<section><div class="cards">'
                 f'<div class="card {"ok" if ok else "bad"}"><b>Ledger</b><span>{"intact" if ok else "BROKEN"}</span></div>'
                 f'<div class="card"><b>Progress</b><span>{n_done} / {proto["n_target"]}</span><br><small class="muted">{"measured items" if is_measure else "resolved events"} / planned</small></div>'
                 f'<div class="card"><b>Forecasters</b><span>{len(losses)}</span></div>'
                 f'<div class="card"><b>Analyses logged</b><span>{st["analyses"]}</span></div></div>')
    if not ok:
        parts.append('<div class="note"><b>The hash chain does not verify.</b> Do not trust the numbers below.<ul>' + "".join(f"<li>{esc(p)}</li>" for p in problems[:10]) + "</ul></div>")
    parts.append("</section>")

    parts.append('<section><h2>Sealed protocol</h2><div class="scroll"><table><tbody>'
                 f'<tr><th>Name</th><td>{esc(proto["name"])}</td></tr><tr><th>Metric</th><td>{esc(metric)}</td></tr>'
                 f'<tr><th>Planned {unit.lower()}</th><td>{esc(proto["n_target"])}</td></tr><tr><th>Alpha</th><td>{esc(proto["alpha"])}</td></tr>'
                 f'<tr><th>Planned comparisons</th><td>{esc(proto.get("n_comparisons", 1))}</td></tr>'
                 f'{manifest_row}<tr><th>Protocol hash</th><td class="mono">{esc(protocol_hash)}</td></tr></tbody></table></div></section>')

    if losses:
        items = []
        table = [f'<div class="scroll"><table><thead><tr><th>Forecaster</th><th class="n">{unit}</th><th class="n">{"Mean value" if is_measure else "Mean loss"}</th><th class="n">95% interval</th></tr></thead><tbody>']
        for name, v in sorted(losses.items(), key=lambda kv: (-1 if hib else 1) * sum(kv[1]) / len(kv[1])):
            m = sum(v) / len(v)
            lo, hi = stats.bootstrap_ci(v, 0.95, seed=seed) if len(v) > 1 else (m, m)
            items.append((name, m, lo, hi))
            table.append(f'<tr><td>{esc(name)}</td><td class="n">{len(v)}</td><td class="n">{_f(m)}</td><td class="n">[{_f(lo)}, {_f(hi)}]</td></tr>')
        table.append("</tbody></table></div>")
        parts.append('<section><h2>Scores</h2>' + "".join(table) + f'<figure>{_score_chart(items)}<figcaption>Bars show the mean; whiskers show a 95% bootstrap interval for each forecaster alone. Overlapping whiskers do not decide a comparison: use the paired comparison below.</figcaption></figure></section>')
        cal_figs = []
        for name in ([] if is_measure else sorted(losses)):
            cal = stats.calibration([r for r in rows if r["forecaster"] == name])
            cal_figs.append(f'<figure>{_calibration_chart(name, cal)}<figcaption>{esc(_short(name, 30))} · ECE {_f(cal["ece"])} · {cal["n"]} pairs</figcaption></figure>')
        if not is_measure:
          parts.append('<section><h2>Calibration</h2><div class="grid">' + "".join(cal_figs) + '</div><p class="muted">Points on the dashed diagonal mean "said 70%, happened 70% of the time". Point size shows how many forecasts fall in the bin; small points are noise.</p></section>')
    else:
        parts.append('<section><h2>Scores</h2><p class="muted">No resolved events yet.</p></section>')

    if comps:
        blocks = []
        for r in comps:
            tag = ("final analysis" if r["final"] else "INTERIM LOOK, not a verdict")
            verdict = (f'interval excludes 0; {r["better"]} is better' if r["excludes_zero"] else "interval includes 0: no difference shown") if r["final"] else "no verdict before the planned number of events"
            extra = ""
            if r["final"] and r["prior_final"] >= r["planned"]:
                extra = f'<div class="note">This is final analysis #{r["prior_final"] + 1}, but the protocol planned {r["planned"]} comparison(s). Treat the interval as too narrow.</div>'
            if r["n"] < 30:
                extra += '<div class="note">Fewer than 30 paired events: intervals are unreliable at this size.</div>'
            blocks.append(f'<figure><p><b>{esc(r["a"])} vs {esc(r["b"])}</b> · {esc(tag)}</p>{_interval_chart(r)}'
                          f'<figcaption>difference = {esc(r["a"])} minus {esc(r["b"])} ({"positive" if r["higher_is_better"] else "negative"} favours {esc(r["a"])}) · mean {r["mean_diff"]:+.4f} · {100 * (1 - r["alpha_adj"]):.2f}% interval [{r["ci"][0]:+.4f}, {r["ci"][1]:+.4f}] · {r["n"]} paired events · {esc(verdict)}</figcaption>{extra}</figure>')
        parts.append("<section><h2>Paired comparisons</h2>" + "".join(blocks) + "</section>")
    else:
        parts.append('<section><h2>Paired comparisons</h2><p class="muted">None requested. Add <code>--compare A B</code> when the planned number of events is resolved (or <code>--interim</code> for a logged, non-final look).</p></section>')

    log = [e for e in led.entries() if e["type"] == "analysis"]
    if log:
        rowsh = "".join(f'<tr><td class="mono">{esc(e["ts"])}</td><td>{esc(e["body"]["kind"])}</td><td>{esc(e["body"]["what"])}</td><td class="n">{esc(e["body"]["n_resolved"])}</td></tr>' for e in log)
        parts.append(f'<section><h2>Analysis log</h2><div class="scroll"><table><thead><tr><th>When</th><th>Kind</th><th>What</th><th class="n">Events</th></tr></thead><tbody>{rowsh}</tbody></table></div><p class="muted">Every look at the comparison is recorded, including interim ones.</p></section>')

    parts.append(f'<section><h2>Ledger</h2><div class="scroll"><table><tbody><tr><th>Entries</th><td>{st["entries"]}</td></tr><tr><th>Head hash</th><td class="mono">{esc(st["head"])}</td></tr></tbody></table></div>'
                 '<div class="note">Timestamps come from the local clock. To show the ledger was not changed later, publish or timestamp the head hash now and verify with <code>fseal verify --expected-head &lt;hash&gt;</code> later.</div></section>')
    parts.append(f'<p class="muted">forecastseal {esc(__version__)}</p>')
    return (f'<title>{esc(proto["name"])} · forecastseal report</title><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}"><style>{CSS}</style><main>' + "".join(parts) + "</main>")
