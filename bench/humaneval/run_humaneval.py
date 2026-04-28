#!/usr/bin/env python3
"""
HumanEval runner for Krentix.

Pipeline:
  1. Load HumanEval.jsonl.gz (164 Python problems with hidden unit tests).
  2. For each problem, POST the prompt to the Krentix bridge `/api/pipeline`.
  3. Extract Python code from the response (markdown fenced or raw).
  4. Construct: `prompt + completion + test + check(entry_point)`.
  5. Run in a fresh `python` subprocess with a wall timeout.
  6. Record pass/fail + stderr + stdout.

Public dataset: https://github.com/openai/human-eval (Chen et al., 2021).
Score = % of tasks where the test subprocess exits with code 0 (pass@1).

Usage:
  python run_humaneval.py                 # full 164 problems
  python run_humaneval.py --limit 20      # first 20 problems
  python run_humaneval.py --sample 20     # random sample of 20 (deterministic seed)
  python run_humaneval.py --task HumanEval/0   # one specific task
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── config ────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
DATASET = HERE / "HumanEval.jsonl.gz"
REPO_ROOT = HERE.parent.parent
REPORT_DIR = REPO_ROOT / "reports" / "bench-2026-04-28"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

KRENTIX_API = os.environ.get("KRENTIX_API", "http://localhost:4100")
KRENTIX_TIMEOUT_S = int(os.environ.get("KRENTIX_TIMEOUT_S", "240"))
TEST_TIMEOUT_S = int(os.environ.get("HE_TEST_TIMEOUT_S", "30"))
SEED = int(os.environ.get("HE_SEED", "20260428"))


# ─── dataset ───────────────────────────────────────────────────────────────
def load_dataset() -> list[dict[str, Any]]:
    if not DATASET.exists():
        raise FileNotFoundError(f"missing dataset: {DATASET}")
    with gzip.open(DATASET, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ─── Krentix call ──────────────────────────────────────────────────────────
def call_krentix(prompt: str) -> dict[str, Any]:
    """POST to /api/pipeline. Return {ok, ms, answer, source, raw, error?}."""
    body = json.dumps(
        {"input": prompt, "projectDir": ".", "surface": "humaneval-bench"}
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{KRENTIX_API}/api/pipeline",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=KRENTIX_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "ok": True,
            "ms": int((time.time() - t0) * 1000),
            "answer": data.get("answer") or data.get("generatedCode") or "",
            "source": data.get("source"),
            "finalDecision": data.get("finalDecision"),
            "raw_keys": sorted(list(data.keys())),
        }
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)}


# ─── code extraction ───────────────────────────────────────────────────────
FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_python(answer: str, entry_point: str) -> str:
    """Best-effort extraction of the Python code from a Krentix response.

    Strategy:
      1. If there's a fenced ```python ... ``` block, use the longest one.
      2. Else if there's any fenced block, use the longest one.
      3. Else use the whole answer.
    """
    if not answer:
        return ""
    fences = FENCE_RE.findall(answer)
    if fences:
        return max(fences, key=len).strip()
    return answer.strip()


def assemble_program(prompt: str, completion: str, test: str, entry_point: str) -> str:
    """Build a runnable Python file that exercises the candidate function.

    The model may have produced (a) just the indented body, (b) the full def,
    or (c) the full def with surrounding imports / helper code. We handle all
    three by checking whether the extracted code already declares the entry
    point. If yes, we use it as-is; if no, we treat it as the body and
    prepend the original prompt (which has the signature).
    """
    has_def = re.search(rf"^\s*def\s+{re.escape(entry_point)}\s*\(", completion, re.M)
    if has_def:
        full = completion
    else:
        # treat completion as body — concatenate after prompt
        full = prompt.rstrip() + "\n" + (completion if completion else "    pass\n")
    return (
        full
        + "\n\n"
        + test
        + f"\n\ncheck({entry_point})\n"
    )


# ─── subprocess runner ─────────────────────────────────────────────────────
def run_test_program(program: str) -> dict[str, Any]:
    """Run program in a fresh `python` subprocess. Return {passed, exit, stdout, stderr, ms}."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(program, encoding="utf-8")
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(path)],
                capture_output=True,
                timeout=TEST_TIMEOUT_S,
                text=True,
            )
            ms = int((time.time() - t0) * 1000)
            return {
                "passed": proc.returncode == 0,
                "exit": proc.returncode,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
                "ms": ms,
                "timeout": False,
            }
        except subprocess.TimeoutExpired as e:
            return {
                "passed": False,
                "exit": -1,
                "stdout": (e.stdout or "")[-2000:] if isinstance(e.stdout, str) else "",
                "stderr": (e.stderr or "")[-2000:] if isinstance(e.stderr, str) else "",
                "ms": int((time.time() - t0) * 1000),
                "timeout": True,
            }


# ─── orchestration ─────────────────────────────────────────────────────────
def select_tasks(all_tasks: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.task:
        sel = [t for t in all_tasks if t["task_id"] == args.task]
        if not sel:
            raise SystemExit(f"task not found: {args.task}")
        return sel
    if args.sample:
        rnd = random.Random(SEED)
        idxs = sorted(rnd.sample(range(len(all_tasks)), min(args.sample, len(all_tasks))))
        return [all_tasks[i] for i in idxs]
    if args.limit:
        return all_tasks[: args.limit]
    return all_tasks


def main() -> int:
    parser = argparse.ArgumentParser(description="HumanEval runner for Krentix")
    parser.add_argument("--limit", type=int, default=0, help="run first N tasks")
    parser.add_argument("--sample", type=int, default=0, help="random sample of N (seeded)")
    parser.add_argument("--task", default="", help="run a single task_id")
    parser.add_argument("--save-prefix", default="humaneval", help="report filename prefix")
    args = parser.parse_args()

    all_tasks = load_dataset()
    tasks = select_tasks(all_tasks, args)
    print(f"\n{'=' * 72}")
    print("  HumanEval — Krentix bridge")
    print(f"  api: {KRENTIX_API}    seed: {SEED}    test_timeout: {TEST_TIMEOUT_S}s")
    print(f"  tasks: {len(tasks)} / {len(all_tasks)}    "
          f"({'full' if len(tasks) == len(all_tasks) else 'subset'})")
    print("=" * 72)

    # bridge health check
    try:
        with urllib.request.urlopen(f"{KRENTIX_API}/health", timeout=5) as r:
            h = json.loads(r.read().decode())
        print(f"  bridge ok  uptime={h.get('uptime')}s  personas={h.get('personas')}\n")
    except Exception as e:
        print(f"  ERROR: bridge unreachable at {KRENTIX_API}: {e}", file=sys.stderr)
        return 2

    started = time.time()
    results: list[dict[str, Any]] = []
    pass_count = 0

    for i, t in enumerate(tasks, 1):
        tid = t["task_id"]
        ep = t["entry_point"]
        prompt_for_krentix = (
            "Complete the following Python function. Return ONLY the full function "
            "definition (including the signature) inside a single Python code block. "
            "Do not include the test cases or extra commentary.\n\n"
            f"```python\n{t['prompt']}```"
        )
        print(f"  [{i:>3}/{len(tasks)}] {tid:<14} entry={ep:<24}", end="", flush=True)
        rk = call_krentix(prompt_for_krentix)
        completion_raw = rk.get("answer", "") if rk["ok"] else ""
        completion = extract_python(completion_raw, ep)
        program = assemble_program(t["prompt"], completion, t["test"], ep)
        run = run_test_program(program) if rk["ok"] else {
            "passed": False, "exit": -2, "stdout": "", "stderr": "krentix call failed",
            "ms": 0, "timeout": False,
        }
        if run["passed"]:
            pass_count += 1
        tag = "PASS" if run["passed"] else ("TMO" if run.get("timeout") else "FAIL")
        src = (rk.get("source") or "")[:14]
        print(f"  {tag:<4}  k={rk['ms']}ms  t={run['ms']}ms  src={src}")

        results.append({
            "task_id": tid,
            "entry_point": ep,
            "krentix_ms": rk.get("ms"),
            "krentix_source": rk.get("source"),
            "krentix_final_decision": rk.get("finalDecision"),
            "krentix_ok": rk.get("ok"),
            "krentix_error": rk.get("error"),
            "answer_chars": len(completion_raw or ""),
            "completion_chars": len(completion or ""),
            "test_passed": run["passed"],
            "test_exit": run["exit"],
            "test_ms": run["ms"],
            "test_timeout": run.get("timeout", False),
            "stderr_tail": (run.get("stderr") or "")[-600:],
        })

    wall = int((time.time() - started) * 1000)
    pct = (pass_count / len(results) * 100) if results else 0.0
    print()
    print("=" * 72)
    print(f"  RESULT  {pass_count} / {len(results)}  =  {pct:.1f}%  pass@1")
    print(f"  wall    {wall / 1000:.1f}s")
    print("=" * 72)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    report_path = REPORT_DIR / f"{args.save_prefix}-{stamp}.json"
    payload = {
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "dataset": "HumanEval (openai/human-eval, v2 2021-07-05)",
        "dataset_url": "https://github.com/openai/human-eval",
        "n_total_in_dataset": len(all_tasks),
        "n_run": len(results),
        "subset": "full" if len(results) == len(all_tasks) else "subset",
        "subset_args": {"limit": args.limit, "sample": args.sample, "task": args.task},
        "seed": SEED,
        "krentix_api": KRENTIX_API,
        "test_timeout_s": TEST_TIMEOUT_S,
        "score_pass_at_1": round(pct, 2),
        "passed": pass_count,
        "failed": len(results) - pass_count,
        "wall_ms": wall,
        "harness_path": str(Path(__file__).relative_to(REPO_ROOT)),
        "harness_sha": _self_sha(),
        "results": results,
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  saved   {report_path}")
    return 0


def _self_sha() -> str:
    import hashlib
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
