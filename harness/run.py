"""Run the DeepSeek-direct vs OpenCode-Go benchmark.

Usage: python3 run.py [--pilot] [--effort] [--speed]
Writes JSONL to results/ and prints a summary.
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks as T  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)

PROVIDERS = {
    "go": dict(base="https://opencode.ai/zen/go/v1", model="deepseek-v4.1-flash", key_env="OPENCODE_GO_API_KEY"),
    "direct": dict(base="https://api.deepseek.com/v1", model="deepseek-flash", key_env="DEEPSEEK_API_KEY"),
}

# DeepSeek public list prices, USD per 1M tokens.
P_OFFPEAK = dict(inp=0.15, cache=0.003, out=0.60)
P_GO_LIST = dict(inp=0.30, out=1.20, cache=0.006)


def _load_env():
    path = os.environ.get("BENCH_ENV_FILE", ".env")
    for line in open(path):
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def call(provider, messages, max_tokens=1024, tools=None, extra=None, timeout=180):
    p = PROVIDERS[provider]
    body = {"model": p["model"], "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if extra:
        body.update(extra)
    headers = {
        "Authorization": f"Bearer {os.environ[p['key_env']]}",
        "Content-Type": "application/json",
        "User-Agent": "bench-harness/1.0",
    }
    if provider == "go":
        headers["x-opencode-session"] = "bench-" + uuid.uuid4().hex[:16]
    req = urllib.request.Request(p["base"] + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    t0 = time.time()
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            dt = time.time() - t0
            d = json.loads(raw)
            msg = d["choices"][0]["message"]
            u = d.get("usage") or {}
            oc = (u.get("opencode") or {})
            return dict(
                ok=True, http=200, latency=dt, model=d.get("model"),
                content=msg.get("content") or "",
                reasoning=(msg.get("reasoning_content") or ""),
                tool_calls=msg.get("tool_calls") or [],
                finish=d["choices"][0].get("finish_reason"),
                tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                cache_hit=(u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                reasoning_tokens=(u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
                go_list_cost=oc.get("list_cost"), go_allowance=oc.get("allowance"),
                raw_usage=u, attempts=attempt + 1,
            )
        except urllib.error.HTTPError as e:
            body_txt = e.read()[:300].decode(errors="replace")
            last = dict(ok=False, http=e.code, error=body_txt, latency=time.time() - t0)
            if e.code in (400, 401, 402, 403, 404):
                return last
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last = dict(ok=False, http=0, error=str(e)[:300], latency=time.time() - t0)
            time.sleep(1.5 * (attempt + 1))
    return last


def cost_direct(r):
    if not r.get("ok"):
        return 0.0
    hit = r.get("cache_hit") or 0
    miss = max(r.get("tokens_in", 0) - hit, 0)
    return (miss * P_OFFPEAK["inp"] + hit * P_OFFPEAK["cache"] + r.get("tokens_out", 0) * P_OFFPEAK["out"]) / 1e6


def cost_go(r):
    if not r.get("ok"):
        return 0.0
    if r.get("go_list_cost") is not None:
        return float(r["go_list_cost"])
    return (r.get("tokens_in", 0) * P_GO_LIST["inp"] + r.get("tokens_out", 0) * P_GO_LIST["out"]) / 1e6


def run_task(provider, task):
    r = call(provider, task["messages"], max_tokens=task["max_tokens"], tools=task.get("tools"))
    passed, detail = False, "call failed"
    if r.get("ok"):
        try:
            passed, detail = task["grade"](r)
        except Exception as e:
            passed, detail = False, f"grader error {e}"
    rec = dict(provider=provider, task=task["id"], cat=task["cat"], passed=bool(passed), detail=str(detail)[:200],
               **{k: r.get(k) for k in ("ok", "http", "latency", "tokens_in", "tokens_out", "cache_hit",
                                        "reasoning_tokens", "finish", "error", "model", "attempts")})
    rec["content"] = (r.get("content") or "")[:1500]
    rec["tool_calls"] = r.get("tool_calls") or []
    rec["cost"] = cost_go(r) if provider == "go" else cost_direct(r)
    rec["cost_alt"] = cost_direct(r) if provider == "go" else None
    return rec


def sweep(tag, tasks, providers=("go", "direct"), workers=6):
    out_path = os.path.join(RESULTS, f"{tag}.jsonl")
    existing = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            try:
                d = json.loads(line)
                existing.add((d["provider"], d["task"]))
            except Exception:
                pass
    jobs = [(p, t) for p in providers for t in tasks if (p, t["id"]) not in existing]
    print(f"[{tag}] {len(jobs)} calls ({len(existing)} cached)", flush=True)
    recs = []
    with open(out_path, "a") as f, ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_task, p, t): (p, t["id"]) for p, t in jobs}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result()
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            recs.append(rec)
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
    return out_path


def summarize(tag):
    path = os.path.join(RESULTS, f"{tag}.jsonl")
    rows = [json.loads(l) for l in open(path)]
    by = {}
    for r in rows:
        by.setdefault(r["provider"], []).append(r)
    summary = {}
    for p, rs in by.items():
        cats = {}
        for r in rs:
            c = cats.setdefault(r["cat"], dict(n=0, ok=0, lat=[], tin=0, tout=0, cost=0.0))
            c["n"] += 1
            c["ok"] += 1 if r["passed"] else 0
            c["lat"].append(r["latency"] or 0)
            c["tin"] += r["tokens_in"] or 0
            c["tout"] += r["tokens_out"] or 0
            c["cost"] += r["cost"] or 0
        tot = dict(n=len(rs), ok=sum(1 for r in rs if r["passed"]),
                   rate=round(100 * sum(1 for r in rs if r["passed"]) / len(rs), 1),
                   lat_med=round(statistics.median([r["latency"] or 0 for r in rs]), 2),
                   lat_p90=round(sorted([r["latency"] or 0 for r in rs])[int(0.9 * (len(rs) - 1))], 2),
                   tin=sum(r["tokens_in"] or 0 for r in rs), tout=sum(r["tokens_out"] or 0 for r in rs),
                   cost=round(sum(r["cost"] or 0 for r in rs), 6),
                   errors=sum(1 for r in rs if not r["ok"]))
        per_cat = {k: dict(n=v["n"], ok=v["ok"], rate=round(100 * v["ok"] / v["n"], 1),
                           lat_med=round(statistics.median(v["lat"]), 2),
                           tin=v["tin"], tout=v["tout"], cost=round(v["cost"], 6))
                   for k, v in sorted(cats.items())}
        summary[p] = dict(total=tot, per_cat=per_cat)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    json.dump(summary, open(os.path.join(RESULTS, f"{tag}-summary.json"), "w"), indent=2, ensure_ascii=False)
    return summary


def effort_probe():
    rng = __import__("random").Random(7)
    tasks = [T.t_math(rng, 100 + i) for i in range(3)] + [T.t_count(rng, i) for i in range(3)]
    path = os.path.join(RESULTS, "effort.jsonl")
    jobs = [(p, t, e) for p in ("go", "direct") for t in tasks for e in ("low", "high", "max")]
    print(f"[effort] {len(jobs)} calls", flush=True)
    with open(path, "w") as f, ThreadPoolExecutor(max_workers=6) as ex:
        def one(p, t, e):
            r = call(p, t["messages"], max_tokens=t["max_tokens"], extra={"reasoning_effort": e})
            ok, det = (False, "fail")
            if r.get("ok"):
                try:
                    ok, det = t["grade"](r)
                except Exception as ex2:
                    det = str(ex2)
            return dict(provider=p, task=t["id"], effort=e, passed=ok, detail=str(det)[:120],
                        reasoning_tokens=r.get("reasoning_tokens", 0), tokens_out=r.get("tokens_out", 0),
                        latency=r.get("latency", 0), ok=r.get("ok"), http=r.get("http"), error=r.get("error"))
        for rec in ex.map(lambda a: one(*a), jobs):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows = [json.loads(l) for l in open(path)]
    agg = {}
    for r in rows:
        a = agg.setdefault((r["provider"], r["effort"]), dict(n=0, ok=0, rt=[], t=[]))
        a["n"] += 1; a["ok"] += 1 if r["passed"] else 0; a["rt"].append(r["reasoning_tokens"]); a["t"].append(r["latency"])
    print(json.dumps({f"{p}/{e}": dict(n=v["n"], ok=v["ok"], reasoning_avg=round(statistics.mean(v["rt"]), 1),
                                       lat_avg=round(statistics.mean(v["t"]), 2)) for (p, e), v in sorted(agg.items())},
                     indent=2))
    return agg


def speed_probe():
    prompt = [{"role": "user", "content": "Escribe un texto de unas 300 palabras explicando cómo funciona "
                                          "una cadena de frío industrial, en español."}]
    rows = []
    for prov in ("go", "direct"):
        for rep in range(3):
            p = PROVIDERS[prov]
            body = {"model": p["model"], "messages": prompt, "temperature": 0, "max_tokens": 900,
                    "stream": True, "stream_options": {"include_usage": True}}
            headers = {"Authorization": f"Bearer {os.environ[p['key_env']]}", "Content-Type": "application/json",
                       "User-Agent": "bench-harness/1.0"}
            if prov == "go":
                headers["x-opencode-session"] = "speed-" + uuid.uuid4().hex[:12]
            req = urllib.request.Request(p["base"] + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
            t0 = time.time(); ttfb = None; chunks = 0; usage = {}
            with urllib.request.urlopen(req, timeout=180) as r:
                for line in r:
                    if not line.startswith(b"data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == b"[DONE]":
                        break
                    if ttfb is None:
                        ttfb = time.time() - t0
                    chunks += 1
                    try:
                        d = json.loads(payload)
                    except Exception:
                        continue
                    if d.get("usage"):
                        usage = d["usage"]
            total = time.time() - t0
            out_tok = usage.get("completion_tokens", 0)
            rows.append(dict(provider=prov, rep=rep, ttfb=round(ttfb or 0, 3), total=round(total, 3),
                             chunks=chunks, out_tokens=out_tok,
                             tok_s=round(out_tok / (total - (ttfb or 0)), 1) if total > (ttfb or 0) else None,
                             usage=usage))
            print(rows[-1], flush=True)
    json.dump(rows, open(os.path.join(RESULTS, "speed.json"), "w"), indent=2)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--effort", action="store_true")
    ap.add_argument("--speed", action="store_true")
    ap.add_argument("--summarize", default=None)
    ap.add_argument("--tag", default="main")
    ap.add_argument("--cat", default=None, help="only run this category")
    a = ap.parse_args()
    if a.summarize:
        summarize(a.summarize)
        sys.exit()
    tasks = T.build_all()
    if a.cat:
        tasks = [t for t in tasks if t["cat"] == a.cat]
    if a.pilot:
        seen, small = set(), []
        for t in tasks:
            if t["cat"] not in seen:
                seen.add(t["cat"]); small.append(t)
        tasks = small
    if a.speed:
        speed_probe()
    else:
        sweep(a.tag, tasks)
        summarize(a.tag)
        if a.effort:
            effort_probe()
