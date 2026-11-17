# ETH-scanner CI extras

## Corpus recall workflow

`eth-scanner-corpus-recall.yml` is the GitHub Actions workflow that measures
scanner recall on known-vulnerable corpora (SmartBugs Curated, Not So Smart
Contracts, DeFiVulnLabs). Corpora are fetched at run time at pinned commits;
they are not committed to this repo. Web3Bugs (~560MB) is skipped.

To enable the job, copy this file into `.github/workflows/`:

```
cp eth-scanner/ci/eth-scanner-corpus-recall.yml .github/workflows/
```

GitHub requires the OAuth `workflow` scope to create or update files under
`.github/workflows/`. Until a token with that scope pushes the copy, the
workflow will not run on pull requests or main.

Run the same measurement locally (corpora already on the box, or fetched
the same way CI would):

```
PYTHONPATH=src python tools/measure_corpora.py \
  --corpus smartbugs-curated \
  --corpus not-so-smart-contracts \
  --corpus defivulnlabs
```

The job prints a summary table and fails only when SmartBugs ungated catch
falls below `ETH_SCANNER_CORPUS_MIN_SMARTBUGS` (default 90 of 143). Set the
env (or `--min-smartbugs`) to 0 to disable the gate.
