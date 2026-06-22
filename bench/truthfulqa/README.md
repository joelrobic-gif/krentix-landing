# TruthfulQA-MC1 - Krentix reproducibility artifacts

Krentix score: **724 / 790 = 91.6% (pass@1, MC1, full dataset)**, measured 2026-05-01, medium tier.

## Files

| File | What it is |
|---|---|
| `run_truthfulqa.py` | The harness. Re-downloads the upstream dataset, queries the local Krentix bridge at `http://localhost:4100`, scores MC1 single-token answers. |
| `truthfulqa_mc1.jsonl` | Frozen dataset snapshot (790 lines). The upstream CSV at `sylinrl/TruthfulQA` drifts on `main`; this frozen copy is the exact set scored, so the number reproduces. |
| `results/all-truthfulqa-2026-05-01T21-45-54.json` | Per-problem results for the definitive run (`passed=724`, `n_run=790`, `seed=20260501`). |

## Run selection (why the 21:45 run, not the 09:11 run)

Two runs exist for 2026-05-01:

- `all-truthfulqa-2026-05-01T09-11-13.json` - **earlier, buggy run.** Superseded.
- `all-truthfulqa-2026-05-01T21-45-54.json` - **definitive run.** This is the published artifact: `passed=724`, `n_run=790`, `score_pass_at_1=0.9164…` → 91.6%, `seed=20260501`.

Always cite the **21:45** file. The 09:11 file is retained upstream in `reports/` only for audit history and is not the published number.

## Reproduce

```bash
# bridge must be running on :4100, medium tier
python run_truthfulqa.py --dataset truthfulqa_mc1.jsonl --seed 20260501
```

The frozen dataset + fixed seed make the 724/790 split deterministic against a stable bridge build.
