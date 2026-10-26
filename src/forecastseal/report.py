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


def _metric_block(led: Ledger, h: str, proto: dict, m: dict, multi: bool, compare, interim: bool, seed: int, is_measure: bool):
    """Scores, calibration and comparisons for one metric. Returns (html parts, comparison results)."""
    rows = led.items_for(h, m["name"])
    hib = m["direction"] == "higher_is_better"
    unit = "Items" if is_measure else "Events"
    losses = stats.loss_lists(rows, m["name"]) if rows else {}
    parts: list[str] = []
    comps, skipped = [], []
    for a, b in (compare or []):
        if not rows:
            skipped.append(f"{a} vs {b}: nothing recorded for this metric yet")
            continue
        try:
            comps.append(workflow.compare_logged(led, h, a, b, interim=interim, seed=seed, metric=m["name"]))
        except workflow.LedgerError as e:                    # not enough complete items yet: say so, do not abort the report
            skipped.append(f"{a} vs {b}: {e}")
    head = f'Metric: {esc(m["name"])} ({"primary" if m["primary"] else "exploratory"})' if multi else "Scores"
    if losses:
        items = []
        table = [f'<div class="scroll"><table><thead><tr><th>{"System" if is_measure else "Forecaster"}</th><th class="n">{unit}</th><th class="n">{"Mean value" if is_measure else "Mean loss"}</th><th class="n">95% interval</th></tr></thead><tbody>']
        for name, v in sorted(losses.items(), key=lambda kv: (-1 if hib else 1) * sum(kv[1]) / len(kv[1])):
            mean_v = sum(v) / len(v)
            lo, hi = stats.bootstrap_ci(v, 0.95, seed=seed) if len(v) > 1 else (mean_v, mean_v)
            items.append((name, mean_v, lo, hi))
            table.append(f'<tr><td>{esc(name)}</td><td class="n">{len(v)}</td><td class="n">{_f(mean_v)}</td><td class="n">[{_f(lo)}, {_f(hi)}]</td></tr>')
        table.append("</tbody></table></div>")
        parts.append(f'<section><h2>{head}</h2><p class="muted">{esc(workflow.direction_text(m["direction"]))}</p>' + "".join(table) +
                     f'<figure>{_score_chart(items)}<figcaption>Bars show the mean; whiskers show a 95% bootstrap interval for each one alone. Overlapping whiskers do not decide a comparison: use the paired comparison below.</figcaption></figure></section>')
        if not is_measure:
            cal_figs = []
            for name in sorted(losses):
                cal = stats.calibration([r for r in rows if r["forecaster"] == name])
                cal_figs.append(f'<figure>{_calibration_chart(name, cal)}<figcaption>{esc(_short(name, 30))} · ECE {_f(cal["ece"])} · {cal["n"]} pairs</figcaption></figure>')
            parts.append('<section><h2>Calibration</h2><div class="grid">' + "".join(cal_figs) + '</div><p class="muted">Points on the dashed diagonal mean "said 70%, happened 70% of the time". Point size shows how many forecasts fall in the bin; small points are noise.</p></section>')
    else:
        parts.append(f'<section><h2>{head}</h2><p class="muted">Nothing recorded yet.</p></section>')
    if comps:
        blocks = []
        for r in comps:
            tag = ("final analysis" if r["final"] else "INTERIM LOOK, not a verdict")
            verdict = (f'interval excludes 0; {r["better"]} is better' if r["excludes_zero"] else "interval includes 0: no difference shown") if r["final"] else "no verdict before the planned number of items"
            extra = ""
            if r["final"] and r["prior_final"] >= r["planned"]:
                extra = f'<div class="note">This is final analysis #{r["prior_final"] + 1} for this metric, but the protocol planned {r["planned"]} comparison(s). Treat the interval as too narrow.</div>'
            if r.get("margin") is not None and r["n"] > 1:
                extra += (f'<div class="note">Non-inferiority (margin {esc(r["margin"])}, sealed in the protocol): {esc(r["a"])} is not worse than {esc(r["b"])} by more than the margin: '
                          f'<b>{"yes" if r["non_inferior"] else "not shown"}</b>' + ("" if r["final"] else " (interim, not a verdict)") + '.</div>')
            if multi and not r["primary"]:
                extra += '<div class="note">Exploratory metric: no multiplicity adjustment. Do not draw conclusions from it.</div>'
            if r["n"] < 30:
                extra += '<div class="note">Fewer than 30 paired items: intervals are unreliable at this size.</div>'
            blocks.append(f'<figure><p><b>{esc(r["a"])} vs {esc(r["b"])}</b> · {esc(tag)}</p>{_interval_chart(r)}'
                          f'<figcaption>difference = {esc(r["a"])} minus {esc(r["b"])} ({"positive" if r["higher_is_better"] else "negative"} favours {esc(r["a"])}) · mean {r["mean_diff"]:+.4f} · '
                          f'{100 * (1 - r["alpha_adj"]):.2f}% interval [{r["ci"][0]:+.4f}, {r["ci"][1]:+.4f}] · {r["n"]} paired items · {esc(verdict)}</figcaption>{extra}</figure>')
        parts.append(f'<section><h2>Paired comparison{(" · " + esc(m["name"])) if multi else "s"}</h2>' + "".join(blocks) + "</section>")
    if skipped:
        parts.append('<section><h2>Comparison not run' + (f' · {esc(m["name"])}' if multi else '') + '</h2>' + "".join(f'<div class="note">{esc(s)}</div>' for s in skipped) + '</section>')
    return parts, comps, losses


def build(led: Ledger, protocol_hash: str | None = None, compare: list[tuple[str, str]] | None = None,
          interim: bool = False, seed: int = 43, now: str | None = None) -> str:
    problems = led.verify()
    protos = led.protocols()
    if protocol_hash is None:
        if len(protos) != 1:
            raise workflow.LedgerError("several protocols are registered; pass --protocol <hash>")
        protocol_hash = next(iter(protos))
    proto = workflow.protocol_of(led, protocol_hash)
    metrics = workflow.metrics_of(led, protocol_hash)
    multi = len(metrics) > 1
    is_measure = proto.get("kind", "forecast") == "measure"
    unit = "items" if is_measure else "events"
    gen = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    man = protos[protocol_hash]["body"].get("manifest")
    manifest_row = (f'<tr><th>Sealed item set</th><td>{esc(man["count"])} items · <span class="mono">{esc(man["sha256"])}</span></td></tr>' if man else "")

    blocks, all_comps, systems, items_done = [], [], set(), set()
    for m in metrics:
        parts, comps, losses = _metric_block(led, protocol_hash, proto, m, multi, compare, interim, seed, is_measure)
        blocks.append(parts)
        all_comps.extend(comps)
        systems.update(losses)
        items_done.update(r["event"] for r in led.items_for(protocol_hash, m["name"]))
    st = led.status()                      # after the comparisons above, so the analysis count includes them
    closure = led.closure(protocol_hash)
    ok = not problems
    n_primary = sum(1 for m in metrics if m["primary"])
    metric_line = (f'{len(metrics)} metrics ({n_primary} primary)' if multi else f'metric: {esc(metrics[0]["name"])} ({esc(workflow.direction_text(metrics[0]["direction"]))})')
    parts: list[str] = [f'<header><h1>{esc(proto["name"])}</h1><p class="muted">forecastseal report · {metric_line} · generated {esc(gen)}</p></header>']
    parts.append('<section><div class="cards">'
                 f'<div class="card {"ok" if ok else "bad"}"><b>Ledger</b><span>{"intact" if ok else "BROKEN"}</span></div>'
                 f'<div class="card"><b>Progress</b><span>{len(items_done)} / {proto["n_target"]}</span><br><small class="muted">{"measured items" if is_measure else "resolved events"} / planned</small></div>'
                 f'<div class="card"><b>{"Systems" if is_measure else "Forecasters"}</b><span>{len(systems)}</span></div>'
                 f'<div class="card"><b>Analyses logged</b><span>{st["analyses"]}</span></div>'
                 f'<div class="card"><b>Study</b><span>{esc(closure["body"]["kind"].replace("_", " ")) if closure else "open"}</span></div></div>')
    if not ok:
        parts.append('<div class="note"><b>The hash chain does not verify.</b> Do not trust the numbers below.<ul>' + "".join(f"<li>{esc(p)}</li>" for p in problems[:10]) + "</ul></div>")
    parts.append("</section>")

    if closure and closure["body"]["kind"] != "completed":
        cb = closure["body"]
        shrink = ""
        if 0 < cb["n_complete"] < cb["n_target"]:
            shrink = f' At the planned size the intervals would be roughly {100 * (1 - (cb["n_complete"] / cb["n_target"]) ** 0.5):.0f}% narrower, if the spread stays similar.'
        parts.append('<section><h2>This study ended early</h2><div class="note">'
                     f'<p>{esc(cb["kind"].replace("_", " ").capitalize())} at {esc(cb["n_complete"])} of {esc(cb["n_target"])} planned items. Reason on record: <b>{esc(cb["reason"])}</b></p>'
                     '<p><b>What the numbers can say:</b> the estimates and intervals so far. <b>What they cannot say:</b> that an effect is absent, or present at the planned precision. '
                     'If the study stopped because the numbers looked good, estimates tend to be exaggerated (see <code>examples/peeking_demo.py</code>).' + esc(shrink) + '</p>'
                     '<p>Treat the figures below as hints, not as a result.</p></div></section>')
    elif closure:
        parts.append(f'<section><h2>Study closed</h2><p class="muted">Completed at {esc(closure["body"]["n_complete"])} of {esc(closure["body"]["n_target"])} planned items. Reason on record: {esc(closure["body"]["reason"])}</p></section>')
    plan_rows = (f'<tr><th>Name</th><td>{esc(proto["name"])}</td></tr>'
                 + (f'<tr><th>Metrics</th><td>' + "<br>".join(f'{esc(m["name"])} · {"primary" if m["primary"] else "exploratory"} · {esc(workflow.direction_text(m["direction"]))}' for m in metrics) + "</td></tr>" if multi
                    else f'<tr><th>Metric</th><td>{esc(metrics[0]["name"])}</td></tr>')
                 + f'<tr><th>Planned {unit}</th><td>{esc(proto["n_target"])}</td></tr><tr><th>Alpha</th><td>{esc(proto["alpha"])}</td></tr>'
                 + f'<tr><th>Planned comparisons</th><td>{esc(proto.get("n_comparisons", 1))}</td></tr>'
                 + (f'<tr><th>Confirmatory family</th><td>{n_primary} primary metric(s) × {esc(proto.get("n_comparisons", 1))} comparison(s): each primary interval uses alpha / {n_primary * proto.get("n_comparisons", 1)}</td></tr>' if multi else "")
                 + manifest_row + f'<tr><th>Protocol hash</th><td class="mono">{esc(protocol_hash)}</td></tr>')
    parts.append(f'<section><h2>Sealed protocol</h2><div class="scroll"><table><tbody>{plan_rows}</tbody></table></div></section>')

    if multi and all_comps:
        rowsh = "".join(
            f'<tr><td>{esc(c["metric"])}</td><td>{"primary" if c["primary"] else "exploratory"}</td><td>{esc(c["a"])} vs {esc(c["b"])}</td><td class="n">{c["n"]}</td>'
            f'<td class="n">{c["mean_diff"]:+.4f}</td><td class="n">[{c["ci"][0]:+.4f}, {c["ci"][1]:+.4f}]</td>'
            f'<td>{(esc(c["better"]) + " is better") if (c["final"] and c["excludes_zero"]) else ("no difference shown" if c["final"] else "interim, no verdict")}</td></tr>'
            for c in sorted(all_comps, key=lambda c: (not c["primary"], c["metric"])))
        parts.append('<section><h2>Summary</h2><div class="scroll"><table><thead><tr><th>Metric</th><th>Role</th><th>Comparison</th><th class="n">Items</th><th class="n">Difference</th><th class="n">Interval</th><th>Result</th></tr></thead>'
                     f'<tbody>{rowsh}</tbody></table></div><p class="muted">Only the primary metrics support conclusions; exploratory ones are for ideas to test next.</p></section>')
    for b in blocks:
        parts.extend(b)
    if not all_comps:
        parts.append('<section><h2>Paired comparisons</h2><p class="muted">None requested. Add <code>--compare A B</code> when the planned number of items is complete (or <code>--interim</code> for a logged, non-final look).</p></section>')

    log = [e for e in led.entries() if e["type"] == "analysis"]
    if log:
        rowsh = "".join(f'<tr><td class="mono">{esc(e["ts"])}</td><td>{esc(e["body"]["kind"])}</td><td>{esc(e["body"]["what"])}{(" · " + esc(e["body"]["metric"])) if e["body"].get("metric") else ""}</td><td class="n">{esc(e["body"]["n_resolved"])}</td></tr>' for e in log)
        parts.append(f'<section><h2>Analysis log</h2><div class="scroll"><table><thead><tr><th>When</th><th>Kind</th><th>What</th><th class="n">Items</th></tr></thead><tbody>{rowsh}</tbody></table></div><p class="muted">Every look at a comparison is recorded, including interim ones.</p></section>')
    parts.append(f'<section><h2>Ledger</h2><div class="scroll"><table><tbody><tr><th>Entries</th><td>{st["entries"]}</td></tr><tr><th>Head hash</th><td class="mono">{esc(st["head"])}</td></tr></tbody></table></div>'
                 '<div class="note">Timestamps come from the local clock. To show the ledger was not changed later, publish or timestamp the head hash now and verify with <code>fseal verify --expected-head &lt;hash&gt;</code> later.</div></section>')
    parts.append(f'<p class="muted">forecastseal {esc(__version__)}</p>')
    return (f'<title>{esc(proto["name"])} · forecastseal report</title><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}"><style>{CSS}</style><main>' + "".join(parts) + "</main>")
