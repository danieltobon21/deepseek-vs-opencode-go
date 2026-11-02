"""Render the 4:5 social card (1080x1350) used for the X post."""
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = json.load(open(os.path.join(ROOT, "site", "data", "summary.json")))
D = S["per_category"] and S["suite"]["quality"]
L = S["latency_s"]
acc_d, acc_g = D["direct"], D["go"]
slow = L["58K-token prompt"]["go"] / L["58K-token prompt"]["direct"]
over = (L["Median, chat"]["go"] / L["Median, chat"]["direct"] - 1) * 100

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
<rect width="1080" height="1350" fill="#181A1F"/>
<rect x="0" y="0" width="8" height="1350" fill="#FF5A1F"/>
<g font-family="Helvetica,Arial,sans-serif">
<text x="72" y="120" font-size="22" letter-spacing="5" fill="#9AA2B1">TOBON DIGITAL · BENCHMARK</text>

<text x="72" y="290" font-size="82" font-weight="bold" fill="#ECEEF2">Same model.</text>
<text x="72" y="382" font-size="82" font-weight="bold" fill="#ECEEF2">Same accuracy.</text>
<text x="72" y="474" font-size="82" font-weight="bold" fill="#FF5A1F">Slower relay.</text>

<text x="72" y="556" font-size="27" fill="#9AA2B1">DeepSeek API vs OpenCode Go · 1,176 requests</text>
<text x="72" y="596" font-size="27" fill="#9AA2B1">72 tasks × 8 runs · deterministic grading</text>

<line x1="72" y1="660" x2="1008" y2="660" stroke="#2C313B" stroke-width="2"/>

<text x="72" y="782" font-size="76" font-weight="bold" fill="#ECEEF2">{acc_d:.1f}%</text>
<text x="72" y="822" font-size="24" fill="#9AA2B1">direct API accuracy</text>

<text x="560" y="782" font-size="76" font-weight="bold" fill="#ECEEF2">{acc_g:.1f}%</text>
<text x="560" y="822" font-size="24" fill="#9AA2B1">OpenCode Go accuracy</text>

<line x1="72" y1="890" x2="1008" y2="890" stroke="#2C313B" stroke-width="2"/>

<text x="72" y="1002" font-size="76" font-weight="bold" fill="#FF5A1F">+{over:.0f}%</text>
<text x="72" y="1042" font-size="24" fill="#9AA2B1">median latency</text>

<text x="560" y="1002" font-size="76" font-weight="bold" fill="#FF5A1F">{slow:.1f}×</text>
<text x="560" y="1042" font-size="24" fill="#9AA2B1">on a 58K-token prompt</text>

<line x1="72" y1="1110" x2="1008" y2="1110" stroke="#2C313B" stroke-width="2"/>

<text x="72" y="1196" font-size="30" fill="#ECEEF2">The weights are identical — the wire is not.</text>
<text x="72" y="1246" font-size="27" fill="#9AA2B1">Full methodology, raw JSONL and numbers:</text>
<text x="72" y="1292" font-size="31" fill="#FF5A1F">deepseek-vs-opencode-go.pages.dev</text>
</g></svg>"""

svg_path = os.path.join(HERE, "x-card-4x5.svg")
png_path = os.path.join(HERE, "x-card-4x5.png")
open(svg_path, "w").write(SVG)
subprocess.run(["rsvg-convert", "-w", "1080", "-h", "1350", "-o", png_path, svg_path], check=True)
print(png_path, os.path.getsize(png_path))
