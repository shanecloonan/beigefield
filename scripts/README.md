# Scripts

## `.com` availability checker

`check_dotcom_availability.py` checks whether every combination of two word
lists is registered as a `.com` domain.

Registration status comes from RDAP (Verisign's `.com` registry, with
`rdap.org` as a fallback). A 404 means the name is not registered
(available); a 200 means it is taken. DNS is recorded only as a sanity note
via DNS-over-HTTPS (Cloudflare, then Google) and is never used to mark a
domain available — a name can be registered without any DNS records. A local
stub resolver is not trusted, because some environments answer every lookup
with a fake IP.

Run from the repo root (Python 3, standard library only):

```bash
python3 scripts/check_dotcom_availability.py
```

That writes `scripts/dotcom-availability-results.json` and `.csv`, and prints
available / taken / unknown lists.

To change the search, edit the `FIRST_WORDS` and `SECOND_WORDS` arrays at the
top of the script, or pass them on the command line. Words are lowercased and
concatenated (`Blue` + `Whale` → `bluewhale.com`); duplicate words and
duplicate combos are dropped.

```bash
python3 scripts/check_dotcom_availability.py \
  --first Blue,Red,Gold \
  --second Whale,Fox,Coin \
  --out scripts/dotcom-availability-results-batch2 \
  --seed scripts/dotcom-availability-results.json
```

Useful flags: `--delay 1.0` (throttle), `--resume` (skip domains already in
the JSON output), `--seed FILE` (reuse an earlier batch's results),
`--recheck-unknown` (re-query uncertain rows), `--limit 5` (smoke test).

The client waits between requests, sends a descriptive User-Agent, retries
rate limits and transient errors with backoff, and marks anything ambiguous
as `UNKNOWN` rather than available.

Prior runs:

- Batch 1: `scripts/dotcom-availability-results.json` / `.csv`
- Batch 2: `scripts/dotcom-availability-results-batch2.json` / `.csv`
- Batch 3: `scripts/dotcom-availability-results-batch3.json` / `.csv`
- Batch 4: `scripts/dotcom-availability-results-batch4.json` / `.csv`
