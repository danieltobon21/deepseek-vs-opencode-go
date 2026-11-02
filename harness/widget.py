"""Generate the inline chat widget from results/summary.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "results", "summary.json")))
D, G = S["direct"], S["go"]
sp = S["speed"] or []
def med(k, p):
    v = sorted([x[k] for x in sp if x["provider"] == p and x[k]])
    return v[len(v) // 2] if v else 0

cats = [c for c in ("math", "logic", "ifollow", "json", "code", "tool", "longctx") if c in D["per_cat"]]
rows = "".join(
    f"<tr><td>{c}</td><td class='n'>{D['per_cat'][c]['rate']:.0f}%</td><td class='n'>{G['per_cat'][c]['rate']:.0f}%</td></tr>"
    for c in cats)

def bar(label, a, b, unit, better_low=False, scale=None):
    m = scale or max(a, b)
    wa, wb = 100 * a / m, 100 * b / m
    return f"""<div class="row"><span class="lbl">{label}</span>
      <div class="bars"><div class="bwrap"><div class="bar a" style="width:{wa:.0f}%"></div><em>directo {a:.2f}{unit}</em></div>
      <div class="bwrap"><div class="bar b" style="width:{wb:.0f}%"></div><em>go {b:.2f}{unit}</em></div></div></div>"""

speed_html = bar("Latencia mediana", D["lat"]["median"], G["lat"]["median"], " s")
speed_html += bar("Prompt 58K tokens", 2.07, 5.16, " s")
speed_html += bar("TTFB streaming", med("ttfb", "direct"), med("ttfb", "go"), " s")
speed_html += bar("Throughput (mayor = mejor)", med("tok_s", "direct"), med("tok_s", "go"), " tok/s")

tc = S["turn_cost"]
html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
:root {{ color-scheme: light dark; }}
body {{ font: 13px/1.45 var(--app-font, system-ui); color: var(--foreground); background: transparent; margin: 0; padding: 2px 0 6px; }}
h3 {{ font-size: 13px; margin: 14px 0 6px; letter-spacing: .02em; text-transform: uppercase; color: var(--muted-foreground); font-weight: 600; }}
.verdict {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:4px; }}
.card {{ border:1px solid var(--border); border-radius:10px; padding:8px 12px; background:var(--card); }}
.card b {{ font-size:17px; display:block; }}
.card span {{ color: var(--muted-foreground); font-size:11px; }}
table {{ border-collapse: collapse; width: 100%; max-width: 420px; }}
td, th {{ padding: 3px 8px 3px 0; border-bottom: 1px solid var(--border); text-align:left; font-size:12px; }}
th {{ color: var(--muted-foreground); font-weight: 600; }}
td.n {{ text-align:right; font-variant-numeric: tabular-nums; }}
.row {{ display:flex; align-items:center; gap:10px; margin:5px 0; max-width:520px; }}
.lbl {{ width:150px; font-size:12px; color:var(--muted-foreground); }}
.bars {{ flex:1; }}
.bwrap {{ display:flex; align-items:center; gap:6px; margin:2px 0; }}
.bar {{ height:9px; border-radius:3px; }}
.a {{ background: var(--accent); opacity:.95; }}
.b {{ background: var(--foreground); opacity:.45; }}
em {{ font-style:normal; font-size:11px; color:var(--muted-foreground); white-space:nowrap; }}
.note {{ color:var(--muted-foreground); font-size:11px; margin-top:8px; }}
</style></head><body>
<div class="verdict">
  <div class="card"><b>{S['main_totals']['direct']['rate']:.1f}% / {S['main_totals']['go']['rate']:.1f}%</b><span>aciertos directo / go · {S['main_totals']['direct']['n']} c/u</span></div>
  <div class="card"><b>+28%</b><span>latencia extra de Go</span></div>
  <div class="card"><b>2.5×</b><span>más lento con 58K tokens</span></div>
  <div class="card"><b>$10/mes</b><span>plan Go vs ${tc['direct_offpeak']*1000:.2f}/1.000 turnos</span></div>
</div>
<h3>Calidad por categoría</h3>
<table><tr><th>categoría</th><th style="text-align:right">directo</th><th style="text-align:right">go</th></tr>{rows}</table>
<h3>Velocidad</h3>{speed_html}
<h3>Costo por turno típico (in 69K, 98% cache, out 603)</h3>
<table>
<tr><th>escenario</th><th style="text-align:right">USD/turno</th><th style="text-align:right">USD/1.000</th></tr>
<tr><td>directo off-peak</td><td class="n">${tc['direct_offpeak']:.5f}</td><td class="n">${tc['direct_offpeak']*1000:.2f}</td></tr>
<tr><td>directo pico</td><td class="n">${tc['direct_peak']:.5f}</td><td class="n">${tc['direct_peak']*1000:.2f}</td></tr>
<tr><td>Go (deducción del plan, 0.6×)</td><td class="n">${tc['go_allowance']:.5f}</td><td class="n">${tc['go_allowance']*1000:.2f}</td></tr>
</table>
<div class="note">Mismo modelo (logprobs coinciden), distinto camino: el relay añade ~0.4 s de latencia en prompts cortos y ~3 s en prompts de 58K.</div>
</body></html>"""
open(os.path.join(HERE, "widget.html"), "w").write(html)
print(os.path.join(HERE, "widget.html"), len(html))
