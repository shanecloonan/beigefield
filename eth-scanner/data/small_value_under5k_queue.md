# Under-$5,000 high-likelihood scan queue (300 contracts)

Generated 2026-11-25T21:57:32Z · chain: ethereum · 300 contracts

## Cutoff rules

- **Under $5,000:** `funds_usd` / `est_usd_held` is the scanner's native ETH plus major-token probe (WETH, USDC, USDT, DAI, WBTC, stETH, wstETH, USDe). Floor is the $100 engine minimum. Cap is exclusive of $5,000.
- **High likelihood:** the same classes as the first small-value queue. Upgradeable proxy, spot oracle, ERC-4626 vault, and lending are structural signals. Rari Capital and Percent Finance are the past-hack Compound-fork lending family already used on list 2. `univ2-fork-unknown` and a protocol named ERC-4626 vault are the AMM-fork and share-inflation classes when the row only has a protocol name. A decompilable contract with none of those is the unverified leftover (score 35).
- **Not this queue:** anything already in `small_value_queue.json`, the signal-rerun seed, or the seen skip list; list-2 canonical names; a negative drain prior; other chains (this job uses the Ethereum RPC).
- **Order:** score descending, then smaller funds, then address. The queue stops at 300. 30 further rows met the bar and stay off this queue so one list stays at the size Shane asked for.

## Selection sources / breakdown

| reason_class | n | class score | peak |
|---|---|---|---|
| clone-erc4626-inflation | 112 | 46 | 4 |
| amm-fork-thin-pool | 75 | 38 | 4 |
| lending-underscanned | 74 | 44 | 4 |
| unverified-leftover | 24 | 35 | 3 |
| clone-proxy-takeover | 13 | 48 | 5 |
| clone-spot-oracle | 2 | 45 | 5 |

- Lists: excluded-below-2000=99, list-1=32, list-2=169
- Funds: <=$1,900: 267, <=$5,000: 300 (median $473)

## How to run it

Signal-rerun reads this file and scans **one batch**, then stops. Finished addresses are the `signal-rerun:<address>` rows already stored as done, so the next trigger continues where this one stopped.

- **Batch:** 75 contracts, proxy cap 250,000 CU (about 2,600 CU each; the measured rerun was ~2,590). Four batches cover this queue. That is under one historical 4,000,000 CU run.
- **Trigger:** push `eth-scanner/signal-rerun.trigger` to `main`. The workflow runs `--small-value-batch`.
- **Or manually:** Actions → *eth-scanner-signal-rerun* → *Run workflow* → mode `small-value-batch`. Mode `historical` is the old full-signal rerun.
- **Or local:** `cd eth-scanner && python -m eth_scanner signal-rerun --small-value-batch --batch-size 75 --budget-cu 250000 --deadline-minutes 55 --dry-run --json`

Watch the Actions log for `mode`, `selected`, `rerun_count`, `skipped_finished`, `cu_used`, and `status`. `skipped_finished` climbs by about 75 after each batch that finishes.

## First batch

| # | address | name | funds_usd | reason_class | peak |
|---|---|---|---|---|---|
| 1 | `0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9` | BoringDAO | 1009 | clone-proxy-takeover | 5 |
| 2 | `0xa0b9cc50c460dde28321c34fcd7161434655a38f` | Skate AMM | 1061 | clone-proxy-takeover | 5 |
| 3 | `0x00000069abbb0b1ad6975bcf753eee15d318a0bf` | Asymmetry Finance | 1145 | clone-proxy-takeover | 5 |
| 4 | `0x357f55b46821a6c6e476cc32ebb2674cd125e849` | Equilibria | 894 | clone-proxy-takeover | 5 |
| 5 | `0xb65b67e986d7b097652920d72202f2c78319bc2c` | moto.fun | 2074 | clone-proxy-takeover | 5 |
| 6 | `0x2153fee80004e22a13f8d4306bf559e5e4d4f0a9` | Ensuro | 2307 | clone-proxy-takeover | 5 |
| 7 | `0xe1303b2514755a72da4aca9b917d96f16c842c80` | Prodigy.Fi V2 | 2887 | clone-proxy-takeover | 5 |
| 8 | `0x66a1e37c9b0eaddca17d3662d6c05f4decf3e110` | Rumpel Labs | 3490 | clone-proxy-takeover | 5 |
| 9 | `0x6a2469944d3f0aa54531dfa6dcb4350f4a150b67` | QIAN | 3855 | clone-proxy-takeover | 5 |
| 10 | `0x24db6717db1c75b9db6ea47164d8730b63875db7` | Eigenpie | 3891 | clone-proxy-takeover | 5 |
| 11 | `0x49f583d263e4ef938b9e09772d3394c71605df94` | SKALE Network Bridge | 4000 | clone-proxy-takeover | 5 |
| 12 | `0x149c4dd9a1f2a4de605be2b63d60540a8865a288` | Silent Protocol | 4178 | clone-proxy-takeover | 5 |
| 13 | `0x945facb997494cc2570096c74b5f66a3507330a1` | mStable CDP | 4578 | clone-proxy-takeover | 5 |
| 14 | `0x882ec5a4a22b110be602762e85758a02943de187` | OpenDAO | 110 | clone-erc4626-inflation | 4 |
| 15 | `0xc11d6b78d8c609a6cbf66e89dbfea06b011b0aef` | alphagrowth | 110 | clone-erc4626-inflation | 4 |
| 16 | `0x090342961b1de565cd76a7be041f57ec446a577c` | ERC-4626 vault | 113 | clone-erc4626-inflation | 4 |
| 17 | `0xc139190f447e929f090edeb554d95abb8b18ac1c` | Rumpel Labs | 125 | clone-erc4626-inflation | 4 |
| 18 | `0xfae2809935233d4bfe8a56c2355c4a2e7d1fff1a` | PieDAO | 127 | clone-erc4626-inflation | 4 |
| 19 | `0x784e3c592a6231d92046bd73508b3aae3a7cc815` | Cega V1 | 139 | clone-erc4626-inflation | 4 |
| 20 | `0x69cda6eda9986f7fca8a5dba06c819b535f4fc50` | Klondike Finance | 148 | clone-erc4626-inflation | 4 |
| 21 | `0x756ee7fafd2b629641b91e8a2e115e9c4d69078f` | ERC-4626 vault | 155 | clone-erc4626-inflation | 4 |
| 22 | `0x672c973155c46fc264c077a41218ddc397bb7532` | Klondike Finance | 161 | clone-erc4626-inflation | 4 |
| 23 | `0x98b872604f36807169c096241ecd4646021de133` | Cega V1 | 183 | clone-erc4626-inflation | 4 |
| 24 | `0xbfdc482616787b420bc6c710212fe3167e7198e9` | alphagrowth | 217 | clone-erc4626-inflation | 4 |
| 25 | `0x6dc3ce9c57b20131347fdc9089d740daf6eb34c5` | ERC-4626 vault | 237 | clone-erc4626-inflation | 4 |
| 26 | `0xad48a8261b0690c71b70115035eb14afd9a43242` | Diamond Protocol V1 | 251 | clone-erc4626-inflation | 4 |
| 27 | `0x877bba4238ef1dca9bf574561da633049de3a334` | ERC-4626 vault | 285 | clone-erc4626-inflation | 4 |
| 28 | `0x090559d58aab8828c27ee7a7eab18efd5bb90374` | xToken | 299 | clone-erc4626-inflation | 4 |
| 29 | `0x5f9baab8b2d5f446514546efc48b62500ddce48e` | ERC-4626 vault | 301 | clone-erc4626-inflation | 4 |
| 30 | `0x52d7e0a859d979997cb5a8f55f725b443d32a531` | ERC-4626 vault | 303 | clone-erc4626-inflation | 4 |
| 31 | `0xe3d74df89163a8fa1cba540ff6b339d13d322f61` | PieDAO | 337 | clone-erc4626-inflation | 4 |
| 32 | `0x87b918e76c92818db0c76a4e174447aee6e6d23f` | Mover | 342 | clone-erc4626-inflation | 4 |
| 33 | `0x5408a506db076dc330e661ca21e7f84947ef9792` | ERC-4626 vault | 345 | clone-erc4626-inflation | 4 |
| 34 | `0xab8631417271dbb928169f060880e289877ff158` | Cega V1 | 362 | clone-erc4626-inflation | 4 |
| 35 | `0x94c5d3c2fe4ef2477e562eee7cccf07ee273b108` | Cega V1 | 366 | clone-erc4626-inflation | 4 |
| 36 | `0xb8ca40e2c5d77f0bc1aa88b2689dddb279f7a5eb` | Bracket Vaults | 373 | clone-erc4626-inflation | 4 |
| 37 | `0x26a70759222b1842a7c72215f64c7fde8db24856` | Wasabix | 379 | clone-erc4626-inflation | 4 |
| 38 | `0x1421d53b2fe0c75d034f81738f3149b54891741e` | ERC-4626 vault | 387 | clone-erc4626-inflation | 4 |
| 39 | `0x747464acdd7228723e4cf9943e09cb0e22828a88` | OpenDAO | 435 | clone-erc4626-inflation | 4 |
| 40 | `0x4296d40183356a770fd8ca3ba0592f0163be9ca3` | xToken | 441 | clone-erc4626-inflation | 4 |
| 41 | `0xc0fce0c5cdbba2d7f7212f3c726b05d5d1b6cf0e` | Lucid Labs | 473 | clone-erc4626-inflation | 4 |
| 42 | `0x1d616dad84dd0b3ce83e5fe518e90617c7ae3915` | PieDAO | 479 | clone-erc4626-inflation | 4 |
| 43 | `0x21f2eafccf161c4e8db7e45825d7251c52d195bc` | ERC-4626 vault | 501 | clone-erc4626-inflation | 4 |
| 44 | `0x096a1e4176ca516bced19b15903eab4654f7ee7a` | ERC-4626 vault | 515 | clone-erc4626-inflation | 4 |
| 45 | `0xabd9c284116b2e757e3d4f6e36c5050aead24e0c` | Defi Yield Protocol | 521 | clone-erc4626-inflation | 4 |
| 46 | `0x79787778b129413160f81b4c598d42489edfb7bf` | ERC-4626 vault | 534 | clone-erc4626-inflation | 4 |
| 47 | `0x48dfa0f826e8026ba51342fff61e9584eccadf69` | Hinkal | 612 | clone-erc4626-inflation | 4 |
| 48 | `0xdd699eae49a3504a28aeb9bd76a3f0369fa08471` | xToken | 632 | clone-erc4626-inflation | 4 |
| 49 | `0x89c15cade77cba4f5c78d1fa845b854623ad8696` | Hinkal | 685 | clone-erc4626-inflation | 4 |
| 50 | `0x2c23276107b45e64c8c59482f4a24f4f2e568ea6` | Bella Protocol | 760 | clone-erc4626-inflation | 4 |
| 51 | `0x44b77e9ce8a20160290fcbaa44196744f354c1b7` | Defi Yield Protocol | 803 | clone-erc4626-inflation | 4 |
| 52 | `0x0c4ff8982c66cd29ea7ea96d985f36ae60b85b1c` | PieDAO | 955 | clone-erc4626-inflation | 4 |
| 53 | `0xfed3d6557dc46a1b25d0a6f666513cb33835864b` | ZTLN-P | 1105 | clone-erc4626-inflation | 4 |
| 54 | `0x206db0a0af10bec57784045e089a418771d20227` | ERC-4626 vault | 1115 | clone-erc4626-inflation | 4 |
| 55 | `0x420cf01fdc7e3c42c3d89ae8799baccbffa9ceaa` | xToken | 1129 | clone-erc4626-inflation | 4 |
| 56 | `0x30df596b7a411d6479544ebec628fa99609d7c2f` | ERC-4626 vault | 1136 | clone-erc4626-inflation | 4 |
| 57 | `0xb50721bcf8d664c30412cfbc6cf7a15145234ad1` | Bitty Vaults | 1138 | clone-erc4626-inflation | 4 |
| 58 | `0x25ec98773d7b4ced4cafab96a2a1c0945f145e10` | stUSDT | 1173 | clone-erc4626-inflation | 4 |
| 59 | `0x06ecfaade8fcb8c1bc58cb05104604282f8a8144` | Amphor | 1174 | clone-erc4626-inflation | 4 |
| 60 | `0x6174a27160f4d7885db4ffed1c0b5fbd66c87f3a` | ERC-4626 vault | 1281 | clone-erc4626-inflation | 4 |
| 61 | `0x76911e11fddb742d75b83c9e1f611f48f19234e4` | Defi Yield Protocol | 1375 | clone-erc4626-inflation | 4 |
| 62 | `0x5b6c72333d56c37a155eb024ee4161ff1c3f04c5` | ERC-4626 vault | 1405 | clone-erc4626-inflation | 4 |
| 63 | `0x828ec6e678a40c251f1f37da389db0f820af6f9d` | xToken | 1429 | clone-erc4626-inflation | 4 |
| 64 | `0x14794665d2f467a6e393e1a7210c49a1aa571d77` | ERC-4626 vault | 1436 | clone-erc4626-inflation | 4 |
| 65 | `0xd68871bd7d28572860b2e0ee5c713b64445104f9` | Spice Finance | 1471 | clone-erc4626-inflation | 4 |
| 66 | `0xfc1cf3dc111981ea4372e91f437581524f3721be` | StoneDefi | 1658 | clone-erc4626-inflation | 4 |
| 67 | `0x68f857cf994434251f7327a9a76ae07be00907c1` | ERC-4626 vault | 1789 | clone-erc4626-inflation | 4 |
| 68 | `0x7cd63e9159d2f6cb7be2fe2a67b67812eb23c7ae` | ERC-4626 vault | 102 | clone-erc4626-inflation | 4 |
| 69 | `0xa00f63e85b3d242568a9edecb48f5e2cf879b07b` | ERC-4626 vault | 104 | clone-erc4626-inflation | 4 |
| 70 | `0x501ebf66d76a96d4fb26ccead42957653e16b8b8` | ERC-4626 vault | 105 | clone-erc4626-inflation | 4 |
| 71 | `0x6d134caad0ca29cd6ea145f6c0dc766076690547` | ERC-4626 vault | 109 | clone-erc4626-inflation | 4 |
| 72 | `0xb11134f14d5b94db60d4599dfdc3bf1bba2150e8` | ERC-4626 vault | 116 | clone-erc4626-inflation | 4 |
| 73 | `0xbe69a6e113c4cf31cd5109e616ae95de4979d38e` | ERC-4626 vault | 117 | clone-erc4626-inflation | 4 |
| 74 | `0x54b8a87c9f85dd2515caae1fad2dd85199900076` | ERC-4626 vault | 137 | clone-erc4626-inflation | 4 |
| 75 | `0xbb50a5341368751024ddf33385ba8cf61fe65ff9` | ERC-4626 vault | 143 | clone-erc4626-inflation | 4 |

## Queue

| # | address | name | funds_usd | reason_class | signals | unverified | list | peak |
|---|---|---|---|---|---|---|---|---|
| 1 | `0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9` | BoringDAO | 1009 | clone-proxy-takeover | upgradeable | Y | list-2 | 5 |
| 2 | `0xa0b9cc50c460dde28321c34fcd7161434655a38f` | Skate AMM | 1061 | clone-proxy-takeover | upgradeable | Y | list-2 | 5 |
| 3 | `0x00000069abbb0b1ad6975bcf753eee15d318a0bf` | Asymmetry Finance | 1145 | clone-proxy-takeover | upgradeable | Y | list-2 | 5 |
| 4 | `0x357f55b46821a6c6e476cc32ebb2674cd125e849` | Equilibria | 894 | clone-proxy-takeover | upgradeable | — | list-2 | 5 |
| 5 | `0xb65b67e986d7b097652920d72202f2c78319bc2c` | moto.fun | 2074 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 6 | `0x2153fee80004e22a13f8d4306bf559e5e4d4f0a9` | Ensuro | 2307 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 7 | `0xe1303b2514755a72da4aca9b917d96f16c842c80` | Prodigy.Fi V2 | 2887 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 8 | `0x66a1e37c9b0eaddca17d3662d6c05f4decf3e110` | Rumpel Labs | 3490 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 9 | `0x6a2469944d3f0aa54531dfa6dcb4350f4a150b67` | QIAN | 3855 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 10 | `0x24db6717db1c75b9db6ea47164d8730b63875db7` | Eigenpie | 3891 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 11 | `0x49f583d263e4ef938b9e09772d3394c71605df94` | SKALE Network Bridge | 4000 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 12 | `0x149c4dd9a1f2a4de605be2b63d60540a8865a288` | Silent Protocol | 4178 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 13 | `0x945facb997494cc2570096c74b5f66a3507330a1` | mStable CDP | 4578 | clone-proxy-takeover | upgradeable | — | list-1 | 5 |
| 14 | `0x882ec5a4a22b110be602762e85758a02943de187` | OpenDAO | 110 | clone-erc4626-inflation | vault,lending | Y | list-2 | 4 |
| 15 | `0xc11d6b78d8c609a6cbf66e89dbfea06b011b0aef` | alphagrowth | 110 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 16 | `0x090342961b1de565cd76a7be041f57ec446a577c` | ERC-4626 vault | 113 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 17 | `0xc139190f447e929f090edeb554d95abb8b18ac1c` | Rumpel Labs | 125 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 18 | `0xfae2809935233d4bfe8a56c2355c4a2e7d1fff1a` | PieDAO | 127 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 19 | `0x784e3c592a6231d92046bd73508b3aae3a7cc815` | Cega V1 | 139 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 20 | `0x69cda6eda9986f7fca8a5dba06c819b535f4fc50` | Klondike Finance | 148 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 21 | `0x756ee7fafd2b629641b91e8a2e115e9c4d69078f` | ERC-4626 vault | 155 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 22 | `0x672c973155c46fc264c077a41218ddc397bb7532` | Klondike Finance | 161 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 23 | `0x98b872604f36807169c096241ecd4646021de133` | Cega V1 | 183 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 24 | `0xbfdc482616787b420bc6c710212fe3167e7198e9` | alphagrowth | 217 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 25 | `0x6dc3ce9c57b20131347fdc9089d740daf6eb34c5` | ERC-4626 vault | 237 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 26 | `0xad48a8261b0690c71b70115035eb14afd9a43242` | Diamond Protocol V1 | 251 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 27 | `0x877bba4238ef1dca9bf574561da633049de3a334` | ERC-4626 vault | 285 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 28 | `0x090559d58aab8828c27ee7a7eab18efd5bb90374` | xToken | 299 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 29 | `0x5f9baab8b2d5f446514546efc48b62500ddce48e` | ERC-4626 vault | 301 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 30 | `0x52d7e0a859d979997cb5a8f55f725b443d32a531` | ERC-4626 vault | 303 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 31 | `0xe3d74df89163a8fa1cba540ff6b339d13d322f61` | PieDAO | 337 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 32 | `0x87b918e76c92818db0c76a4e174447aee6e6d23f` | Mover | 342 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 33 | `0x5408a506db076dc330e661ca21e7f84947ef9792` | ERC-4626 vault | 345 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 34 | `0xab8631417271dbb928169f060880e289877ff158` | Cega V1 | 362 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 35 | `0x94c5d3c2fe4ef2477e562eee7cccf07ee273b108` | Cega V1 | 366 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 36 | `0xb8ca40e2c5d77f0bc1aa88b2689dddb279f7a5eb` | Bracket Vaults | 373 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 37 | `0x26a70759222b1842a7c72215f64c7fde8db24856` | Wasabix | 379 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 38 | `0x1421d53b2fe0c75d034f81738f3149b54891741e` | ERC-4626 vault | 387 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 39 | `0x747464acdd7228723e4cf9943e09cb0e22828a88` | OpenDAO | 435 | clone-erc4626-inflation | vault,lending | Y | list-2 | 4 |
| 40 | `0x4296d40183356a770fd8ca3ba0592f0163be9ca3` | xToken | 441 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 41 | `0xc0fce0c5cdbba2d7f7212f3c726b05d5d1b6cf0e` | Lucid Labs | 473 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 42 | `0x1d616dad84dd0b3ce83e5fe518e90617c7ae3915` | PieDAO | 479 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 43 | `0x21f2eafccf161c4e8db7e45825d7251c52d195bc` | ERC-4626 vault | 501 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 44 | `0x096a1e4176ca516bced19b15903eab4654f7ee7a` | ERC-4626 vault | 515 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 45 | `0xabd9c284116b2e757e3d4f6e36c5050aead24e0c` | Defi Yield Protocol | 521 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 46 | `0x79787778b129413160f81b4c598d42489edfb7bf` | ERC-4626 vault | 534 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 47 | `0x48dfa0f826e8026ba51342fff61e9584eccadf69` | Hinkal | 612 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 48 | `0xdd699eae49a3504a28aeb9bd76a3f0369fa08471` | xToken | 632 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 49 | `0x89c15cade77cba4f5c78d1fa845b854623ad8696` | Hinkal | 685 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 50 | `0x2c23276107b45e64c8c59482f4a24f4f2e568ea6` | Bella Protocol | 760 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 51 | `0x44b77e9ce8a20160290fcbaa44196744f354c1b7` | Defi Yield Protocol | 803 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 52 | `0x0c4ff8982c66cd29ea7ea96d985f36ae60b85b1c` | PieDAO | 955 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 53 | `0xfed3d6557dc46a1b25d0a6f666513cb33835864b` | ZTLN-P | 1105 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 54 | `0x206db0a0af10bec57784045e089a418771d20227` | ERC-4626 vault | 1115 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 55 | `0x420cf01fdc7e3c42c3d89ae8799baccbffa9ceaa` | xToken | 1129 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 56 | `0x30df596b7a411d6479544ebec628fa99609d7c2f` | ERC-4626 vault | 1136 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 57 | `0xb50721bcf8d664c30412cfbc6cf7a15145234ad1` | Bitty Vaults | 1138 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 58 | `0x25ec98773d7b4ced4cafab96a2a1c0945f145e10` | stUSDT | 1173 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 59 | `0x06ecfaade8fcb8c1bc58cb05104604282f8a8144` | Amphor | 1174 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 60 | `0x6174a27160f4d7885db4ffed1c0b5fbd66c87f3a` | ERC-4626 vault | 1281 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 61 | `0x76911e11fddb742d75b83c9e1f611f48f19234e4` | Defi Yield Protocol | 1375 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 62 | `0x5b6c72333d56c37a155eb024ee4161ff1c3f04c5` | ERC-4626 vault | 1405 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 63 | `0x828ec6e678a40c251f1f37da389db0f820af6f9d` | xToken | 1429 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 64 | `0x14794665d2f467a6e393e1a7210c49a1aa571d77` | ERC-4626 vault | 1436 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 65 | `0xd68871bd7d28572860b2e0ee5c713b64445104f9` | Spice Finance | 1471 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 66 | `0xfc1cf3dc111981ea4372e91f437581524f3721be` | StoneDefi | 1658 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 67 | `0x68f857cf994434251f7327a9a76ae07be00907c1` | ERC-4626 vault | 1789 | clone-erc4626-inflation | vault | Y | list-2 | 4 |
| 68 | `0x7cd63e9159d2f6cb7be2fe2a67b67812eb23c7ae` | ERC-4626 vault | 102 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 69 | `0xa00f63e85b3d242568a9edecb48f5e2cf879b07b` | ERC-4626 vault | 104 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 70 | `0x501ebf66d76a96d4fb26ccead42957653e16b8b8` | ERC-4626 vault | 105 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 71 | `0x6d134caad0ca29cd6ea145f6c0dc766076690547` | ERC-4626 vault | 109 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 72 | `0xb11134f14d5b94db60d4599dfdc3bf1bba2150e8` | ERC-4626 vault | 116 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 73 | `0xbe69a6e113c4cf31cd5109e616ae95de4979d38e` | ERC-4626 vault | 117 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 74 | `0x54b8a87c9f85dd2515caae1fad2dd85199900076` | ERC-4626 vault | 137 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 75 | `0xbb50a5341368751024ddf33385ba8cf61fe65ff9` | ERC-4626 vault | 143 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 76 | `0xe0437beb5bb7cf980e90983f6029033d710bd1da` | CVI Finance | 156 | clone-spot-oracle | oracle | Y | list-2 | 5 |
| 77 | `0x40b74ac60f4133b31f297767b455b4328d917809` | ERC-4626 vault | 194 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 78 | `0x30987adf0b11dc698438a99ba04ec3a1ab2c7eab` | ERC-4626 vault | 199 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 79 | `0x9757515d91bd7c095f7aac9cad3d5fb32f759e76` | ERC-4626 vault | 248 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 80 | `0xbb30c3b6046debcbe941281218d18dec8ecebeb5` | ERC-4626 vault | 251 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 81 | `0x5103d3ee6d599984609daaadd3a439152cc0c392` | ERC-4626 vault | 252 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 82 | `0x1abd0403591be494771115d74ed9e120530f356e` | ERC-4626 vault | 252 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 83 | `0x660e2fc185a9ffe722af253329ceaad4c9f6f928` | ERC-4626 vault | 256 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 84 | `0x0e0da40101d8f6eb1b1d6b0215327e8452e0bc60` | CVI Finance | 353 | clone-spot-oracle | oracle | Y | list-2 | 5 |
| 85 | `0x180f6e72a19da2a791d40433c619c553fe268d94` | ERC-4626 vault | 359 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 86 | `0x5f35d1cef957467f4c7b35b36371355170a0dbb1` | ERC-4626 vault | 362 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 87 | `0x5c51fa43608a140e4510f676d36188ba1cd1fcae` | ERC-4626 vault | 401 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 88 | `0x4cb280e63251b9ab24a54def74bf5995d82ff398` | ERC-4626 vault | 501 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 89 | `0x9c78040069fd3de1ddf433e4eee2db6e44869083` | ERC-4626 vault | 517 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 90 | `0x4bc05cb7159bd092d1c46888c735d21e8185c1ac` | ERC-4626 vault | 572 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 91 | `0x82f01dc127f78ebd3e7bec68b243f519b074fc15` | ERC-4626 vault | 590 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 92 | `0x2d45c2835cea592f75e72e656932aa60d474ddf3` | ERC-4626 vault | 615 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 93 | `0x3dfe70b05657949a5db340754ad664810ac63b21` | ERC-4626 vault | 642 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 94 | `0x1f3d2ec885483042365bde1a8edf5bbc505450fd` | ERC-4626 vault | 651 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 95 | `0xea1ef816ddfa86a8e9690423c88c1512c01d1799` | ERC-4626 vault | 741 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 96 | `0x5f342382d5f77f0f99e8f26161e689df6c7cded3` | ERC-4626 vault | 745 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 97 | `0xca66317ea1e566d72fd1d333c22bb0223273226a` | ERC-4626 vault | 846 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 98 | `0x2643c6731199d36ce3c9533e4c3f7eeab2dac94a` | ERC-4626 vault | 977 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 99 | `0x09ace8b2f2fe2189a5b37046bbafa29dce31c920` | ERC-4626 vault | 1004 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 100 | `0x20e934c725b6703f0ac696f1689008057db9ac44` | ERC-4626 vault | 1080 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 101 | `0x43a32d4f6c582f281c52393f8f9e5ace1d4a1e68` | ERC-4626 vault | 1093 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 102 | `0x395da89bdb9431621a75df4e2e3b993acc2cab3d` | ERC-4626 vault | 1118 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 103 | `0x5fe86b1adee4b18f6a8c55ea0bdbb55e2e445159` | ERC-4626 vault | 1250 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 104 | `0x1c7ce003dccdd769581034394f680964aa94d123` | ERC-4626 vault | 1261 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 105 | `0x025a05f1967521806bb4c8a10ba4b8c00a794f65` | Vesper V2 | 1283 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 106 | `0xe9b725010a9e419412ed67d0fa5f3a5f40159d32` | ERC-4626 vault | 1795 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 107 | `0x3527663fa14f1799ffdf54fdc7e721d2fb8e88d5` | ERC-4626 vault | 1843 | clone-erc4626-inflation | vault | — | list-2 | 4 |
| 108 | `0x8824f63f990fde4b46c6f2ec26356472db680563` | ERC-4626 vault | 1876 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 109 | `0xcdbbe7c7ae6c756bd14b5787fc0bcf66ad5acfc3` | ERC-4626 vault | 1985 | clone-erc4626-inflation | — | — | excluded-below-2000 | 4 |
| 110 | `0xe1077f6942e9fd6bda4678b82e6bfc7fea090a0b` | ERC-4626 vault | 2073 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 111 | `0x47259058895e78825e88b7f3a2c9b3bd5051c4e4` | ERC-4626 vault | 2137 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 112 | `0x02991ee6134dee504668e2227c5879dd78efcdc3` | ERC-4626 vault | 2248 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 113 | `0xf72bd5a56de97840f1fdd3641b556126c10aa1c4` | ERC-4626 vault | 2473 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 114 | `0x093272c07700d3ca5301c3bf9b3a392624179e2f` | ERC-4626 vault | 2500 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 115 | `0xef8629d568adca04d0ac52c7388d5377872d7f61` | ERC-4626 vault | 2508 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 116 | `0x998d7b14c123c1982404562b68eddb057b0477cb` | ERC-4626 vault | 2517 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 117 | `0x46e9893422b9ae9246793489433f72c548cb2455` | ERC-4626 vault | 2642 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 118 | `0xd066649bcb7d8d3335fe29cad0aed6e17d5828b5` | ERC-4626 vault | 2689 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 119 | `0xe8f4856315c30282d1913c21921df59ea6ccb664` | ERC-4626 vault | 2738 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 120 | `0x82fe329f4a9c4bcedc8a33f004337d51921d55e4` | ERC-4626 vault | 2869 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 121 | `0x99351baed3d8ab544ccb08af96a105910fda71e7` | ERC-4626 vault | 3000 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 122 | `0xee847a804b67f4887c9e8fe559a2da4278defb52` | ERC-4626 vault | 3004 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 123 | `0x51a80238b5738725128d3a3e06ab41c1d4c05c74` | unshETH LSDVault | 3034 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 124 | `0x03d1ec0d01b659b89a87eabb56e4af5cb6e14bfc` | ERC-4626 vault | 3198 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 125 | `0x3f453133ea14550b883805672b2871b0ac295462` | ERC-4626 vault | 3816 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 126 | `0xc428439fb7b1efe56360eb837ca98f551fdd9b26` | ERC-4626 vault | 4539 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 127 | `0xf419c7674536f6b32b9a73929dbf4ff5c2386d5c` | ERC-4626 vault | 4991 | clone-erc4626-inflation | vault | — | list-1 | 4 |
| 128 | `0x5de8ab7e27f6e7a1fff3e5b337584aa43961beef` | SMARDEX P2P Lending | 107 | lending-underscanned | lending | Y | list-2 | 4 |
| 129 | `0x3bac111a6f5ed6a554616373d5c7d858d7c10d88` | SynStation | 186 | lending-underscanned | lending | Y | list-2 | 4 |
| 130 | `0x1623a55e0ba2384afd7511d6d7f77cf28790b5c5` | Bondlink Finance | 217 | lending-underscanned | lending | Y | list-2 | 4 |
| 131 | `0x1ddf85abdf165d2360b31d9603b487e0275e3928` | OpenDAO | 241 | lending-underscanned | lending | Y | list-2 | 4 |
| 132 | `0xead9190db1a6a5f4262572845cf75c31e474fd4c` | cSigma Finance | 254 | lending-underscanned | lending | Y | list-2 | 4 |
| 133 | `0x8da513d9b614d0a473eaf294e3e531cd4eea9984` | Vailox | 317 | lending-underscanned | lending | Y | list-2 | 4 |
| 134 | `0x0c7d5ae016f806603cb1782bea29ac69471cab9c` | BiFi | 339 | lending-underscanned | lending | Y | list-2 | 4 |
| 135 | `0x70467416507b75543c18093096ba4612a9261db8` | Fringe V2 | 350 | lending-underscanned | lending | Y | list-2 | 4 |
| 136 | `0xc18360217d8f7ab5e7c516566761ea12ce7f9d72` | Beta Finance V1 | 500 | lending-underscanned | lending | Y | list-2 | 4 |
| 137 | `0x7d027083e55724a1082b8cdc51ee90781f41ff14` | Match Finance | 710 | lending-underscanned | lending | Y | list-2 | 4 |
| 138 | `0xd372a3221021df72eda38f77117d3a95f057e163` | DeFIL | 903 | lending-underscanned | lending | Y | list-2 | 4 |
| 139 | `0xeae019ef845a4ffdb8829210de5d30ac6fbb5371` | B.Protocol | 936 | lending-underscanned | lending | Y | list-2 | 4 |
| 140 | `0x00aa1c57e894c4010fe44cb840ae56432d7ea1d1` | Drops | 997 | lending-underscanned | lending | Y | list-2 | 4 |
| 141 | `0x87f6faa87358b628498e8dcd4e30b0378feafd07` | CHFRY Finance | 1016 | lending-underscanned | lending | Y | list-2 | 4 |
| 142 | `0xc9fe6e1c76210be83dc1b5b20ec7fd010b0b1d15` | Fringe V2 | 1115 | lending-underscanned | lending | Y | list-2 | 4 |
| 143 | `0x01aa4629b756b1222cb5541da0255b4f473f3a11` | Beta Finance V1 | 1223 | lending-underscanned | lending | Y | list-2 | 4 |
| 144 | `0xd1ffa2cbae34ff85cefecdab0b33e7b1dc19024b` | CHFRY Finance | 1261 | lending-underscanned | lending | Y | list-2 | 4 |
| 145 | `0x588c13e685e44b22dc6647937481c816e5fee086` | Drops | 1309 | lending-underscanned | lending | Y | list-2 | 4 |
| 146 | `0x25299e9ec27c242465587b8a2aa70bce02636cda` | Unlockd V2 | 1556 | lending-underscanned | lending | Y | list-2 | 4 |
| 147 | `0x1f947ed7ccf11d3b39fc39926c95d9d928b90e98` | Rari Capital | 137 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 148 | `0x82eecf1f719eed527efab332fe84b91b91b91c60` | Rari Capital | 145 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 149 | `0xa7a668d24daa8cb8c028c04005c28bfdc6f637dd` | Rari Capital | 148 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 150 | `0x92697ec57d547bbd6c47e188b9d205880fa51e5d` | Rari Capital | 154 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 151 | `0xc10d8be5c570856bec7d936d4e1e1f51308ff6d4` | Rari Capital | 169 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 152 | `0x20c461b0214eebb71be32b6a1605ed992a8f1410` | Rari Capital | 178 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 153 | `0x18f49849d20bc04059fe9d775df9a38cd1f5ec9f` | Rari Capital | 181 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 154 | `0x258592543a2d018e5bdd3bd74d422f952d4b3c1b` | Rari Capital | 183 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 155 | `0xc12b58d31b97dbd7f092db5cc69ad321a0ad747e` | Rari Capital | 200 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 156 | `0x19d13b4c0574b8666e9579da3c387d5287af410c` | Rari Capital | 206 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 157 | `0x325e3257286eb040aabb1128c21a55cf82e25901` | Rari Capital | 235 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 158 | `0x6f28b8237c3c2233235f8991069dba45abdb6ced` | Rari Capital | 238 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 159 | `0x484d065931c19b8dc2d915b2cf23bb142c2c7637` | Rari Capital | 261 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 160 | `0xf06f65a6b7d2c401fcb8b3273d036d21fe2a5963` | Rari Capital | 296 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 161 | `0xff859f9a808a78833f9661310101c853a1dfe6c6` | Rari Capital | 299 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 162 | `0xbfb6f7532d2db0fe4d83abb001c5c2b0842af4db` | Rari Capital | 299 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 163 | `0x6f95d4d251053483f41c8718c30f4f3c404a8cf2` | Rari Capital | 312 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 164 | `0x3e5c122ffa75a9fe16ec0c69f7e9149203ea1a5d` | Rari Capital | 316 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 165 | `0x3b624de26a6ceba421f9857127e37a5efd8ecaab` | Rari Capital | 355 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 166 | `0xca9219aef43d66e80a5167b0c3b434568b3371c9` | Rari Capital | 366 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 167 | `0x712808b1e8a17f90df1bc0faa33a6a211c3311a9` | Rari Capital | 374 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 168 | `0xc69c916ce44f2cfa50a28e0e3002e818804217b5` | Rari Capital | 380 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 169 | `0xe71b4cb8a99839042c45cc4caca31c85c994e79f` | Rari Capital | 397 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 170 | `0x8ad7472631695420626c17ee0f8cecfea480caff` | Rari Capital | 401 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 171 | `0x10e0953c583f9fdfcad13bdb9a81d0744e3933d4` | Rari Capital | 415 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 172 | `0x4b3d6ad21cb4c02c0f38a131ae2358c2813af13f` | Rari Capital | 482 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 173 | `0xe468d0244d75b9b18b27cb682aec3ab35d33663b` | Rari Capital | 483 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 174 | `0xbe9c32d18668b4d1cd149291d268bc5258318f0b` | Rari Capital | 505 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 175 | `0x6780b4681aa8efe530d075897b3a4ff6ca5ed807` | Rari Capital | 560 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 176 | `0x03c2d837e625e0f5cc8f50084b7986863c82102c` | Rari Capital | 564 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 177 | `0xeb37ce0db663a742df93e23ea7ba78016e82be39` | Rari Capital | 564 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 178 | `0x70570d2bbfa62aad8e1597225a944ef363530730` | Rari Capital | 689 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 179 | `0x41284a88d970d3552a26fae680692ed40b34010c` | Percent Finance | 706 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 180 | `0x0028a459d6705b30333e98d5bcb34dd1b21e2a89` | Rari Capital | 708 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 181 | `0xd9c1109bed723ea8b78d0ac1757586955666bb00` | Rari Capital | 713 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 182 | `0x8b3fa5350b46dcf0d0918414371abc92d97f272f` | Rari Capital | 804 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 183 | `0x673f9cb9bea1525bd982c061125c285d79d8fbe2` | Rari Capital | 888 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 184 | `0x99e582374015c1d2f3c0f98d0763b4b1145772b7` | Percent Finance | 939 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 185 | `0xf527853cf3d2a83093947a0c300727c58e57be7d` | Rari Capital | 996 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 186 | `0xd8f3793a26f9e7f8b0337b4ceeb0ff38bd72a87b` | Rari Capital | 1101 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 187 | `0xfbd8aaf46ab3c2732fa930e5b343cd67cea5054c` | Rari Capital | 1154 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 188 | `0x599f56d82fef1e8dc5a5a1bba9a165c92bcab261` | Rari Capital | 1296 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 189 | `0x10362af7718468263243ef2419d3096a5f35c8d7` | Rari Capital | 1300 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 190 | `0x0302f55dc69f5c4327c8a6c3805c9e16fc1c3464` | Rari Capital | 1301 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 191 | `0x7e9ce3caa9910cc048590801e64174957ed41d43` | Rari Capital | 1327 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 192 | `0x8ea8fcd938d45d2461e023b96044acab4780f07b` | Rari Capital | 1386 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 193 | `0xaff95ac1b0a78bd8e4f1a2933e373c66cc89c0ce` | Rari Capital | 1507 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 194 | `0x1f9045e2bf5d7f64898f5492df8980e92cb344c7` | Rari Capital | 1521 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 195 | `0x2f251e9074e3a3575d0105586d53a92254528fc5` | Rari Capital | 1531 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 196 | `0x0f43a7e3f7b529015b0517d0d9aa9b95701fd2cb` | Rari Capital | 1564 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 197 | `0x1ba12ae1fcfadd08fa37db849ef4b6e11e435357` | Rari Capital | 1667 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 198 | `0x35036a4b7b012331f23f2945c08a5274ced38ac2` | Rari Capital | 1758 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 199 | `0x5acf7a7da7ee26e7c586d84ec6ad69626bc160f8` | Rari Capital | 1768 | lending-underscanned | — | — | excluded-below-2000 | 4 |
| 200 | `0xd76b7060f1b646fa14740ff6ac670a4f0a6fc5e3` | BiFi | 2032 | lending-underscanned | lending | — | list-1 | 4 |
| 201 | `0xe4baf69b887843ab6a0e82e8baea49010ff619af` | Multiplier | 4682 | lending-underscanned | lending | — | list-1 | 4 |
| 202 | `0xa6bb68ff426a57029ec06162cb1a9f7aadde5354` | univ2-fork-unknown | 103 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 203 | `0x4908d3c000a602529b1b21fcb37ddbaa8ef21216` | univ2-fork-unknown | 103 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 204 | `0x073ae4eb8aad32756eae3e33902e5b94ed22610a` | univ2-fork-unknown | 104 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 205 | `0x5996451816d3789ade9456dd27512895e1312003` | univ2-fork-unknown | 107 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 206 | `0xe1ab8a2e0c647b2f6d564ad64a248766b92f1e2d` | univ2-fork-unknown | 108 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 207 | `0xc82b72078878f25dacc5741fd04322d0b5f18991` | univ2-fork-unknown | 115 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 208 | `0xee5ec31ca426135281c661500bb2f1639be81f88` | univ2-fork-unknown | 116 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 209 | `0xc134922a5d9117dbb97904b61fcbe04b803b5c50` | univ2-fork-unknown | 134 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 210 | `0xd463517696c888938f1df5b9db6e09ee7d9f0e94` | univ2-fork-unknown | 143 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 211 | `0xfc6b05f3e5fcdd27995d6c17a71cf8e7a8f966d2` | univ2-fork-unknown | 146 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 212 | `0xd2606dd09880e94057399e38ea26140e64744a05` | univ2-fork-unknown | 169 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 213 | `0x69f06a51b0b8d9c2f12fcef6e5c89298395e8810` | univ2-fork-unknown | 171 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 214 | `0xa2e0f89d32abf062c39f2205b17a72fa70353bd2` | univ2-fork-unknown | 176 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 215 | `0xab850984c05bd5581f4f6e4bbff9d8cc3d8273d9` | univ2-fork-unknown | 176 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 216 | `0x3750c1fcd35eae956c7a57e773d1496c41d2759a` | univ2-fork-unknown | 204 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 217 | `0x338c6807b433a95b2e2347e0cffacd92b97fe8e2` | univ2-fork-unknown | 300 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 218 | `0x692a2c1dc88b53eed63f852432072a2808d4fd2f` | univ2-fork-unknown | 320 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 219 | `0x4429dbcbae70d33895640537b78859c47b0f980b` | univ2-fork-unknown | 325 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 220 | `0x83d63ce48d772106ae09411f41613d976f247223` | univ2-fork-unknown | 326 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 221 | `0xac10f17627cd6bc22719ceebf1fc524c9cfdc255` | univ2-fork-unknown | 402 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 222 | `0x9dd78ea2b7a92b6cb5d4a495dac34f8641070ceb` | univ2-fork-unknown | 457 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 223 | `0x233ab72c3a6e03aa3a2e896ab9ec1866dc0a9448` | univ2-fork-unknown | 511 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 224 | `0x1a9ec5d0855d2af8f504fc4047e2097f09d6e55d` | univ2-fork-unknown | 532 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 225 | `0xdf5e69fa81f3d2b7b6c14ac9069c4705ee38e95f` | univ2-fork-unknown | 565 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 226 | `0xca3d6a94759cb675f0ac10a76fc0da6ee6bf6e7b` | univ2-fork-unknown | 569 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 227 | `0x7c50e11364ee1811842df7c282a49a8db4b68a7a` | univ2-fork-unknown | 612 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 228 | `0xf40bc8b92bfb87d8527a2f97538c0ebda4bbed11` | univ2-fork-unknown | 623 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 229 | `0x7e8dc7c0fef7bb84304cc5c2dacf5e583198ca4f` | univ2-fork-unknown | 695 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 230 | `0xfbbdfe495260a1e711e039ab2cd987cd638bb9b3` | univ2-fork-unknown | 708 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 231 | `0xe291b2a982289f0aa01d0c96c916a9f37b11fa8e` | univ2-fork-unknown | 723 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 232 | `0x8df8447f2b83c66a930e21a49eeac22267612d2d` | univ2-fork-unknown | 725 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 233 | `0xbfa25cac44a4e9a23263c8c11eee5065b7cc18a1` | univ2-fork-unknown | 826 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 234 | `0xd911db619c3f563c4471329349882da9afe50580` | univ2-fork-unknown | 855 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 235 | `0x3ed1b76c68f6fd1c645e1e596cec0c77f56711cc` | univ2-fork-unknown | 916 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 236 | `0x8a02454ca2565d25f65531111b6dcac1e5f1d671` | univ2-fork-unknown | 1428 | amm-fork-thin-pool | — | Y | list-2 | 4 |
| 237 | `0x2959501164a828050a4a219c210f661b081f9c70` | univ2-fork-unknown | 102 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 238 | `0x20f1e9b44fc066191ec08d98517390674b25ffb9` | univ2-fork-unknown | 102 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 239 | `0xfb8eda8275802db501ea558510182abd64e19994` | univ2-fork-unknown | 108 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 240 | `0xa650b56015736a22dd19c176901fa42d13a71e86` | univ2-fork-unknown | 118 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 241 | `0x5f9946fd12cb85ca24f906b200ccf4c62d780305` | univ2-fork-unknown | 121 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 242 | `0xbab102eca9bce61ea49efc713bac3dff6e5512d9` | univ2-fork-unknown | 122 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 243 | `0x5c00b1b9b6357f782cc01910b54d96f4690d1eb5` | univ2-fork-unknown | 125 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 244 | `0xb628143b29a26f1e47a21cba5dd75fc7ab773670` | univ2-fork-unknown | 131 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 245 | `0x8b869206b30cb45994d26a96139ce71cf5d1e13b` | univ2-fork-unknown | 137 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 246 | `0x694736a70d63241884e891fd0416b1ada7ff2bdb` | univ2-fork-unknown | 139 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 247 | `0x8817d938ea8168b64cec828a6371d5fcd6c1961e` | univ2-fork-unknown | 143 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 248 | `0x8c22e8ddf5c333e346b58b65ee75ad40cf0c74a2` | univ2-fork-unknown | 148 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 249 | `0xdc7c280063812eef49bfba36c16c629b42b49609` | univ2-fork-unknown | 149 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 250 | `0x63671a5625b4923eba647df340a01dcf9db943f5` | univ2-fork-unknown | 161 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 251 | `0x7948f0fce3a46d8f3c40bcf4c06a357bae74056a` | univ2-fork-unknown | 184 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 252 | `0x652960fc3e2faa494d9c84e62f0901a86a528fb8` | univ2-fork-unknown | 186 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 253 | `0x9f872cd72521a6189ddf25cd752e6386129647d9` | univ2-fork-unknown | 187 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 254 | `0x5b255e213bcce0fa8ad2948e3d7a6f6e76472db8` | univ2-fork-unknown | 187 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 255 | `0x69a66b6885d04d6724fd85feb6c77c09263ab52b` | univ2-fork-unknown | 198 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 256 | `0x06008a785bb761476bc5ade0c3da3e4af62ef5b1` | univ2-fork-unknown | 204 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 257 | `0x2110275cae57a63d661626742bf0a459a7f43d44` | univ2-fork-unknown | 260 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 258 | `0xddaaae3af2bf94ef7a962040ce0c46ea8e546edd` | univ2-fork-unknown | 358 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 259 | `0x9646684b5a2be6dc024ed60b8383be3650e56f4e` | univ2-fork-unknown | 399 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 260 | `0x44b5d8d7c0a93fe769a30d92b9a1e5500b3e9897` | univ2-fork-unknown | 462 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 261 | `0xad9fc170bdbd30d2ec38cf26b75e6238fe9ec48f` | univ2-fork-unknown | 467 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 262 | `0xe304af407e07465d0a859de9f38324099c9b3a93` | univ2-fork-unknown | 524 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 263 | `0x4c55011e3b909e3e8ec3b381d184260bf2c472bf` | univ2-fork-unknown | 627 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 264 | `0x948f5d52713fa7fef212703678546b903895d807` | univ2-fork-unknown | 631 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 265 | `0x990e24ddd35d532b501731388b8bba0badc88eba` | univ2-fork-unknown | 712 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 266 | `0xa429a6c5b5ef08391d96e5f1d386e2e2909b7604` | univ2-fork-unknown | 886 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 267 | `0x33d666286b541e4964d73b583eda72f28d94fb45` | univ2-fork-unknown | 1014 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 268 | `0x688a82f0957b808d4ae03d6d7f39d8b90b1043a3` | univ2-fork-unknown | 1069 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 269 | `0xea829640baade56e4894f142371f1cbb9250cfbf` | univ2-fork-unknown | 1255 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 270 | `0x9ab3fb581f16cc635681a94a32251d5d23eace4f` | univ2-fork-unknown | 1500 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 271 | `0xc19c5b63705807079dbf6d54071f9113233283f5` | univ2-fork-unknown | 1620 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 272 | `0x61583697a9f4dc2e40ea6afec2502c4a76a8785d` | univ2-fork-unknown | 1620 | amm-fork-thin-pool | — | — | list-2 | 4 |
| 273 | `0x68a4cb4c6b12f598509cfb32919d1951e63aa9b6` | univ2-fork-unknown | 1761 | amm-fork-thin-pool | — | — | excluded-below-2000 | 4 |
| 274 | `0x2a79a0e0c226a58eeb99c5704d72d49177cc7516` | univ2-fork-unknown | 2044 | amm-fork-thin-pool | — | — | list-1 | 4 |
| 275 | `0x2ad95483ac838e2884563ad278e933fba96bc242` | univ2-fork-unknown | 2554 | amm-fork-thin-pool | — | — | list-1 | 4 |
| 276 | `0xe2e5aca8e483a4c057892ee1f03bebc9bfa1f9c2` | univ2-fork-unknown | 4749 | amm-fork-thin-pool | — | — | list-1 | 4 |
| 277 | `0x12e74f3c61f6b4d17a9c3fdb3f42e8f18a8bb394` | VII Finance | 111 | unverified-leftover | — | Y | list-2 | 3 |
| 278 | `0x7eaf9c89037e4814dc0d9952ac7f888c784548db` | UniFarm | 117 | unverified-leftover | — | Y | list-2 | 3 |
| 279 | `0x72f020f8f3e8fd9382705723cd26380f8d0c66bb` | UniFarm | 121 | unverified-leftover | — | Y | list-2 | 3 |
| 280 | `0x12a4f34d27b1d54defd4eb39799971e26d9025e7` | Ensuro | 125 | unverified-leftover | — | Y | list-2 | 3 |
| 281 | `0xfb04d48e4ce9c042188ef933ff4cf58921ab59b8` | YieldFlow Yield Farming | 139 | unverified-leftover | — | Y | list-2 | 3 |
| 282 | `0x3315351f0b20595777a28054ef3d514bdc37463d` | Varen | 142 | unverified-leftover | — | Y | list-2 | 3 |
| 283 | `0x5522a4339a8722ba4471d93f3851ccf55a7d3d2d` | Defx | 147 | unverified-leftover | — | Y | list-2 | 3 |
| 284 | `0xcac7092de2d6af9dfad327dc0ebef4e099b2777e` | Varen | 153 | unverified-leftover | — | Y | list-2 | 3 |
| 285 | `0x204c87cda5daac87b2fc562bfb5371a0b066229c` | BoringDAO | 176 | unverified-leftover | — | Y | list-2 | 3 |
| 286 | `0xb48bc8c844859d2a197d45291e375fe17670cdd0` | Varen | 199 | unverified-leftover | — | Y | list-2 | 3 |
| 287 | `0xac36a41da8f069c4874dda60e073b5dcf889b56e` | YieldFlow Yield Farming | 229 | unverified-leftover | — | Y | list-2 | 3 |
| 288 | `0xc00e94cb662c3520282e6f5717214004a7f26888` | Angle | 233 | unverified-leftover | — | Y | list-2 | 3 |
| 289 | `0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b` | B.Protocol | 258 | unverified-leftover | — | Y | list-2 | 3 |
| 290 | `0x3ff53a3cc3729a6cb089396addb5f977668c5ffd` | ChickenSwap | 264 | unverified-leftover | — | Y | list-2 | 3 |
| 291 | `0x6659423929e1a00119fc3f79c8e4f443cc6fd36f` | Goldsand by InshAllah | 266 | unverified-leftover | — | Y | list-2 | 3 |
| 292 | `0xb5087f95643a9a4069471a28d32c569d9bd57fe4` | Bunni v1 | 272 | unverified-leftover | — | Y | list-2 | 3 |
| 293 | `0x9d0731968ae480936c25ae841573842eef6d65a4` | YieldFlow Yield Farming | 292 | unverified-leftover | — | Y | list-2 | 3 |
| 294 | `0x39166b36a25a4a98d6b7c21d429f4740c6a5e94c` | Clovis | 294 | unverified-leftover | — | Y | list-2 | 3 |
| 295 | `0x74b23882a30290451a17c44f4f05243b6b58c76d` | BoringDAO | 337 | unverified-leftover | — | Y | list-2 | 3 |
| 296 | `0x8d999a2f262ffda47a734b987d1a15bc984e45be` | Risk Harbor | 407 | unverified-leftover | — | Y | list-2 | 3 |
| 297 | `0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2` | mStable V2 | 429 | unverified-leftover | — | Y | list-2 | 3 |
| 298 | `0xdc4e6dfe07efca50a197df15d9200883ef4eb1c8` | Angle | 434 | unverified-leftover | — | Y | list-2 | 3 |
| 299 | `0x8f24e100d785daaa70e9ff461a831a0354499f4e` | XUSD Money | 440 | unverified-leftover | — | Y | list-2 | 3 |
| 300 | `0xd46ba6d942050d489dbd938a2c909a5d5039a161` | Meter Passport | 471 | unverified-leftover | — | Y | list-2 | 3 |
