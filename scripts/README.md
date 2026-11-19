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
top of the script. Words are lowercased and concatenated (`Blue` + `Whale` →
`bluewhale.com`). Useful flags: `--delay 1.0` (throttle), `--resume` (skip
domains already in the JSON output), `--recheck-unknown` (re-query uncertain
rows), `--limit 5` (smoke test).

The client waits between requests, sends a descriptive User-Agent, retries
rate limits and transient errors with backoff, and marks anything ambiguous
as `UNKNOWN` rather than available.
