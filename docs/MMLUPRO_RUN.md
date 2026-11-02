# Running the MMLU-Pro experiment (screen, then holdout)

One question: does a judge after up to 3 debate rounds (D) beat the plurality of the three round-0 answers (B) on
MMLU-Pro, with a weaker free-tier panel? A1-A3 (each model alone) are reported for reference. There is no C and no
D-vote. The holdout (60 questions) is spent once, so a guard checks the screen first.

All commands run from the repo root in PowerShell. Every command that sends requests uses your keys from `.env`; run
those yourself.

```powershell
$py = "backend\.venv\Scripts\python.exe"; $env:PYTHONPATH = "backend"
```

## 1. Check the data (no requests)
```powershell
& $py -m eval.mmlupro check          # 12,032 rows, sha256 pin ok, screen and holdout disjoint
```

## 2. Screen: debater_1 (Gemma) and debater_2 (gpt-oss-20b), 60 questions each
```powershell
& $py -m eval.screen --config eval/config/mmlupro_agents.yaml
```
- Prints the estimate, then asks `Proceed? [y/N]`. Results go to `eval/results/mmlupro-screen-s42/`.
- Stops cleanly at a daily cap or a rate limit. **Run the same command again to continue**; finished questions are skipped.
- `--report` prints the saved results and sends nothing.
- Target for each model: overall 40-70% and no category below 25% (3 of 12 passes, 2 of 12 does not).
  If it misses, follow the guidance the report prints: change the panel, then re-screen with a **new, disjoint seed**
  (`python -m eval.mmlupro select --kind screen --seed 43`, then `--seed 43` here) before any holdout run.

## 3. Check the guard (no requests)
```powershell
& $py -m eval.holdout check
```
Prints `finished and matches`, or lists every reason the holdout would be refused. For a re-screen under another
seed or folder: `--screen-seed 43 --screen-run mmlupro-screen-s43`.

## 4. Holdout: A1-A3, B and D on 60 questions
```powershell
& $py -m eval.run --dataset mmlupro-holdout --n 60 --seed 42 --config eval/config/mmlupro_agents.yaml
```
- Runs the guard first and refuses to start (exit 1, nothing sent) unless the screen is finished and matches. It
  re-checks on every resume. `--force` does not bypass it.
- Results go to `eval/results/mmlupro-holdout-s42/`; the manifest stores a `screen_pin` (which screen, hashes, accuracies).
- About 7-13 requests per question, so it takes several days at the free-tier caps (openrouter 40, groq 500, gemini
  200, mistral 200 per UTC day). Same command again each day. Add `--dry-run` first to see the estimate; it also shows whether
  the guard would refuse.
- `Ctrl+C` is safe: finished questions are saved.

## 5. Report
```powershell
& $py -m eval.report --dataset mmlupro-holdout --seed 42
```
Reads saved results only. D vs B is the single pre-declared test. At n = 60 only differences of roughly 15
points are detectable; "no detectable difference" is not evidence of no difference.

## What the guard checks
It refuses unless, for both screened agents:
1. the screen folder and manifest exist and all 60 screen questions are finished (and only those);
2. the screen's recorded hashes and settings equal what the holdout would use: dataset sha256, prompt suffix and its
   hash, extractor fingerprint, provider, model, max tokens, temperature, fallback flag, run profile, and the
   fingerprint of the whole agents config plus every prompt file in `backend/app/prompts/`;
3. the screen met its target (override: `--accept-missed-screen`, recorded in the pin).

| Refusal says | Meaning | What to do |
|---|---|---|
| `no screen results` / `no screen manifest` | Not screened, or another model was screened | Run step 2 |
| `N of 60 screen questions finished` | Screen interrupted | Run step 2 again |
| `screen extractor / prompt_suffix... was X` | Extractor or prompt changed after the screen | Revert the change, or re-screen under a new `--run` name |
| `screen agents_fingerprint was X` | Any edit to the agents file, a prompt file, or the profile flags (even the unscreened debater_3 or the judge) | Revert, or re-screen under a new `--run` name (response-cache hits cost no requests) |
| `missed its target` | Panel too hard or too easy | New panel and new screen seed; or `--accept-missed-screen` knowingly |

## Do not change between the screen and the holdout
`eval/mmlupro.py` (the extractor and the prompt line), `backend/app/prompts/*.md`, `eval/config/mmlupro_agents.yaml`,
the dataset files, and any `--max-tokens` / `--rpm` / `--allow-fallback` flags (pass the same ones to both).
