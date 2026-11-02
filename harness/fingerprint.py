"""Fingerprint probe: are both endpoints serving the same weights?

For each fixed prompt, ask for 1 token with top_logprobs=10 at temperature 0 and compare the
first-token distribution. Same engine => near-identical token and logprobs; different
weights/quant => divergence.
"""
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run import PROVIDERS, _load_env  # noqa: E402

_load_env()

PROMPTS = [
    "La capital de Francia es",
    "def fibonacci(n):\n    if n < 2:\n        return n\n    return",
    "El precio del café en Colombia durante 2026 ha sido",
    "SELECT nombre, apellido FROM clientes WHERE",
    "2 + 2 =",
    "Escribe una función que ordene una lista:",
    "La fotosíntesis ocurre en",
    "import numpy as np\nnp.",
    "El presidente de la República de Chile en 2025 fue",
    "Traduce 'good morning' al español:",
    "La ecuación de la relatividad es E =",
    "Resuelve: 17 * 23 =",
]


def one(provider, prompt):
    p = PROVIDERS[provider]
    body = {"model": p["model"], "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": 1, "logprobs": True, "top_logprobs": 10}
    headers = {"Authorization": f"Bearer {os.environ[p['key_env']]}", "Content-Type": "application/json",
               "User-Agent": "bench-harness/1.0"}
    if provider == "go":
        headers["x-opencode-session"] = "fp-" + uuid.uuid4().hex[:12]
    req = urllib.request.Request(p["base"] + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
            lp = d["choices"][0].get("logprobs") or {}
            entry = None
            for key in ("content", "reasoning_content"):
                if lp.get(key):
                    entry = lp[key][0]
                    break
            tin = (d.get("usage") or {}).get("prompt_tokens")
            return dict(ok=True, token=entry["token"], logprob=entry["logprob"],
                        top=[(t["token"], t["logprob"]) for t in entry.get("top_logprobs") or []],
                        tin=tin)
        except Exception as e:
            err = str(e)[:200]
    return dict(ok=False, error=err)


def main():
    rows = []
    for prompt in PROMPTS:
        g = one("go", prompt)
        d = one("direct", prompt)
        rec = dict(prompt=prompt, go=g, direct=d)
        if g.get("ok") and d.get("ok"):
            rec["same_top1"] = g["token"] == d["token"]
            rec["d_logprob"] = round(abs(g["logprob"] - d["logprob"]), 6)
            gset = {t: l for t, l in g["top"]}
            dset = {t: l for t, l in d["top"]}
            common = set(gset) & set(dset)
            rec["top5_overlap"] = len(set(list(gset)[:5]) & set(list(dset)[:5]))
            rec["max_abs_delta_top"] = round(max((abs(gset[t] - dset[t]) for t in common), default=None), 4) if common else None
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False)[:400], flush=True)
    ok = [r for r in rows if r.get("same_top1") is not None]
    print("\n=== SUMMARY ===")
    print("prompts:", len(rows), "| both ok:", len(ok))
    print("same top-1 token:", sum(1 for r in ok if r["same_top1"]), "/", len(ok))
    print("median |Δlogprob| top-1:", round(statistics.median([r["d_logprob"] for r in ok]), 6))
    print("median top-5 overlap:", statistics.median([r["top5_overlap"] for r in ok]))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "fingerprint.json")
    json.dump(rows, open(out, "w"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
