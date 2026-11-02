"""Build the static site for the DeepSeek-direct vs OpenCode-Go benchmark.

Reads the measured summary from the benchmark run and writes a sanitized, self-contained
static site (index.html, og.png, data/) into ./site.
"""
import json
import os
import subprocess

BENCH = os.path.expanduser("~/benchmarks/ds-go-vs-direct-20261102/results")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
S = json.load(open(os.path.join(BENCH, "summary.json")))
SPEED = json.load(open(os.path.join(BENCH, "speed.json")))

D, G = S["direct"], S["go"]
MAIN_D, MAIN_G = S["main_totals"]["direct"], S["main_totals"]["go"]
CATS = [("math", "Arithmetic"), ("logic", "Logic"), ("ifollow", "Instruction following"),
        ("json", "JSON schema"), ("code", "Code generation"), ("tool", "Tool calling"),
        ("longctx", "64K context")]


def med(key, prov):
    v = sorted([x[key] for x in SPEED if x["provider"] == prov and x.get(key)])
    return v[len(v) // 2]


def xlong(prov):
    rows = [json.loads(l) for l in open(os.path.join(BENCH, "xlong.jsonl"))]
    v = sorted([r["latency"] for r in rows if r["provider"] == prov])
    return v[len(v) // 2]


LAT = {
    "Median, chat": (D["lat"]["median"], G["lat"]["median"]),
    "p90, chat": (D["lat"]["p90"], G["lat"]["p90"]),
    "First token (stream)": (med("ttfb", "direct"), med("ttfb", "go")),
    "58K-token prompt": (xlong("direct"), xlong("go")),
}
TPUT = (med("tok_s", "direct"), med("tok_s", "go"))
TC = S["turn_cost"]

os.makedirs(os.path.join(OUT, "data"), exist_ok=True)

# ---------- sanitized data files
public = {
    "generated": "2026-11-02",
    "calls": S["calls"],
    "suite": {"tasks_per_provider": MAIN_D["n"], "repetitions": 8,
              "quality": {"direct": MAIN_D["rate"], "go": MAIN_G["rate"]}},
    "per_category": {c: {"direct": {"rate": D["per_cat"][c]["rate"], "ci95": D["per_cat"][c]["ci"], "n": D["per_cat"][c]["n"]},
                         "go": {"rate": G["per_cat"][c]["rate"], "ci95": G["per_cat"][c]["ci"], "n": G["per_cat"][c]["n"]}}
                     for c, _ in CATS},
    "latency_s": {k: {"direct": v[0], "go": v[1]} for k, v in LAT.items()},
    "throughput_tok_s": {"direct": TPUT[0], "go": TPUT[1]},
    "cost_usd_per_turn": TC,
    "break_even_turns_per_month": S["break_even_turns"],
}
json.dump(public, open(os.path.join(OUT, "data", "summary.json"), "w"), indent=2)

rows = []
for f in sorted(os.listdir(os.path.join(os.path.dirname(BENCH), "results"))):
    if not (f.startswith("main_r") and f.endswith(".jsonl")):
        continue
    for line in open(os.path.join(os.path.dirname(BENCH), "results", f)):
        r = json.loads(line)
        rows.append({k: r.get(k) for k in ("provider", "task", "cat", "passed", "latency", "tokens_in",
                                           "tokens_out", "reasoning_tokens", "cache_hit", "finish", "detail")})
with open(os.path.join(OUT, "data", "results.jsonl"), "w") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

# ---------- charts
def bars():
    out = []
    for label, (a, b) in LAT.items():
        m = max(a, b)
        out.append(f"""<div class="bar-row"><span class="bar-label">{label}</span>
          <div class="bar-track"><span class="bar direct" style="width:{100*a/m:.0f}%"></span><b>{a:.2f}s</b></div>
          <div class="bar-track"><span class="bar go" style="width:{100*b/m:.0f}%"></span><b>{b:.2f}s</b></div></div>""")
    return "\n".join(out)


def cat_rows():
    out = []
    for c, name in CATS:
        a, b = D["per_cat"][c], G["per_cat"][c]
        delta = b["rate"] - a["rate"]
        cls = "flat" if abs(delta) < 1 else ("up" if delta > 0 else "down")
        out.append(f"<tr><td>{name}</td><td class='num'>{a['rate']:.1f}%</td>"
                   f"<td class='num'>{b['rate']:.1f}%</td>"
                   f"<td class='num delta {cls}'>{delta:+.1f}</td></tr>")
    return "\n".join(out)


speedup = (G["lat"]["median"] / D["lat"]["median"] - 1) * 100
slow58 = LAT["58K-token prompt"][1] / LAT["58K-token prompt"][0]

CSS = """
:root{--bg:#181A1F;--panel:#1C1F26;--line:#2C313B;--fg:#ECEEF2;--muted:#9AA2B1;--accent:#FF5A1F}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:0 22px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
header{border-bottom:1px solid var(--line);padding:20px 0}
.brand{display:flex;align-items:center;gap:10px;font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.brand i{width:9px;height:9px;border-radius:2px;background:var(--accent);display:inline-block}
h1{font-size:clamp(30px,5vw,46px);line-height:1.1;letter-spacing:-.02em;margin:44px 0 14px;font-weight:650}
h1 span{color:var(--accent)}
.lede{font-size:clamp(17px,2.2vw,20px);color:var(--muted);max-width:44em;margin:0 0 26px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:30px 0 10px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stat b{display:block;font-size:clamp(20px,5.6vw,26px);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.stat span{font-size:12.5px;color:var(--muted)}
h2{font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);font-weight:600;margin:56px 0 14px}
p{margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);font-size:14.5px}
th{color:var(--muted);font-weight:600;font-size:12px;letter-spacing:.06em;text-transform:uppercase}
td.num,th.num{text-align:right}
tr:last-child td{border-bottom:none}
.flat{color:var(--muted)}.up{color:#8fd96b}.down{color:#ff8a6b}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:6px 18px 10px;overflow-x:auto}
.stat b.pair{white-space:nowrap}
.bar-row{display:grid;grid-template-columns:190px 1fr 1fr;gap:14px;align-items:center;padding:9px 0;border-bottom:1px solid var(--line)}
.bar-row:last-child{border-bottom:none}
.bar-label{font-size:14px;color:var(--fg)}
.bar-track{display:flex;align-items:center;gap:9px}
.bar{height:10px;border-radius:3px;min-width:2px}
.delta{display:table-cell}
.bar.direct{background:var(--fg);opacity:.85}
.bar.go{background:var(--accent)}
.bar-track b{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.legend{display:flex;gap:18px;font-size:12.5px;color:var(--muted);margin:4px 0 12px}
.legend i{width:10px;height:10px;border-radius:2px;display:inline-block;margin-right:6px}
.note{font-size:13px;color:var(--muted)}
ul{margin:0 0 14px;padding-left:20px}
li{margin-bottom:8px}
.kv{display:grid;grid-template-columns:auto auto;gap:4px 18px;font-size:14px}
footer{margin:64px 0 40px;padding-top:22px;border-top:1px solid var(--line);color:var(--muted);font-size:13.5px}
@media(max-width:720px){.stats{grid-template-columns:repeat(2,1fr);gap:10px}.stat{padding:11px 12px}.stat span{font-size:11.5px;line-height:1.35}.stat b.pair{font-size:19px}table{min-width:440px}th{white-space:nowrap}.bar-row{grid-template-columns:1fr;gap:6px}.bar-label{color:var(--muted);font-size:13px}}
@media(max-width:560px){.delta{display:none}table{min-width:0}td,th{padding:8px 6px;font-size:13.5px}}
"""

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DeepSeek API vs OpenCode Go — same model, different latency</title>
<meta name="description" content="Reproducible A/B test of DeepSeek's direct API against the OpenCode Go relay: 1,176 requests, deterministic grading, quality, latency and cost.">
<link rel="canonical" href="https://deepseek-vs-opencode-go.pages.dev/">
<meta property="og:type" content="article">
<meta property="og:title" content="DeepSeek API vs OpenCode Go: same model, different latency">
<meta property="og:description" content="1,176 requests, deterministic grading. Quality identical within noise; the relay adds 28% latency and 2.5x on long prompts.">
<meta property="og:image" content="https://deepseek-vs-opencode-go.pages.dev/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="DeepSeek API vs OpenCode Go: same model, different latency">
<meta name="twitter:description" content="1,176 requests, deterministic grading. Same weights, same accuracy, higher latency.">
<meta name="twitter:image" content="https://deepseek-vs-opencode-go.pages.dev/og.png">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>{CSS}</style>
</head>
<body>
<header><div class="wrap"><div class="brand"><i></i> Tobon Digital · Benchmark</div></div></header>
<main class="wrap">
  <h1>DeepSeek&nbsp;API vs OpenCode&nbsp;Go:<br><span>same model, different latency</span></h1>
  <p class="lede">There is a persistent claim that the OpenCode Go relay serves a worse DeepSeek than the direct API.
  I tested it: 1,176 requests, deterministic graders, identical prompts. The model behind both endpoints is the same one.
  What you actually feel is the wire.</p>

  <div class="stats">
    <div class="stat"><b class="pair">{MAIN_D['rate']:.1f}% / {MAIN_G['rate']:.1f}%</b><span>accuracy: direct vs Go, {MAIN_D['n']} calls each</span></div>
    <div class="stat"><b>+{speedup:.0f}%</b><span>median latency on short prompts</span></div>
    <div class="stat"><b>{slow58:.1f}×</b><span>slower on a 58K-token prompt</span></div>
    <div class="stat"><b class="pair">$0.15 / $0.60</b><span>per 1M in/out — the rate both bill internally</span></div>
  </div>

  <h2>What was measured</h2>
  <p>Two endpoints, one model family: <code>api.deepseek.com/v1</code> with <code>deepseek-flash</code> and
  <code>opencode.ai/zen/go/v1</code> with <code>deepseek-v4.1-flash</code>. Same prompts, same <code>max_tokens</code>,
  <code>temperature=0</code>, run eight times per task. Grading is programmatic — numeric answers, parsed JSON,
  generated code executed against test cases, tool-call arguments inspected — so no model judges another model.</p>
  <p>72 tasks across seven categories, plus two probes: a 58K-token needle and a 20-tool selection test.
  A separate logprob probe (one token, <code>top_logprobs=10</code>) fingerprints the engine itself.</p>

  <h2>Quality</h2>
  <div class="card">
  <table>
    <tr><th>Category</th><th class="num">Direct</th><th class="num">OpenCode Go</th><th class="num delta">Δ points</th></tr>
    {cat_rows()}
    <tr><td><strong>All</strong></td><td class="num"><strong>{MAIN_D['rate']:.1f}%</strong></td><td class="num"><strong>{MAIN_G['rate']:.1f}%</strong></td><td class="num delta flat"><strong>{MAIN_G['rate']-MAIN_D['rate']:+.1f}</strong></td></tr>
  </table>
  </div>
  <p class="note">95% confidence intervals overlap across every category. The difference is inside the noise.</p>

  <h2>The model is the same model</h2>
  <p>Asking both endpoints for one token with logprobs shows the identical top-1 token on 8 of 9 prompts, a median
  |Δlogprob| around 1e-5, and 4 of 5 shared tokens in the top-5. Different weights, a different quantization or a
  different tokenizer would show up here immediately. It does not.</p>
  <p>What does differ is sampling bookkeeping: neither endpoint is deterministic at <code>temperature=0</code>
  (31% and 32% of tasks varied across eight repetitions), so anyone comparing single responses is comparing noise.</p>

  <h2>Latency</h2>
  <div class="legend"><span><i style="background:#ECEEF2"></i>Direct</span><span><i style="background:#FF5A1F"></i>OpenCode Go</span></div>
  <div class="card">{bars()}</div>
  <p class="note">Median of all graded calls, plus the streaming probe. Throughput follows the same pattern:
  {TPUT[0]:.0f} tok/s direct vs {TPUT[1]:.0f} tok/s through the relay.</p>
  <p>The penalty grows with the prompt. On short chats it is a few hundred milliseconds; at 58K tokens it is
  three seconds per call. In a long agent session — dozens of calls per task — that is the difference the user
  actually perceives as "the model got worse".</p>

  <h2>Cost</h2>
  <p>Both endpoints bill the same internal rate: <strong>$0.15 per million input tokens</strong> (cache miss),
  <strong>$0.003</strong> (cache hit) and <strong>$0.60 per million output tokens</strong>. The relay's own
  <code>list_cost</code> field reproduces DeepSeek's off-peak price to the cent. Direct billing doubles during
  DeepSeek's peak hours; the Go plan is a flat subscription whose usage is deducted at 0.6× that list price.</p>
  <div class="card">
  <table>
    <tr><th>Scenario (typical agent turn: 69K in, 98% cached, 600 out)</th><th class="num">USD / turn</th><th class="num">USD / 1,000 turns</th></tr>
    <tr><td>Direct, off-peak</td><td class="num">${TC['direct_offpeak']:.5f}</td><td class="num">${TC['direct_offpeak']*1000:.2f}</td></tr>
    <tr><td>Direct, peak (2×)</td><td class="num">${TC['direct_peak']:.5f}</td><td class="num">${TC['direct_peak']*1000:.2f}</td></tr>
    <tr><td>Go plan, list cost</td><td class="num">${TC['go_list']:.5f}</td><td class="num">${TC['go_list']*1000:.2f}</td></tr>
    <tr><td>Go plan, deducted from quota (0.6×)</td><td class="num">${TC['go_allowance']:.5f}</td><td class="num">${TC['go_allowance']*1000:.2f}</td></tr>
  </table>
  </div>
  <p class="note">A $10/month plan breaks even against off-peak pay-as-you-go at roughly
  {S['break_even_turns']:,.0f} turns per month for this workload.</p>

  <h2>Where the relay really differs</h2>
  <ul>
    <li><strong>Prefix cache is tied to the session id.</strong> With a fresh id per request, <code>cached_tokens</code>
    stays at zero; with a stable one it caches normally (measured: 4,608 of 4,720 tokens). Clients that generate a new
    session id per call pay full input price every time.</li>
    <li><strong>Reasoning tokens disappear on <code>/responses</code>.</strong> The relay reports
    <code>reasoning_tokens: 0</code> while the model clearly reasons; <code>/chat/completions</code> reports them
    correctly. Answers are identical, accounting is not.</li>
    <li><strong>Logprobs are partially supported.</strong> Some requests land on a backend that answers
    <code>400 logprobs are not supported by the cell router yet</code>, and only content logprobs come back.</li>
    <li><strong>It trims reasoning.</strong> With the same <code>reasoning_effort</code>, Go spends 10–15% fewer
    reasoning tokens than the direct API — invisible on these tasks, relevant if you rely on deep thinking.</li>
  </ul>

  <h2>What this does not prove</h2>
  <p>It does not measure long agentic runs (50+ tool calls, 150K+ context), where relays are known to drop streams or
  return opaque 400s. That is reliability, not model quality, and it needs its own test. It also does not measure
  subjective long-form writing: the suite is deliberately deterministic so the result can be checked by anyone.</p>

  <h2>Verdict</h2>
  <p><strong>If the complaint is "the answers are worse", the data says no: it is the same model with the same
  accuracy.</strong> If the complaint is "it feels slower", that is real and measurable — +{speedup:.0f}% on short
  prompts, {slow58:.1f}× on 58K-token ones. Choose on latency and cost, not on quality.</p>

  <footer>
    <p>Run on 2 November 2026 · 1,176 requests · every graded number on this page is recomputed from the raw
    JSONL published with the code. The streaming speed test, the 58K and 20-tool probes and the logprob
    fingerprint come from <code>run.py --speed</code>, <code>hard.py</code> and <code>fingerprint.py</code>;
    rerun those to reproduce them. Benchmark and analysis by Tobon Digital.</p>
    <p><a href="https://github.com/danieltobon21/deepseek-vs-opencode-go">Source, raw data and reproduction steps →</a></p>
  </footer>
</main>
</body>
</html>
"""
open(os.path.join(OUT, "index.html"), "w").write(HTML)

# ---------- favicon
open(os.path.join(OUT, "favicon.svg"), "w").write(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" fill="#181A1F"/>'
    '<rect x="14" y="26" width="10" height="26" rx="3" fill="#ECEEF2"/>'
    '<rect x="27" y="16" width="10" height="36" rx="3" fill="#ECEEF2"/>'
    '<rect x="40" y="34" width="10" height="18" rx="3" fill="#FF5A1F"/></svg>')

# ---------- OG image (1200x630) as SVG -> PNG
OG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#181A1F"/>
<rect x="0" y="0" width="6" height="630" fill="#FF5A1F"/>
<text x="72" y="96" font-family="Helvetica,Arial,sans-serif" font-size="19" letter-spacing="4" fill="#9AA2B1">TOBON DIGITAL · BENCHMARK</text>
<text x="72" y="196" font-family="Helvetica,Arial,sans-serif" font-size="60" font-weight="bold" fill="#ECEEF2">DeepSeek API vs OpenCode Go</text>
<text x="72" y="256" font-family="Helvetica,Arial,sans-serif" font-size="34" fill="#FF5A1F">same model, different latency</text>
<text x="72" y="330" font-family="Helvetica,Arial,sans-serif" font-size="24" fill="#9AA2B1">1,176 requests · deterministic grading · 72 tasks × 8 runs</text>
<g font-family="Helvetica,Arial,sans-serif">
  <text x="72" y="436" font-size="56" font-weight="bold" fill="#ECEEF2">{MAIN_D['rate']:.1f}% / {MAIN_G['rate']:.1f}%</text>
  <text x="72" y="470" font-size="22" fill="#9AA2B1">accuracy, direct / relay</text>
  <text x="470" y="436" font-size="56" font-weight="bold" fill="#ECEEF2">+{speedup:.0f}%</text>
  <text x="470" y="470" font-size="22" fill="#9AA2B1">median latency</text>
  <text x="760" y="436" font-size="56" font-weight="bold" fill="#FF5A1F">{slow58:.1f}×</text>
  <text x="760" y="470" font-size="22" fill="#9AA2B1">slower at 58K tokens</text>
</g>
<line x1="72" y1="520" x2="1128" y2="520" stroke="#2C313B" stroke-width="2"/>
<text x="72" y="566" font-family="Helvetica,Arial,sans-serif" font-size="22" fill="#9AA2B1">Same weights, same accuracy. The relay is what you feel.</text>
</svg>"""
open(os.path.join(OUT, "og.svg"), "w").write(OG)
subprocess.run(["rsvg-convert", "-w", "1200", "-h", "630", "-o", os.path.join(OUT, "og.png"),
                os.path.join(OUT, "og.svg")], check=True)

print("built", OUT, os.path.getsize(os.path.join(OUT, "index.html")), "bytes html",
      os.path.getsize(os.path.join(OUT, "og.png")), "bytes og.png")
