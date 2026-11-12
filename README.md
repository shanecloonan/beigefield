This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

## `/test` — ETH funds-at-risk scanner desk

Live at [`/test`](https://beigefield.vercel.app/test) (linked as **Scanner** from the home page). Defensive triage
only: findings are framed as *funds at risk*, automation never stamps "exploitable", and the desk never generates
exploit or PoC code. Counterexamples, call sequences and long calldata are elided from every engine's output.

Tabs:

- **Lane A** — `python -m eth_scanner` against an address or a local fixture; Lane A/B buckets.
- **Research** — the research stack (`python -m eth_scanner.research`) with receipts.
- **Engines** — one desk over eight engines with a common finding schema
  (`lib/eth-scanner/desk/findings.ts`), cross-referenced to eight vulnerability corpora.

| Engine | Kind | Target | Fork |
| --- | --- | --- | --- |
| Slither | static | fixture source | [shanecloonan/slither](https://github.com/shanecloonan/slither) |
| Aderyn | static | fixture source | [shanecloonan/aderyn](https://github.com/shanecloonan/aderyn) |
| AChecker | bytecode | fixture runtime bytecode | [shanecloonan/AChecker](https://github.com/shanecloonan/AChecker) |
| Echidna | fuzz | `eth-scanner/research/fuzz` harness | [shanecloonan/echidna](https://github.com/shanecloonan/echidna) |
| Medusa | fuzz | harness | [shanecloonan/medusa](https://github.com/shanecloonan/medusa) |
| ityfuzz | fuzz | harness | [shanecloonan/ityfuzz](https://github.com/shanecloonan/ityfuzz) |
| Halmos | symbolic | harness (`check_*`) | [shanecloonan/halmos](https://github.com/shanecloonan/halmos) |
| Mythril | symbolic | fixture source | [shanecloonan/mythril](https://github.com/shanecloonan/mythril) |

Corpora (linked, never vendored — some contain PoCs): smartbugs-curated, Web3Bugs, DeFiVulnLabs,
not-so-smart-contracts, Blockchain-bridge-vulnerabilities, awesome-buggy-erc20-tokens,
clustered-web3-vulnerabilities, bug-bounty-intelligence-mcp (CC0 Sherlock acceptance priors used for triage ranking).

Engines are **adapters**, not bundled tools. `GET /api/test/engines` reports each as `installed`, `stub`
(binary present but `solc`/`forge` missing, or disabled) or `missing`. On Vercel serverless no engine binaries
exist, so all show `missing`; run them on a worker and paste the report into the Engines tab
(`POST /api/test/engines {engine, output}`) to normalize it. Engine processes get a scrubbed env (no API keys),
a temp workdir and a hard timeout, and only run against whitelisted fixtures or the defensive harness.

### Environment (set on Vercel → Project → Settings → Environment Variables)

| Var | Needed | Purpose |
| --- | --- | --- |
| `ETHERSCAN_API_KEYS` | for live ingest | Comma-separated Etherscan keys. Unset → built-in free-tier test key. |
| `ETH_SCANNER_SUPABASE_URL` / `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_SECRET_KEY` | optional | Live persist. Detailed `/test` rows go to `test_scan_*` (`supabase/migrations/*_test_results.sql`); Lane A also uses `eth_scan_*` when present. Unset → dry-run; detailed persist soft-fails. |
| `ETH_RPC_URL` | optional | Read-only RPC for proxy / storage checks. |
| `ETH_SCANNER_DRY_RUN` | optional | `1` forces local dry-run even with Supabase set. |
| `ETH_SCANNER_PYTHON`, `ETH_SCANNER_WORK_DIR` | local only | Interpreter / work dir override. |
| `ETH_SCANNER_<ENGINE>_BIN`, `ETH_SCANNER_ENGINES_DISABLED` | workers only | Engine binary overrides / force stub. |

See `.env.example` for the full list. `npm run build` downloads a pinned portable CPython on Vercel only
(`scripts/bundle-python-runtime.mjs`). Tests: `npm run test:eth-scanner` and `npm run test:eth-scanner-py`.
