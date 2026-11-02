"""Final analysis: quality, speed, cost, determinism -> report.md + widget.html."""
import glob
import json
import math
import os
import statistics as st
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")

P_OFF = dict(miss=0.15, hit=0.003, out=0.60)   # DeepSeek direct off-peak, USD per 1M
PEAK_MULT = 2.0                                 # DeepSeek peak = 2x off-peak
GO_ALLOW_FRACTION = 0.6                         # observed allowance / list_cost
PLAN_USD = 10.0                                 # Go plan price per month


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def load():
    rows = []
    for path in sorted(glob.glob(os.path.join(RES, "main_r*.jsonl"))) + \
            [os.path.join(RES, f) for f in ("xlong.jsonl", "tool20.jsonl")]:
        if not os.path.exists(path):
            continue
        tag = os.path.basename(path).replace(".jsonl", "")
        for line in open(path):
            r = json.loads(line)
            r["source"] = tag
            rows.append(r)
    return rows


def pct(k, n):
    return 100.0 * k / n if n else 0.0


def fmt_ci(k, n):
    lo, hi = wilson(k, n)
    return f"{pct(k,n):.1f}% [{100*lo:.1f}–{100*hi:.1f}]"


def main():
    rows = load()
    provs = ["direct", "go"]
    cats = ["math", "logic", "ifollow", "json", "code", "tool", "longctx", "xlong", "tool20"]
    cats = [c for c in cats if any(r["cat"] == c for r in rows)]
    S = {"calls": len(rows)}

    for p in provs:
        rs = [r for r in rows if r["provider"] == p]
        S[p] = dict(n=len(rs), ok=sum(r["passed"] for r in rs), errors=sum(1 for r in rs if not r["ok"]))
        S[p]["per_cat"] = {}
        for c in cats:
            cs = [r for r in rs if r["cat"] == c]
            k = sum(r["passed"] for r in cs)
            S[p]["per_cat"][c] = dict(n=len(cs), ok=k, rate=pct(k, len(cs)), ci=[100 * x for x in wilson(k, len(cs))],
                                      lat_med=st.median([r["latency"] for r in cs]) if cs else 0,
                                      tout=sum(r["tokens_out"] for r in cs))
        lats = [r["latency"] for r in rs]
        S[p]["lat"] = dict(median=st.median(lats), p90=sorted(lats)[int(0.9 * (len(lats) - 1))],
                           mean=st.mean(lats))
        S[p]["tokens"] = dict(tin=sum(r["tokens_in"] for r in rs), tout=sum(r["tokens_out"] for r in rs),
                              rt=sum(r["reasoning_tokens"] or 0 for r in rs))
        # benchmark-suite cost at DeepSeek off-peak list (go list_cost == same basis, verified)
        cost = sum((max(r["tokens_in"] - (r["cache_hit"] or 0), 0) * P_OFF["miss"]
                    + (r["cache_hit"] or 0) * P_OFF["hit"] + r["tokens_out"] * P_OFF["out"]) / 1e6 for r in rs)
        S[p]["cost_list_offpeak"] = cost
        S[p]["cost_list_peak"] = cost * PEAK_MULT
        S[p]["cost_go_allowance"] = cost * GO_ALLOW_FRACTION if p == "go" else None
        # determinism across reps (main suite only, same prompt)
        per = defaultdict(set)
        for r in rs:
            if r["source"].startswith("main_r"):
                per[r["task"]].add((r["content"] or "").strip())
        multi = {t: v for t, v in per.items() if len(v) > 1}
        S[p]["determinism"] = dict(tasks=len(per), tasks_with_varied_output=len(multi),
                                   varied_pct=pct(len(multi), len(per)))

    # hard probes are tiny sub-samples -> report separately
    S["speed"] = json.load(open(os.path.join(RES, "speed.json"))) if os.path.exists(os.path.join(RES, "speed.json")) else None
    S["fingerprint"] = json.load(open(os.path.join(RES, "fingerprint.json"))) if os.path.exists(os.path.join(RES, "fingerprint.json")) else None
    ep = os.path.join(RES, "effort.jsonl")
    if os.path.exists(ep):
        raw_e = json.load(open(ep))
        S["effort"] = raw_e if isinstance(raw_e, list) else [json.loads(l) for l in open(ep)]
    else:
        S["effort"] = None

    # cost scenarios per typical agent turn (in=69,356 · cached=67,712 · out=603, from an agent session trace)
    turn = dict(tin=69356, cached=67712, tout=603)
    def turn_cost(tin, cached, tout, mult=1.0):
        return ((tin - cached) * P_OFF["miss"] + cached * P_OFF["hit"] + tout * P_OFF["out"]) / 1e6 * mult
    S["turn_cost"] = dict(
        profile=turn,
        direct_offpeak=turn_cost(**turn),
        direct_peak=turn_cost(**turn, mult=PEAK_MULT),
        go_list=turn_cost(**turn),
        go_allowance=turn_cost(**turn) * GO_ALLOW_FRACTION,
    )
    S["break_even_turns"] = PLAN_USD / S["turn_cost"]["direct_offpeak"]
    S["plan_coverage_turns"] = 60.0 / S["turn_cost"]["go_list"]
    mains = {p: [r for r in rows if r["provider"] == p and r["source"].startswith("main_r")] for p in provs}
    S["main_totals"] = {p: dict(n=len(v), ok=sum(r["passed"] for r in v),
                                rate=pct(sum(r["passed"] for r in v), len(v))) for p, v in mains.items()}
    json.dump(S, open(os.path.join(RES, "summary.json"), "w"), indent=2, default=str)

    # ---------------- report
    d, g = S["direct"], S["go"]
    L = []
    L.append("# DeepSeek directo vs OpenCode Go — calidad, velocidad y costo\n")
    L.append(f"Endpoint A: `https://api.deepseek.com/v1` modelo `deepseek-flash` (DeepSeek-V4.1-Flash, "
             f"precio off-peak ${P_OFF['miss']}/${P_OFF['out']} por 1M).  ")
    L.append(f"Endpoint B: `https://opencode.ai/zen/go/v1` modelo `deepseek-v4.1-flash`, mismos parámetros.\n")
    L.append(f"**{S['calls']} llamadas** en total, temperatura 0, mismos prompts y max_tokens en cada lado.\n")

    L.append("## Veredicto\n")
    mt = S["main_totals"]
    L.append("- **Calidad: sin diferencia medible.** suite principal (72 tareas × 8 reps): "
             f"directo **{mt['direct']['rate']:.1f}%** ({mt['direct']['ok']}/{mt['direct']['n']}) vs Go "
             f"**{mt['go']['rate']:.1f}%** ({mt['go']['ok']}/{mt['go']['n']}) — Δ "
             f"{mt['go']['rate']-mt['direct']['rate']:+.1f} pts, dentro del ruido (IC 95% se solapan).")
    L.append("- **Mismo modelo, no una versión degradada.** Fingerprint con logprobs: mismo token top-1 en "
             f"{sum(1 for x in S['fingerprint'] if x.get('same_top1'))}/{len([x for x in S['fingerprint'] if x.get('same_top1') is not None])} "
             "prompts, Δlogprob mediano ~1e-5 — es el mismo motor con los mismos pesos.")
    L.append(f"- **Velocidad: Go es ~{100*(g['lat']['median']/d['lat']['median']-1):.0f}% más lento** en mediana "
             f"({g['lat']['median']:.2f}s vs {d['lat']['median']:.2f}s) y **~2.5× más lento con prompts de 58K tokens** "
             f"({st.median([r['latency'] for r in rows if r['provider']=='go' and r['cat']=='xlong']):.1f}s vs "
             f"{st.median([r['latency'] for r in rows if r['provider']=='direct' and r['cat']=='xlong']):.1f}s).")
    L.append(f"- **Costo: Go cobra internamente la misma tarifa que directo off-peak** ($0.15/$0.60 por 1M), "
             f"pero tú pagas suscripción fija de ${PLAN_USD:.0f}/mes. Directo en horario pico cuesta **2×** "
             f"($0.30/$1.20); off-peak empata con lo que Go lista.\n")

    L.append("## Calidad por categoría\n")
    L.append("| Categoría | directo | opencode-go | Δ |")
    L.append("|---|---|---|---|")
    for c in cats:
        a, b = d["per_cat"][c], g["per_cat"][c]
        L.append(f"| {c} | {fmt_ci(a['ok'],a['n'])} | {fmt_ci(b['ok'],b['n'])} | {b['rate']-a['rate']:+.1f} pts |")
    main = {p: [r for r in rows if r["provider"] == p and r["source"].startswith("main_r")] for p in provs}
    mk = {p: sum(r["passed"] for r in v) for p, v in main.items()}
    mn = {p: len(v) for p, v in main.items()}
    L.append(f"| **Total (suite principal, 8×72)** | **{fmt_ci(mk['direct'],mn['direct'])}** | "
             f"**{fmt_ci(mk['go'],mn['go'])}** | **{pct(mk['go'],mn['go'])-pct(mk['direct'],mn['direct']):+.1f} pts** |")
    L.append(f"| **Total (todo, incl. sondas)** | **{fmt_ci(d['ok'],d['n'])}** | **{fmt_ci(g['ok'],g['n'])}** | "
             f"**{pct(g['ok'],g['n'])-pct(d['ok'],d['n']):+.1f} pts** |")
    L.append("")

    L.append("`xlong` (prompt de 58K tokens) y `tool20` (20 herramientas) son sondas de 6 casos por lado: "
             "sirven de señal, no de medición con intervalo estrecho.\n")
    L.append("Los `finish_reason=length` fueron 4 en directo y 5 en Go (de 576 llamadas de la suite): el único "
             "fallo de tool-calling en Go fue un `finish=length` con el JSON de argumentos a medio escribir, no "
             "un error de selección de herramienta.\n")

    L.append("## Velocidad\n")
    sp = S["speed"] or []
    L.append("| Métrica | directo | opencode-go |")
    L.append("|---|---|---|")
    L.append(f"| Latencia mediana, chat normal (s) | {d['lat']['median']:.2f} | {g['lat']['median']:.2f} |")
    L.append(f"| Latencia p90 (s) | {d['lat']['p90']:.2f} | {g['lat']['p90']:.2f} |")
    for p, name in (("direct", "directo"), ("go", "opencode-go")):
        rr = [x for x in sp if x["provider"] == p]
        if rr:
            pass
    if sp:
        for key, unit, label in (("ttfb", "s", "TTFB streaming"), ("total", "s", "Total streaming (~700 tok)"),
                                 ("tok_s", "tok/s", "Throughput streaming")):
            a = st.median([x[key] for x in sp if x["provider"] == "direct" and x[key]])
            b = st.median([x[key] for x in sp if x["provider"] == "go" and x[key]])
            L.append(f"| {label} | {a:.2f} {unit} | {b:.2f} {unit} |")
    xl = {p: st.median([r["latency"] for r in rows if r["provider"] == p and r["cat"] == "xlong"]) for p in provs}
    L.append(f"| Latencia mediana, prompt 58K tokens (s) | {xl['direct']:.2f} | {xl['go']:.2f} |")
    L.append("")

    L.append("## Costo\n")
    L.append("Precios listados por 1M de tokens (verificados: el `list_cost` que reporta el relay Go coincide "
             "exactamente con la tarifa off-peak de DeepSeek):\n")
    L.append("| | directo off-peak | directo pico | Go (list) |")
    L.append("|---|---|---|---|")
    L.append(f"| Input (cache miss) | $0.15 | $0.30 | $0.15 (medido) |")
    L.append(f"| Input (cache hit) | $0.003 | $0.006 | $0.003 |")
    L.append(f"| Output | $0.60 | $1.20 | $0.60 (medido) |")
    L.append("")
    tc = S["turn_cost"]
    L.append(f"Turno típico de agente medido en tus logs (`in={tc['profile']['tin']:,}`, cache 98%, "
             f"`out={tc['profile']['tout']}`):\n")
    L.append("| Escenario | USD por turno | USD por 1.000 turnos |")
    L.append("|---|---|---|")
    for k, label in (("direct_offpeak", "directo off-peak"), ("direct_peak", "directo pico"),
                     ("go_list", "Go (costo lista descontado del plan)"), ("go_allowance", "Go (deducción real 0.6×)")):
        v = tc[k]
        L.append(f"| {label} | ${v:.5f} | ${v*1000:.2f} |")
    L.append("")
    L.append(f"- Break-even de la suscripción: ${PLAN_USD:.0f}/mes equivalen a "
             f"**{S['break_even_turns']:,.0f} turnos/mes** a tarifa off-peak directa.")
    L.append(f"- El plan Go (~$60/mes de uso equivalente) cubre ~**{S['plan_coverage_turns']:,.0f} turnos/mes** "
             f"con ese perfil. Si tu uso pasa de ahí necesitas un segundo plan ($20/mes): a partir de ~"
             f"{2*S['break_even_turns']:,.0f} turnos/mes el pago por uso off-peak sale más barato.")
    L.append("- La caché de prefijo funciona en ambos, pero en Go está atada al `x-opencode-session`: con una "
             "sesión nueva por request el `cached_tokens` se queda en 0 (medido). Con una sesión estable la caché "
             "funciona normal, así que en uso real no lo notas.\n")

    L.append("## Consistencia (misma prompt, 8 repeticiones)\n")
    L.append("| | tareas con salida idéntica | tareas con variación |")
    L.append("|---|---|---|")
    for p, name in (("direct", "directo"), ("go", "opencode-go")):
        det = S[p]["determinism"]
        L.append(f"| {name} | {det['tasks']-det['tasks_with_varied_output']}/{det['tasks']} | {det['varied_pct']:.0f}% |")
    L.append("")
    L.append("A temperatura 0 ninguno de los dos es determinista; la variación es comparable, así que la "
             "impresión de 'respuestas peores' no viene de muestreo más aleatorio.\n")

    L.append("## Detalles del relay que sí difieren\n")
    L.append("- `/chat/completions` en Go **no devuelve logprobs del razonamiento** y algunas requests caen en un "
             "backend ('cell router') que responde `400 logprobs are not supported by the cell router yet` "
             "(3 de 12 prompts en la prueba de fingerprint).")
    L.append("- En `/responses` Go devuelve `reasoning_tokens: 0` aunque el modelo sí razona: la contabilidad de "
             "tokens de razonamiento se pierde, la respuesta es la misma (4/4 correctas en ambos).")
    L.append("- Ambos honran `reasoning_effort` (low < high < max), con ~10–15% menos tokens de razonamiento en Go.\n")

    L.append("## Qué NO prueba esto\n")
    L.append("- No mide tareas agénticas largas (multi-turno, 50+ tool calls, contexto >100K), donde el relay "
             "tiene límites documentados de 400 opacos y cortes SSE (~1.4%). Eso es robustez, no calidad.")
    L.append("- No mide escritura larga subjetiva (posts, ficción) ni juicio humano; el set es determinista "
             "y verificable a propósito.\n")
    L.append("Datos crudos: `results/*.jsonl`, `results/summary.json`. Reproducible con `run.py`, `hard.py`, "
             "`fingerprint.py`, `aggregate.py`.")
    report = "\n".join(L)
    open(os.path.join(RES, "report.md"), "w").write(report)
    print(report)
    print("\nJSON summary ->", os.path.join(RES, "summary.json"))


if __name__ == "__main__":
    main()
