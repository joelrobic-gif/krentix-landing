# Krentix benchmarks — public, reproducible

This directory contains the harness, datasets, and raw results behind the
benchmark numbers shown on [www.krentix.com](https://www.krentix.com).

The point of putting this here, in a public repo, is simple: **the
benchmark numbers we cite need to be re-runnable by anyone**. If you can
clone this folder, point the harness at a Krentix bridge, and reproduce
the score, the claim stands. If you can't, the claim doesn't.

## What's in here

```
bench/
└── humaneval/
    ├── HumanEval.jsonl.gz       Public dataset (openai/human-eval, v2 2021-07-05)
    ├── run_humaneval.py         The harness — reads dataset, calls bridge,
    │                             extracts code, runs unit tests, scores.
    ├── results/
    │   └── humaneval-<UTC>.json  Per-problem results, raw output preserved.
    └── README.md
```

## HumanEval — what's measured

[HumanEval](https://github.com/openai/human-eval) is the standard public
coding benchmark from Chen et al., 2021 (arXiv:2107.03374). 164 hand-written
Python problems, each with hidden unit tests.

- **Score**: pass@1 — % of problems where the candidate's code passes ALL
  the official unit tests in a fresh `python -I` subprocess (no inherited
  imports, no shared state).
- **No author grading.** A test passes iff the subprocess exits with code 0.
  No human reads the answer to decide.
- **Dataset hash** (sanity check):
  ```
  $ sha256sum bench/humaneval/HumanEval.jsonl.gz
  # See: https://github.com/openai/human-eval/blob/master/data/HumanEval.jsonl.gz
  ```

## Reproducing the score

1. Clone this repo:
   ```
   git clone https://github.com/joelrobic-gif/krentix-landing.git
   cd krentix-landing/bench/humaneval
   ```

2. Install Python 3.11+ (only `urllib`, `gzip`, `subprocess`, `json` —
   all standard library, no extra packages required).

3. Run a Krentix bridge somewhere reachable (default `http://localhost:4100`).
   See [krentix.com/app](https://www.krentix.com/app) for status of public
   bridge availability.

4. Run the harness:
   ```
   # Sanity check — single task
   python run_humaneval.py --task HumanEval/0

   # Full suite (164 tasks, ~60 min, costs ~$5–10 in API spend on
   # Krentix's twelve-model ensemble)
   python run_humaneval.py
   ```

5. Compare your `results/humaneval-<UTC>.json` against the one we
   committed. The pass@1 score should match within run-to-run variance
   (LLM sampling is non-deterministic; expect ±1–2 points).

## Why this is more defensible than what we had before

The previous landing copy claimed "100% HLE benchmark vs 56.8% Mythos"
in the hero. That number was author-derived, the comparator was a
placeholder name from internal planning docs ("Mythos" wasn't a real
benchmark or competitor), and neither was reproducible. We pulled it.

What's posted now is bounded, sourced, and re-runnable:

1. **Public dataset** — `HumanEval.jsonl.gz` is the file OpenAI shipped
   in 2021. We didn't make it.
2. **Mechanical scoring** — pass/fail comes from `python` exit codes on
   the dataset's own hidden tests. We didn't pick the rubric.
3. **Open harness** — `run_humaneval.py` is in this repo. Read it. Re-run
   it. The pipeline is: HTTP POST → fenced-code extraction → subprocess
   → exit-code check.
4. **Per-problem results saved** — `results/*.json` lists which task IDs
   passed and which failed, with stderr tails for the failures. Anyone
   can audit specific failures.

If we ever post a number that you can't reproduce by running this
harness, please open an issue.

## What this benchmark does *not* measure

HumanEval is one piece. It tests function-completion in Python with
clean signatures and unit tests. It doesn't test:

- Multi-file refactors → see SWE-bench Verified (heavier infrastructure;
  requires Docker per task).
- Architecture / design decisions → no public benchmark covers this well.
- Long-horizon agentic work → see Terminal-Bench, Devin-eval (gated).
- Hardest reasoning → see HLE (gated by authors; not redistributable).

The frontier-model scores (44.7% HLE etc.) shown in the landing's §04
Benchmarks table come from Artificial Analysis's live leaderboard for
those gated benchmarks — we link the source rather than reproducing
numbers we can't verify ourselves.

## Provenance

- Dataset: `openai/human-eval` repo, file `data/HumanEval.jsonl.gz`,
  sourced 2026-04-27.
- Harness: written 2026-04-27 in this session. Self-hash printed in
  every result file under `harness_sha`.
- Bridge: Krentix `0.1.0`, twelve-model ensemble, full pipeline mode.
