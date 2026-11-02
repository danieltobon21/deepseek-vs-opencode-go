#!/usr/bin/env python3
"""Scan a git repository's ENTIRE history (every blob) for secrets and private data."""
import re
import subprocess
import sys

REPO = sys.argv[1] if len(sys.argv) > 1 else "."

PATTERNS = [
    ("aws_key", r"AKIA[0-9A-Z]{16}"),
    ("openai_style_key", r"\bsk-[A-Za-z0-9_-]{16,}"),
    ("anthropic_key", r"sk-ant-[A-Za-z0-9_-]{16,}"),
    ("github_token", r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    ("google_api_key", r"AIza[0-9A-Za-z_-]{35}"),
    ("slack_token", r"xox[abprs]-[0-9A-Za-z-]{10,}"),
    ("private_key_block", r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("bearer_literal", r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    ("cf_account_id", r"\b[0-9a-f]{32}\b"),
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ("local_path", r"/home/[A-Za-z0-9._-]+"),
    ("ssh_target", r"\bssh\s+-\w*\s*[a-z0-9._-]+@"),
    ("private_ip", r"\b(10\.\d{1,3}|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    ("windows_user_path", r"C:\\\\Users\\\\[A-Za-z0-9._-]+"),
    ("env_secret_assign", r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+_.-]{12,}"),
]

ALLOW = [
    # public identifiers that are intentionally published
    "danieltobon21@users.noreply.github.com",
    "api.deepseek.com",
    "opencode.ai",
]

blobs = subprocess.run(["git", "-C", REPO, "rev-list", "--objects", "--all"],
                       capture_output=True, text=True, check=True).stdout.splitlines()
total = 0
findings = []
for line in blobs:
    if " " not in line:
        continue
    sha, path = line.split(" ", 1)
    try:
        data = subprocess.run(["git", "-C", REPO, "cat-file", "-p", sha],
                              capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        continue
    total += 1
    try:
        text = data.decode("utf-8", "replace")
    except Exception:
        continue
    for name, pat in PATTERNS:
        for m in re.finditer(pat, text):
            val = m.group(0)
            if any(a in val for a in ALLOW):
                continue
            findings.append((path, name, val[:80]))

print(f"blobs scanned: {total}")
seen = set()
for path, name, val in findings:
    key = (path, name, val)
    if key in seen:
        continue
    seen.add(key)
    print(f"  {name:18} {path:40} {val}")
print("FINDINGS:", len(seen))
