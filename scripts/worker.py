"""Dispatch heavy generation to AgentRouter worker models (deepseek-v4-flash / glm-5.3).

Usage:
    python scripts/worker.py <model> <prompt_file> [system_file]
    echo "prompt" | python scripts/worker.py deepseek-v4-flash -

Claude reviews + commits the output; these models do the heavy drafting.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

WORKERS = {"deepseek-v4-flash", "glm-5.3"}


def _key() -> str:
    for line in open("/Users/vinayak/Documents/razorpay/.env"):
        if line.startswith("AGENTROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("no AGENTROUTER_API_KEY in .env")


def ask(model: str, prompt: str, system: str | None = None, *, max_tokens: int = 32000) -> str:
    # deepseek-v4-flash / glm-5.3 are REASONING models: they spend tokens in `reasoning_content`
    # before emitting `content`. Give a large budget or the answer comes back empty (finish=length).
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    req = urllib.request.Request(
        "https://agentrouter.org/v1/chat/completions",
        data=json.dumps({"model": model, "messages": msgs, "max_tokens": max_tokens}).encode(),
        headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json",
                 "User-Agent": "codex_cli_rs/0.45.0"},
    )
    try:
        r = json.load(urllib.request.urlopen(req, timeout=900))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        sys.exit(f"HTTP {e.code}: {body}")
    msg = r["choices"][0]["message"]
    content = msg.get("content") or ""
    if not content.strip() and r["choices"][0].get("finish_reason") == "length":
        sys.exit("worker ran out of tokens during reasoning; raise max_tokens")
    return content


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.exit(__doc__)
    model = argv[0]
    prompt = sys.stdin.read() if argv[1] == "-" else open(argv[1], encoding="utf-8").read()
    system = open(argv[2], encoding="utf-8").read() if len(argv) > 2 else None
    print(ask(model, prompt, system))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
