# Under-$5,000 high-likelihood scan queue 2 (300 contracts)

Generated 2026-11-26T05:34:12Z · chain: ethereum · 300 contracts

This is the follow-up to `small_value_under5k_queue.json`. That file is unchanged. A push of `eth-scanner/signal-rerun.trigger` still scans queue 1.

## Cutoff rules

- **Under $5,000:** native ETH plus WETH, USDC, USDT, DAI, WBTC, stETH, wstETH, and USDe, priced when this list was built. Floor is $100. Cap is exclusive of $5,000.
- **High likelihood:** the same classes and the same score order as queue 1. Upgradeable proxy, spot oracle, ERC-4626 vault, and lending outrank an AMM fork, which outranks an unverified leftover.
- **Where these came from:** Uniswap V2 fork factories via `allPairs` (not Uniswap, Sushi, or Pancake), Compound-fork `getAllMarkets`, and ERC-4626 vault addresses from the DefiLlama registries. A pair had to answer `getReserves`, a market `exchangeRateStored`, and a vault `totalAssets`.
- **Not this queue:** every address in queue 1, the signal-rerun seen skip list, the signal-rerun seed, hand exclusions, list-2 canonical names, and every address already in the candidate pools. 31 further measured rows stayed off so the list stays at 300. The 30 unverified leftovers left over from queue 1 score below these AMM forks, so they stay deferred.
- **Stored scans:** the batch job skips a `signal-rerun:<address>` row already stored as done. This build could not read the production scan tables, so it also dropped the committed seen skip list and every address already in the pools.
- **Order:** score descending, then smaller funds, then address.

## Selection sources / breakdown

| reason_class | n | class score | peak |
|---|---|---|---|
| amm-fork-thin-pool | 266 | 38 | 4 |
| lending-underscanned | 29 | 44 | 4 |
| clone-erc4626-inflation | 5 | 46 | 4 |

- Lists: compound-fork-getAllMarkets=29, erc4626-registry=5, univ2-fork-allPairs=266
- Funds: <=$1,900: 240, <=$5,000: 300 (median $450)

## How to run it

Signal-rerun reads **one** queue and scans **one batch**, then stops. Finished addresses are the `signal-rerun:<address>` rows already stored as done.

- **Batch:** 75 contracts, proxy cap 250,000 CU. Four batches cover this queue.
- **Queue 2 trigger:** push `eth-scanner/signal-rerun-q2.trigger` to `main`. The workflow runs `--small-value-batch --queue 2`. Each push must change the file. One push scans one batch.
- **Queue 2, manually:** Actions → *eth-scanner-signal-rerun* → *Run workflow* → mode `small-value-batch`, queue `2`.
- **Queue 2, local:** `cd eth-scanner && python -m eth_scanner signal-rerun --small-value-batch --queue 2 --batch-size 75 --budget-cu 250000 --deadline-minutes 55 --dry-run --json`
- **Queue 1 is unchanged:** push `eth-scanner/signal-rerun.trigger`, or run the workflow with queue `1` (the default). That command does not pass `--queue`. A push that includes the queue 1 file stays on queue 1.

Watch the Actions log for `mode` (`small-value-under5k-2`), `queue_id` (`2`), `selected`, `rerun_count`, `skipped_finished`, `cu_used`, and `status`.

## First batch

| # | address | name | funds_usd | reason_class | peak |
|---|---|---|---|---|---|
| 1 | `0x18e2f4f2e6565187fce73ecc707579e5f7933f74` | zensats | 112 | clone-erc4626-inflation | 4 |
| 2 | `0xcf8eafc3b1d92801238faadc22d2a7b83fb96c10` | ERC-4626 vault | 240 | clone-erc4626-inflation | 4 |
| 3 | `0x8417430a31851ae0a36a854394227c5d86be8fc9` | ammalgam-vaults | 503 | clone-erc4626-inflation | 4 |
| 4 | `0xaf53431488e871d103baa0280b6360998f0f9926` | protectorate | 564 | clone-erc4626-inflation | 4 |
| 5 | `0x7a12d4b719f5aa479ecd60defed909fb2a37e428` | RockSolid | 3903 | clone-erc4626-inflation | 4 |
| 6 | `0x830dacd5d0a62afa92c9bc6878461e9cd317b085` | onyx | 101 | lending-underscanned | 4 |
| 7 | `0x8c83b281fa131360fc90a83397a3afa5c1d8e8a7` | cozy | 115 | lending-underscanned | 4 |
| 8 | `0xf146c26136c1f80c9f0967d27bcb7e500d45681f` | cozy | 137 | lending-underscanned | 4 |
| 9 | `0x63d6b99659f7b05b054deef582f5daaa51780e80` | damm-finance | 157 | lending-underscanned | 4 |
| 10 | `0x9435f39c4a1a51765dd4294fc84fe024f5ace0d2` | cream | 165 | lending-underscanned | 4 |
| 11 | `0xba2e90b4dcdb235e46b9554360e31f2afa1d8b35` | cream | 176 | lending-underscanned | 4 |
| 12 | `0xf428189d73a7a17b8eb8f5637654063edd728df8` | minterest | 211 | lending-underscanned | 4 |
| 13 | `0x6365b24999105afd1bc44ddd43718b2407e43298` | tonpound | 212 | lending-underscanned | 4 |
| 14 | `0xc5fa52aa356203ae375d0a98d7423c350b5b31c6` | tonpound | 217 | lending-underscanned | 4 |
| 15 | `0x06078583447f9c0b4b688ace305de8a342c7af2b` | tonpound | 234 | lending-underscanned | 4 |
| 16 | `0x7d4377114fd3c61c59d72de48102bf6acd3882b1` | cozy | 250 | lending-underscanned | 4 |
| 17 | `0xbf0852a95ec76e87f7431fa505b27937c9836372` | damm-finance | 267 | lending-underscanned | 4 |
| 18 | `0x118823514681353634ff95837939e783d85b18af` | damm-finance | 353 | lending-underscanned | 4 |
| 19 | `0xc42d8f3d791c107c458b2fea025a36669b51fc5f` | cream | 375 | lending-underscanned | 4 |
| 20 | `0xf635fdf9b36b557bd281aa02fdfaebec04cd084a` | bao-markets | 395 | lending-underscanned | 4 |
| 21 | `0x41f4766b0368f43d1312f63350635eb155040832` | minterest | 509 | lending-underscanned | 4 |
| 22 | `0x7ecc1d6fc7f63b003de4391dfd4c78365e844e1d` | cozy | 600 | lending-underscanned | 4 |
| 23 | `0x19b3bde6f02fc2c985947dcc1dc2a4cddfd43ee8` | cream | 731 | lending-underscanned | 4 |
| 24 | `0xaef3f76e426d2f0139eaecd19672dd9c9a3fc582` | cozy | 919 | lending-underscanned | 4 |
| 25 | `0x97f84825d16b32ca97afc1c8bf51ab1086bcff1f` | cozy | 925 | lending-underscanned | 4 |
| 26 | `0x9affb6d8568cefa2837d251b1553967430d1a5e5` | cozy | 1169 | lending-underscanned | 4 |
| 27 | `0x43647239ede197099b57bf72d0373f8049acfb0f` | cozy | 1378 | lending-underscanned | 4 |
| 28 | `0x65ca80f2373c4943c9f0f476cf53167261e3208b` | donkey | 1454 | lending-underscanned | 4 |
| 29 | `0x366a6c33ff4157b3759f5ca15af214d407aa4844` | donkey | 1583 | lending-underscanned | 4 |
| 30 | `0x913f50d0195e92bb76c453d61b969dc5d20afa3d` | cozy | 1704 | lending-underscanned | 4 |
| 31 | `0xd8add9b41d4e1cd64edad8722ab0ba8d35536657` | venus | 1972 | lending-underscanned | 4 |
| 32 | `0x8ad4475d330926cc4387d3d1b0c80688e71bf310` | tonpound | 2014 | lending-underscanned | 4 |
| 33 | `0x11581582aa816c8293e67c726af49fc2c8b98c6e` | cozy | 2703 | lending-underscanned | 4 |
| 34 | `0xe6ef65ec40d943c3f675165b0b17e06862fe3d82` | cozy | 4140 | lending-underscanned | 4 |
| 35 | `0x8c29c67fc6c2638db3b4497973595fc8eb0204cf` | youswap | 100 | amm-fork-thin-pool | 4 |
| 36 | `0x9db2836267c60e625bf61ff998a571128e8dc0b3` | ethervista | 101 | amm-fork-thin-pool | 4 |
| 37 | `0xbdb6677b8429d329cda862ebc2031e8083e90fab` | ethervista | 102 | amm-fork-thin-pool | 4 |
| 38 | `0xb8e2a981f878e6be597e4a0c187e2757b1322760` | ShibaSwap | 103 | amm-fork-thin-pool | 4 |
| 39 | `0xc63bebf8a5af8ca3c7913f90ae8dedc8a8505a2e` | ShibaSwap | 105 | amm-fork-thin-pool | 4 |
| 40 | `0xae06088ecb0e668db494ee64ae78af5e5b510797` | ShibaSwap | 106 | amm-fork-thin-pool | 4 |
| 41 | `0xe0f7a2b725ee756d0c3a3eeb6f04cd51d22a3454` | ShibaSwap | 107 | amm-fork-thin-pool | 4 |
| 42 | `0xd6be3b9780572f0215afb3e4d15751955503cebe` | luaswap | 107 | amm-fork-thin-pool | 4 |
| 43 | `0x83540501967b040d942badc61f89f736e509cae8` | supernova | 107 | amm-fork-thin-pool | 4 |
| 44 | `0xfd8618765990a76dad18781b62a642874fac72ee` | ethervista | 111 | amm-fork-thin-pool | 4 |
| 45 | `0x7efd2be9d23cb8a39f9526120441fdef5b31d736` | ethervista | 114 | amm-fork-thin-pool | 4 |
| 46 | `0x51ded664624e7285dcd32d175bb43bf5b43f4454` | ethervista | 114 | amm-fork-thin-pool | 4 |
| 47 | `0xd26d052420e0fcc3e640243d7b9b57e0b28acf5f` | ethervista | 114 | amm-fork-thin-pool | 4 |
| 48 | `0x603fe9a7987319219e44b33134fdf4b1c3b941b7` | minidex | 116 | amm-fork-thin-pool | 4 |
| 49 | `0x66e3992623785d58195b6a9bd45b6657a64a3fab` | ShibaSwap | 117 | amm-fork-thin-pool | 4 |
| 50 | `0x2a56926c32e040bc6db8493e1fd5c96a50e0faa7` | ethervista | 118 | amm-fork-thin-pool | 4 |
| 51 | `0xf830763552e7d6d46a37c2abb103d0f55ed0cfa9` | ethervista | 119 | amm-fork-thin-pool | 4 |
| 52 | `0xad31ff64f5db3def8166daece0b3e41d0dcce76c` | swipeswap | 119 | amm-fork-thin-pool | 4 |
| 53 | `0x4200901bea80abc54023c30b9fb1f7ac2c897f4a` | unicly | 120 | amm-fork-thin-pool | 4 |
| 54 | `0x9b0a330333be460132a9f3c29a69eb21d4a22a5e` | ethervista | 122 | amm-fork-thin-pool | 4 |
| 55 | `0x79bcd8d7003ca27bc4d53d07d3df3847336ee670` | MotoSwap | 123 | amm-fork-thin-pool | 4 |
| 56 | `0xa610313e19f3dcc58254ef24b0d002ee91225387` | ShibaSwap | 123 | amm-fork-thin-pool | 4 |
| 57 | `0xd94e796cf6d4b3a0ad3a3dbdfb9e30036ec1cb4a` | ShibaSwap | 124 | amm-fork-thin-pool | 4 |
| 58 | `0xe4e0e70aafb0fe46634069f5adee92d30cc7cb81` | ethervista | 124 | amm-fork-thin-pool | 4 |
| 59 | `0xeaeb52ec6a629336b8dcfe022e6306831aa0619c` | minidex | 128 | amm-fork-thin-pool | 4 |
| 60 | `0x59f7a66a2fbcaf203cee71359b51142238f85b78` | defi-swap | 129 | amm-fork-thin-pool | 4 |
| 61 | `0xd0a9c569342da0d52ca409c5cf1eac19635de728` | versedex | 130 | amm-fork-thin-pool | 4 |
| 62 | `0x611cbd6744fa310a1a75fad66261b90305e998e1` | ShibaSwap | 132 | amm-fork-thin-pool | 4 |
| 63 | `0x9ea468e0ffc6a6dbfc6c81e81efe15719fd88b67` | ShibaSwap | 132 | amm-fork-thin-pool | 4 |
| 64 | `0x64ad70b217b98fd5fa0430fa134c54f9dfd69b9a` | ethervista | 134 | amm-fork-thin-pool | 4 |
| 65 | `0x25aa1a25fefff1a2640b066cf7751e7d90b8c27c` | ethervista | 135 | amm-fork-thin-pool | 4 |
| 66 | `0xfa08fa948bd2ac1bf11d6687d7e81819d7a484dc` | ethervista | 135 | amm-fork-thin-pool | 4 |
| 67 | `0x4b7990e743a0237fb5c2f0cf4083e7b15c43a09f` | ethervista | 136 | amm-fork-thin-pool | 4 |
| 68 | `0x2fe16dd18bba26e457b7dd2080d5674312b026a2` | integral | 137 | amm-fork-thin-pool | 4 |
| 69 | `0x3087967c5a28f8a83c0b8261808b28512a5da2ce` | defi-swap | 140 | amm-fork-thin-pool | 4 |
| 70 | `0xf1f00b3c234bbf09d6ef35bb274ad6da6e300582` | ShibaSwap | 142 | amm-fork-thin-pool | 4 |
| 71 | `0x811558bf214fea2eebe750b54dd9783db262045a` | ethervista | 144 | amm-fork-thin-pool | 4 |
| 72 | `0x7bd34c4a2d893e8771fa8338f975984b48196b59` | ethervista | 145 | amm-fork-thin-pool | 4 |
| 73 | `0x5819e84f30d41454c0e9d6b5f04a7603c720c9bf` | ethervista | 147 | amm-fork-thin-pool | 4 |
| 74 | `0x27a0c7e1d6051c334d1e80ef6f521aa38eb0a448` | versedex | 148 | amm-fork-thin-pool | 4 |
| 75 | `0x29c100633da99703a75d1a4799efc94112509d6a` | defi-swap | 148 | amm-fork-thin-pool | 4 |

## Queue

| # | address | name | funds_usd | reason_class | signals | unverified | list | peak |
|---|---|---|---|---|---|---|---|---|
| 1 | `0x18e2f4f2e6565187fce73ecc707579e5f7933f74` | zensats | 112 | clone-erc4626-inflation | vault | — | erc4626-registry | 4 |
| 2 | `0xcf8eafc3b1d92801238faadc22d2a7b83fb96c10` | ERC-4626 vault | 240 | clone-erc4626-inflation | vault | — | erc4626-registry | 4 |
| 3 | `0x8417430a31851ae0a36a854394227c5d86be8fc9` | ammalgam-vaults | 503 | clone-erc4626-inflation | vault | — | erc4626-registry | 4 |
| 4 | `0xaf53431488e871d103baa0280b6360998f0f9926` | protectorate | 564 | clone-erc4626-inflation | vault | — | erc4626-registry | 4 |
| 5 | `0x7a12d4b719f5aa479ecd60defed909fb2a37e428` | RockSolid | 3903 | clone-erc4626-inflation | vault | — | erc4626-registry | 4 |
| 6 | `0x830dacd5d0a62afa92c9bc6878461e9cd317b085` | onyx | 101 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 7 | `0x8c83b281fa131360fc90a83397a3afa5c1d8e8a7` | cozy | 115 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 8 | `0xf146c26136c1f80c9f0967d27bcb7e500d45681f` | cozy | 137 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 9 | `0x63d6b99659f7b05b054deef582f5daaa51780e80` | damm-finance | 157 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 10 | `0x9435f39c4a1a51765dd4294fc84fe024f5ace0d2` | cream | 165 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 11 | `0xba2e90b4dcdb235e46b9554360e31f2afa1d8b35` | cream | 176 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 12 | `0xf428189d73a7a17b8eb8f5637654063edd728df8` | minterest | 211 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 13 | `0x6365b24999105afd1bc44ddd43718b2407e43298` | tonpound | 212 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 14 | `0xc5fa52aa356203ae375d0a98d7423c350b5b31c6` | tonpound | 217 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 15 | `0x06078583447f9c0b4b688ace305de8a342c7af2b` | tonpound | 234 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 16 | `0x7d4377114fd3c61c59d72de48102bf6acd3882b1` | cozy | 250 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 17 | `0xbf0852a95ec76e87f7431fa505b27937c9836372` | damm-finance | 267 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 18 | `0x118823514681353634ff95837939e783d85b18af` | damm-finance | 353 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 19 | `0xc42d8f3d791c107c458b2fea025a36669b51fc5f` | cream | 375 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 20 | `0xf635fdf9b36b557bd281aa02fdfaebec04cd084a` | bao-markets | 395 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 21 | `0x41f4766b0368f43d1312f63350635eb155040832` | minterest | 509 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 22 | `0x7ecc1d6fc7f63b003de4391dfd4c78365e844e1d` | cozy | 600 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 23 | `0x19b3bde6f02fc2c985947dcc1dc2a4cddfd43ee8` | cream | 731 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 24 | `0xaef3f76e426d2f0139eaecd19672dd9c9a3fc582` | cozy | 919 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 25 | `0x97f84825d16b32ca97afc1c8bf51ab1086bcff1f` | cozy | 925 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 26 | `0x9affb6d8568cefa2837d251b1553967430d1a5e5` | cozy | 1169 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 27 | `0x43647239ede197099b57bf72d0373f8049acfb0f` | cozy | 1378 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 28 | `0x65ca80f2373c4943c9f0f476cf53167261e3208b` | donkey | 1454 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 29 | `0x366a6c33ff4157b3759f5ca15af214d407aa4844` | donkey | 1583 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 30 | `0x913f50d0195e92bb76c453d61b969dc5d20afa3d` | cozy | 1704 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 31 | `0xd8add9b41d4e1cd64edad8722ab0ba8d35536657` | venus | 1972 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 32 | `0x8ad4475d330926cc4387d3d1b0c80688e71bf310` | tonpound | 2014 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 33 | `0x11581582aa816c8293e67c726af49fc2c8b98c6e` | cozy | 2703 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 34 | `0xe6ef65ec40d943c3f675165b0b17e06862fe3d82` | cozy | 4140 | lending-underscanned | lending | — | compound-fork-getAllMarkets | 4 |
| 35 | `0x8c29c67fc6c2638db3b4497973595fc8eb0204cf` | youswap | 100 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 36 | `0x9db2836267c60e625bf61ff998a571128e8dc0b3` | ethervista | 101 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 37 | `0xbdb6677b8429d329cda862ebc2031e8083e90fab` | ethervista | 102 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 38 | `0xb8e2a981f878e6be597e4a0c187e2757b1322760` | ShibaSwap | 103 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 39 | `0xc63bebf8a5af8ca3c7913f90ae8dedc8a8505a2e` | ShibaSwap | 105 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 40 | `0xae06088ecb0e668db494ee64ae78af5e5b510797` | ShibaSwap | 106 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 41 | `0xe0f7a2b725ee756d0c3a3eeb6f04cd51d22a3454` | ShibaSwap | 107 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 42 | `0xd6be3b9780572f0215afb3e4d15751955503cebe` | luaswap | 107 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 43 | `0x83540501967b040d942badc61f89f736e509cae8` | supernova | 107 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 44 | `0xfd8618765990a76dad18781b62a642874fac72ee` | ethervista | 111 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 45 | `0x7efd2be9d23cb8a39f9526120441fdef5b31d736` | ethervista | 114 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 46 | `0x51ded664624e7285dcd32d175bb43bf5b43f4454` | ethervista | 114 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 47 | `0xd26d052420e0fcc3e640243d7b9b57e0b28acf5f` | ethervista | 114 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 48 | `0x603fe9a7987319219e44b33134fdf4b1c3b941b7` | minidex | 116 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 49 | `0x66e3992623785d58195b6a9bd45b6657a64a3fab` | ShibaSwap | 117 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 50 | `0x2a56926c32e040bc6db8493e1fd5c96a50e0faa7` | ethervista | 118 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 51 | `0xf830763552e7d6d46a37c2abb103d0f55ed0cfa9` | ethervista | 119 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 52 | `0xad31ff64f5db3def8166daece0b3e41d0dcce76c` | swipeswap | 119 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 53 | `0x4200901bea80abc54023c30b9fb1f7ac2c897f4a` | unicly | 120 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 54 | `0x9b0a330333be460132a9f3c29a69eb21d4a22a5e` | ethervista | 122 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 55 | `0x79bcd8d7003ca27bc4d53d07d3df3847336ee670` | MotoSwap | 123 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 56 | `0xa610313e19f3dcc58254ef24b0d002ee91225387` | ShibaSwap | 123 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 57 | `0xd94e796cf6d4b3a0ad3a3dbdfb9e30036ec1cb4a` | ShibaSwap | 124 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 58 | `0xe4e0e70aafb0fe46634069f5adee92d30cc7cb81` | ethervista | 124 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 59 | `0xeaeb52ec6a629336b8dcfe022e6306831aa0619c` | minidex | 128 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 60 | `0x59f7a66a2fbcaf203cee71359b51142238f85b78` | defi-swap | 129 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 61 | `0xd0a9c569342da0d52ca409c5cf1eac19635de728` | versedex | 130 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 62 | `0x611cbd6744fa310a1a75fad66261b90305e998e1` | ShibaSwap | 132 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 63 | `0x9ea468e0ffc6a6dbfc6c81e81efe15719fd88b67` | ShibaSwap | 132 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 64 | `0x64ad70b217b98fd5fa0430fa134c54f9dfd69b9a` | ethervista | 134 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 65 | `0x25aa1a25fefff1a2640b066cf7751e7d90b8c27c` | ethervista | 135 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 66 | `0xfa08fa948bd2ac1bf11d6687d7e81819d7a484dc` | ethervista | 135 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 67 | `0x4b7990e743a0237fb5c2f0cf4083e7b15c43a09f` | ethervista | 136 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 68 | `0x2fe16dd18bba26e457b7dd2080d5674312b026a2` | integral | 137 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 69 | `0x3087967c5a28f8a83c0b8261808b28512a5da2ce` | defi-swap | 140 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 70 | `0xf1f00b3c234bbf09d6ef35bb274ad6da6e300582` | ShibaSwap | 142 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 71 | `0x811558bf214fea2eebe750b54dd9783db262045a` | ethervista | 144 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 72 | `0x7bd34c4a2d893e8771fa8338f975984b48196b59` | ethervista | 145 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 73 | `0x5819e84f30d41454c0e9d6b5f04a7603c720c9bf` | ethervista | 147 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 74 | `0x27a0c7e1d6051c334d1e80ef6f521aa38eb0a448` | versedex | 148 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 75 | `0x29c100633da99703a75d1a4799efc94112509d6a` | defi-swap | 148 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 76 | `0xea86f2362a91ad9f725934fe33aa1ab24775fa0a` | minidex | 150 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 77 | `0x422ad1293bbddc1b1465781e28530ff78119dc38` | ShibaSwap | 158 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 78 | `0xaa350b5e696b21e1a5a35378b5ca6440926f8985` | ShibaSwap | 159 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 79 | `0xd694cad4f40bef311301a1ca8376665bc426c8f1` | supernova | 161 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 80 | `0xc5bd38c4a7339818c6a0ee8f053a52ba56a663d6` | ethervista | 164 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 81 | `0x7a44d56ba0ce8bb5f0359c473b6b637db1ff216b` | swapr | 165 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 82 | `0x6ff14236858f3cea952376b847170adc4a9ae44f` | ethervista | 170 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 83 | `0xb42d590eb1e21b254ac678ebd78cba85ce9ae83b` | ethervista | 171 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 84 | `0x8b1d9ef2bf469701c8953825f214ad5a0814b38f` | unicly | 174 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 85 | `0x7ba8b798ac0f8a2bfe7f912a54e34dca764c316e` | ethervista | 176 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 86 | `0xf1d46b96dc29757780077cad731407e161259367` | ethervista | 177 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 87 | `0x3f051df334f3b8d8aa70cc5374379f36a64f4b70` | unicly | 177 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 88 | `0x8bfc29fc5675be9d6a11dee5b6c0c8f927802281` | ShibaSwap | 177 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 89 | `0x1cf74bebb1974ecd077a308e07b5ef012a49aa98` | unicly | 182 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 90 | `0x3bc6b9602568c1088a29a888f9661f57757e349f` | unicly | 184 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 91 | `0x2625f07613120f12c256dfa195a8f7094568e2c3` | ethervista | 187 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 92 | `0x98f29f527c8e0ecc67a3c2d5567833bee01f2a12` | swapr | 197 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 93 | `0xc90f34061af7a81b25e4a1f83fc99cf5ea2d83a4` | ShibaSwap | 199 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 94 | `0x1a2eaaeb59908d7b5be401fca12ba14330f43887` | youswap | 200 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 95 | `0x48187e512f5338f06222ac574576744129736efd` | solidly-v2 | 202 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 96 | `0x45ecadc95216a3dab2bd37defde2ca805dfac277` | bxh | 204 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 97 | `0x2c3bd1277ea42c4ed594211493898bae52281a2c` | ShibaSwap | 204 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 98 | `0x556ee2fa5314bd309cb06e46a7359a0287a4950c` | ethervista | 210 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 99 | `0x3187feb2bf79fce819c6fc9d62597a638163c30f` | ShibaSwap | 215 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 100 | `0xcdb49866c473bfd0a4dbf64e48d7db2cd31796df` | minidex | 219 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 101 | `0x4ae12cf3aef260bbb763c08669e2afd0e98bdf84` | ethervista | 220 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 102 | `0xdc806458b80c608870b9621604199dc4c0f6a470` | unicly | 220 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 103 | `0xb7a12d87775a9bc496f7baa88966e414bfffabe8` | ethervista | 222 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 104 | `0x3cbc144eb04916fb3ac8b6a3ffb39cdfdea23437` | ShibaSwap | 223 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 105 | `0x21bce45d6bb49520fec91e1e1e6650834748e7ea` | ethervista | 226 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 106 | `0x457aa8fa9ba75337f50fc5ee719fcda152092330` | justmoney | 228 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 107 | `0x42bf7367d96afeeecdb6209c8a6573ce6d55b511` | ShibaSwap | 236 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 108 | `0xc044b084e3fbf5179a14b1af382c85f6f4c2202d` | bullionFX | 236 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 109 | `0x5a85b27b56f428d58f40b389fbbd7b95a33f253d` | saitaswap | 237 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 110 | `0xaf075507f9b503b9c5860f6510b157a3682df9df` | ethervista | 237 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 111 | `0x030725ba5feadd41de3a6f5132b004144a6b8b01` | ethervista | 239 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 112 | `0xb9b4e543020439b88532fff21fa18775256a58ac` | ShibaSwap | 245 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 113 | `0xb10c1840f562f0ac914da2bad3290833c75fdddf` | luaswap | 247 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 114 | `0x4811c9384bc8447945806a2319159054b228fda7` | defi-swap | 253 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 115 | `0xacefce78e31332cf2d1b9e770d609c31d26afc09` | minidex | 258 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 116 | `0x79aec2604855d6eddc26dd558ec9a91a630b2997` | ShibaSwap | 267 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 117 | `0xf5e4b5f58703582ad142b15e6c303dbb3cf7de8a` | solidly-v2 | 273 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 118 | `0x2e4405dc1317e7d1cbfdb0b2073d3662b5da13db` | ShibaSwap | 273 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 119 | `0xdf38cd2363df744c9e6c5def59b6a2ff6a1f4d10` | ethervista | 274 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 120 | `0x97f088b0175a7319059d8e705286aa035077d624` | solidly-v2 | 274 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 121 | `0xe65299b3e494022fea6b34525ac795a28a32ce43` | ShibaSwap | 286 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 122 | `0x5a89feea78872d7a10dda3ddb95ce7a05b99081a` | versedex | 286 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 123 | `0xd0922ddbf6ce8332f680b2d4fdaa0722126ed2f7` | ShibaSwap | 293 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 124 | `0x0124634e7a6325babbbe39fed7d7f9a6bce2c88f` | ShibaSwap | 297 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 125 | `0x2a0dc9ca8062721b87bfc3e39b8f360bfc1181a3` | minidex | 301 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 126 | `0xe0427a927929abd3cfb017b7844550d4bf147e50` | Kwikswap | 303 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 127 | `0xd2fc04d2c34e868bb0bc65be5a5daaf2a7a7b64f` | minidex | 303 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 128 | `0xb76f3bf5f1d669f931064a2a84aa5499232b00e1` | ShibaSwap | 304 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 129 | `0x59c6e1059c904b192b883c5f7e42b347e8833216` | bamboodefi | 306 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 130 | `0xd2ff8e592e09dccb2d27ed91a8e023ee3c4d00fc` | ShibaSwap | 308 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 131 | `0x17f780b6b93f26d2760d17b3fa6207dba49f8c6c` | ShibaSwap | 311 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 132 | `0x07094c3d05525392ba1e2f532a4af6f4d14bdb0c` | ethervista | 316 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 133 | `0x85323e31bca3a8da8c5307671dde878c4bbcdd36` | capitaldex | 316 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 134 | `0xe92cc0e5db597066b3c26016b2fb32830401a31a` | ElkFinance | 317 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 135 | `0x50d3f135681304feef9f80d1d03404e2a0707e82` | minidex | 318 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 136 | `0xfa2048b1008039ca629747353791baef47e25456` | ElkFinance | 323 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 137 | `0x1f61a49589865dbdd8ea798b3ccbaee4c5c5f2f7` | unicly | 335 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 138 | `0x509a06592cd945b1fe9819fe5241173790ce6ecf` | saitaswap | 336 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 139 | `0x6e7ae922140efed0c7dbc9066b50b9f933fd755a` | swipeswap | 337 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 140 | `0x3418d20cd7609680c47634c48dd33181e0ba03db` | ShibaSwap | 342 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 141 | `0x9cd2a3d4adeec326704097ac5b2687b2cb46a2ad` | ShibaSwap | 343 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 142 | `0x27c5966d8ce3b3cdda5aba645d0bbd9410cf57c6` | minidex | 346 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 143 | `0x6cd34dcc0fca7fa7d2ada313e9bb965f74f81da2` | unicly | 348 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 144 | `0xfeea92041bcc1c00f5934663955a6825e1a297b0` | ShibaSwap | 348 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 145 | `0x63d3afecaf08a5b50a91565a60f5a7c52f498971` | ethervista | 352 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 146 | `0x6f5716df72ce3902d7e0a48cab46261d2e2bad93` | cypher-v2 | 364 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 147 | `0xd4d2140ed70dcf8794a986f0cfd07560ee738c71` | integral | 368 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 148 | `0xfc789fc17368c2b66709efe09c0aa76dc2c131d3` | standard-tech | 369 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 149 | `0x8fd90ebcd1b0e783fd313a2ffdc4149f269f7236` | ShibaSwap | 387 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 150 | `0x54bfd4fa6dde7ce96140728b126af72702e4b354` | justmoney | 388 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 151 | `0x5e3065381788c7a1ee323c2d3e1b73c872976e72` | ShibaSwap | 389 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 152 | `0x8e5fb73900b9093c9f51d2032e6aba4ae378476e` | unicly | 390 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 153 | `0x4956bfbeb99b825ae3720e135bee6ee9a1b3902e` | ShibaSwap | 392 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 154 | `0x1a98aae831759efa5a36f78336defa156957bc07` | ShibaSwap | 395 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 155 | `0x53b7420c59a4721ce621283f137e2eadff26fa3d` | swipeswap | 398 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 156 | `0x6a0a4110504e992a45a88b4666125eb0dd183e72` | supernova | 401 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 157 | `0xd14399e7f42822dea1aa9318de453b3356122532` | ShibaSwap | 402 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 158 | `0x9f12f4b11056f4adddf08e8f56aa227010e464ac` | ShibaSwap | 407 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 159 | `0x7eaaf27ca935a2e448bbb400e3b37287eb6294eb` | ethervista | 410 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 160 | `0xdf8ef8a76c33b4f259bb72241a8697e307548c8b` | groveswap | 412 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 161 | `0xb49b4bc127889d64d73969f5a482d6306d3bc186` | ShibaSwap | 416 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 162 | `0x1914122308ccb9ff67f3b587ca59d230c6abdc25` | defi-swap | 419 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 163 | `0x50b2c07f0269ebf0e906feeea9d5c90c42d9fd24` | ShibaSwap | 432 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 164 | `0x656c36882a3d5fb1ba47fbeb3346033437a8c690` | ShibaSwap | 439 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 165 | `0x923347d1ec146e524ed8208f1be4820cfa95d6b0` | ShibaSwap | 444 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 166 | `0x4c568562039b3e70725eafcebbf91e7d3c9cdb76` | ethervista | 445 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 167 | `0xcd452c162da7761f08f656b8e5ede3a385981378` | solidly-v2 | 449 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 168 | `0x5e8981ac03c349ecff06ad1b0fe70c2f573ac790` | ShibaSwap | 450 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 169 | `0x975a4ff7e35565f33fb9666ee7f08041d0569aee` | swipeswap | 465 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 170 | `0xee9d02cb7b1e983fe56d94bfe115879c0c50f40c` | MotoSwap | 469 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 171 | `0xbb6d133d7f36705ea058cfd706082aa382f23de9` | ShibaSwap | 474 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 172 | `0xc0bf67bb0d2cfbca8615e45eaa947e796aca931b` | ShibaSwap | 491 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 173 | `0x447a8103596af3ad1ed8dcdff53b1dd599264cd6` | ElkFinance | 491 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 174 | `0x35e9c7f45b9cbafa6c294bfcc591aab39cbfa44c` | MotoSwap | 495 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 175 | `0xd4a07ab7d094aa7ae102f1b285b852b8d0f424b8` | bxh | 497 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 176 | `0x43f0e5f2304f261dfa5359a0b74ff030e498d904` | integral | 506 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 177 | `0x1c66d959688ced0d47cfb943db0c12f4a7e9f594` | unicly | 510 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 178 | `0x1bcd6b0e97b51d76fd1752111a1fe2b473f655ee` | swipeswap | 518 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 179 | `0xbd504d0a4b16a77e531722c3aea770161347dea7` | akronswap | 525 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 180 | `0x97d9877ff71e514864f7bfc37abda73d13245f55` | defi-swap | 530 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 181 | `0x844146b6a5318cacbc059505a42ff5f21afe9fa1` | saitaswap | 541 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 182 | `0x8d5a1dcdc0fb93de2103977b1ffeacb16066025b` | ShibaSwap | 550 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 183 | `0xa36af59353067a60f76f301611dd21b9f135c551` | MotoSwap | 561 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 184 | `0x08d0b9aa7121f5b70f1109ebd4b04b18a6322fc7` | ShibaSwap | 574 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 185 | `0x1c8edca101c30d85e1ce32f354e27f5cabafe466` | bamboodefi | 575 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 186 | `0xf3033c8d381f16d9d466b0517e6ccced0f493fb6` | ShibaSwap | 578 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 187 | `0x9de898825f7f851694e4c93d7f233b35787c99a7` | empiredex | 586 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 188 | `0xa47b332014b332194616057f0fd82cf1152c74e1` | MotoSwap | 602 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 189 | `0x8380f233ff5553f536d9e204de735ba8ca10e556` | empiredex | 616 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 190 | `0x18f5e1a28cdc4bad5d19380dc717641eab1f53f1` | defi-swap | 623 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 191 | `0x7885e359a085372ebcf1ed6829402f149d02c600` | luaswap | 628 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 192 | `0xe3b07bc14a3c96e55f474492f1c1c3324cb9ccfe` | supernova | 634 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 193 | `0x338eabfa7775793b0a9d01e96b21bb334a39e451` | ShibaSwap | 639 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 194 | `0x4b5cd5807c6819cf9e83f79d979781460a13f16e` | ShibaSwap | 645 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 195 | `0x41e1633719d5c1df86888f1e1a8d8d32202b6d27` | swipeswap | 666 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 196 | `0x36df698fb1e4c072a9c85e9848edd9c4c96dd194` | ethervista | 682 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 197 | `0x9467a2d9c07cebce3708ca32eeb2b9219aeb31b8` | saitaswap | 711 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 198 | `0x43d4f85a793f7354966b5a6199b3909fabe50fac` | defi-swap | 717 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 199 | `0xdb6655a7050ae52caaae5cf3d36098129a5e16f1` | supernova | 719 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 200 | `0x2574c142f25a0111e73dbf46c838646759ba1a6e` | cypher-v2 | 720 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 201 | `0x1aed31e03c0a3ff7a6c841f0de45838e09176fd4` | ShibaSwap | 750 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 202 | `0xa2f91b69db309d23e09783cad5fb1402dff5b37e` | ShibaSwap | 781 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 203 | `0xd75e77026b998a62c80b93fcf71aef1255d2b0ec` | ShibaSwap | 784 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 204 | `0xb2924b0a238976d231c361a64a885e61b1006d15` | MotoSwap | 786 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 205 | `0x1b1753b114874481f8bcedb65f2c9f76470fc875` | pepedex | 788 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 206 | `0x6d2a35e903f95a8aca302de7688d12e26f1a08d8` | ShibaSwap | 796 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 207 | `0x65fabaf7e6c5380243e063d8559d84e589db6438` | luaswap | 801 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 208 | `0x02328931f7fb70098021a4446cea73936f41cef8` | ShibaSwap | 802 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 209 | `0x5572e5e8119b6b747f286f3b63082a64f8b24856` | ShibaSwap | 822 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 210 | `0x75b181849a7ecf684f62fcc929236765f5efb0ec` | ethervista | 836 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 211 | `0x7ac1a76f4570661543149a04c4be34d8e8deb11c` | tamaswap | 880 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 212 | `0x8784a0f6d01a9fe3b1b6e803ceaa7549c655b580` | standard-tech | 882 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 213 | `0x8875535944d6728e0439657671b1d5c060fc75fa` | unicly | 939 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 214 | `0xb591d863c458a6fb1a498a51964b1195f5f5c4c9` | sumswap | 952 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 215 | `0xe5c4bd4c562ac9df1b33ffbccd2341981a462825` | ShibaSwap | 980 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 216 | `0x682831244b0e97946abc52cb1893cce398de3a35` | versedex | 983 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 217 | `0xae933d0a8d630e30a2e035284e35f232f4590e33` | Kwikswap | 988 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 218 | `0xa27e5775317f3f301b5b08babcde0a20feae7f09` | ElkFinance | 994 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 219 | `0x9909d09656fce21d1904f662b99382b887a9c5da` | defi-swap | 1020 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 220 | `0x2a529766847129f8cc13cebc6b7dfe89ee49d55c` | ShibaSwap | 1034 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 221 | `0x71cb6c7d2179ae0fb6d32f3484fa9e225e47d15e` | ShibaSwap | 1082 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 222 | `0x0f671104e68b9f56c29a2ba4a22288c6499d71ab` | solidly-v2 | 1136 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 223 | `0x559fe81784cc80acdd3e1ae5b2a8d5b7a8120f76` | ShibaSwap | 1137 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 224 | `0x6c327fa5c54043f419b798148429b4fdbd207d10` | ShibaSwap | 1149 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 225 | `0x7a019e9f33af312b5e5c6b065fbc733ccaa09f39` | ShibaSwap | 1164 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 226 | `0x79c860158366dd5c977fb4a5eaea16aa93a13479` | Kwikswap | 1171 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 227 | `0xb41136cfd8860b5680c7f58f667572584ffa566c` | ShibaSwap | 1173 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 228 | `0xbc96b7890bb0131703cf0382732f02ff3dfd206c` | ShibaSwap | 1190 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 229 | `0x9d7d2e2c67ef21a0d3ee5b309d417d0ff601392f` | minidex | 1210 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 230 | `0x829080c535559f165e4f32a5edb9be28aea6eb3c` | ShibaSwap | 1214 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 231 | `0x12a132927a47e8ea1535f491061bc6cbe460c46b` | youswap | 1216 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 232 | `0xd9b908363f10530d16bb6162e04d8de66920dda5` | ShibaSwap | 1231 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 233 | `0x87f006e8356ea8214896a41b829b72169f1723d9` | justmoney | 1262 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 234 | `0xe46e4af11fd00d881fcccfbfe2d6b78612c48337` | ShibaSwap | 1339 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 235 | `0x54c4c936911dcd4755f6007987c50b4cdb448174` | pepedex | 1352 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 236 | `0x64a35e5b8bc5d3f2dd43d1d2c5c26d2e57d86bbe` | youswap | 1450 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 237 | `0x642431623ae5d73c19fc931aaea0d4677303880c` | solidly-v2 | 1451 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 238 | `0xd5a547f21c2d76667c239e14f1fe65a5d9fd5d50` | convergence | 1549 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 239 | `0xa856139af24e63cc24d888728cd5eef574601374` | defi-swap | 1597 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 240 | `0x843fdc30d42c7561503aaa040556051b892a32e7` | unicly | 1627 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 241 | `0x2f62a3f785d23be0d03bcf34821fc0619ae53910` | ShibaSwap | 1640 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 242 | `0x106293047d8263f86e4e3550bb44d4e5455e7e89` | justmoney | 1676 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 243 | `0x9e2ad5024b4955f38287c076ae113857ece02d27` | ShibaSwap | 1703 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 244 | `0x48736fd9f1e70696259c8d3f83f25d3c795e0897` | unicly | 1751 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 245 | `0xec3bb25709b042bdcddaee8a50cd13ee41feed85` | unicly | 1820 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 246 | `0x294fff8fbfe37da6ffd410b4ca370b92ae853a9b` | versedex | 1916 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 247 | `0xf5438e9711e6332f4b1926d6750a65704a65c75b` | ShibaSwap | 2037 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 248 | `0x0d70947cd19df8c67e6bbec9c7e21ec54df61c0f` | ethervista | 2050 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 249 | `0x6491f4cf9c084ef8fc055eaaf735bdceccf69370` | defi-swap | 2173 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 250 | `0xcfd23ba4f3ac68b484e26cb7aa275e48dab7a93c` | ShibaSwap | 2179 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 251 | `0x5716d2cbf2f44b5b9e3ed7b7a6eb58ce5996f318` | saitaswap | 2207 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 252 | `0x6cbefa95e42960e579c2a3058c05c6a08e2498e9` | ShibaSwap | 2211 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 253 | `0xd426817f86f318f625deb1adf6c553f5f7cf6d8d` | ethervista | 2246 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 254 | `0xf3f82bc165a83425e81b8f2858d786e41ab21671` | versedex | 2275 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 255 | `0xe2ca82f662fd7eadec92541af83456bae88dc166` | minidex | 2345 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 256 | `0x9b7e74b56400eeb15f9760c847ccc678f7223f70` | unicly | 2366 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 257 | `0x970cf9b7346fbaea0588f03356a104100eb675e2` | ethervista | 2369 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 258 | `0x163b890f4892d593945579028ec44ef0f20a4633` | empiredex | 2410 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 259 | `0xfc7b7cda3b9491b9e08aa54dde1e1207eedb6c0e` | unicly | 2434 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 260 | `0xd1516ab7f9b5ebeb2c0678b1c550a7273a801201` | Kwikswap | 2511 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 261 | `0x4087d0e6e513f260de87408bee9334a5742cfdf4` | defi-swap | 2531 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 262 | `0x11457ef2b71087d18651106f23ed59dd8ec0da6c` | MotoSwap | 2538 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 263 | `0x570eb9e14e7c3c46827e9c1381baa95dfb821dc9` | MotoSwap | 2573 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 264 | `0x8507673bee915646a7e837b9e90d6494c303e6fa` | unicly | 2636 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 265 | `0x8b59be2fc6fccc2256cc4841843a13ce29da16bd` | defi-swap | 2677 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 266 | `0x4a2b4f76ab77c7ee3820f16967741209d0a8779e` | convergence | 2692 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 267 | `0xc95389f2883cf6c9099a25f1cf356d881e5a07c6` | ShibaSwap | 2706 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 268 | `0xe64cce041a6705c23f7df94af9cd824efb740a79` | justmoney | 2771 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 269 | `0x7d2a83dbfb562226666e75b08d55c6b226df9eda` | minidex | 2881 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 270 | `0xbf41a6ac5e15ada4acb739399a423871a78ace62` | ShibaSwap | 2893 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 271 | `0x29baa9ebcce8552b030bc1138d5d64893018b329` | ShibaSwap | 2980 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 272 | `0x5a1fd72b299f523ff0c0b3f5ed27e3bb889266cf` | ShibaSwap | 3024 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 273 | `0xd9439f8ef8ec20f3aec8f6203e91d572673bcfd8` | justmoney | 3047 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 274 | `0x492e507a9b3645c458e16408ec8c2468a3ef82f3` | bamboodefi | 3057 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 275 | `0x6593f97975400fcfee16a44d8448bb0509743e8e` | ShibaSwap | 3110 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 276 | `0xd360131b77ead72f1f23fb185b4896fe01dc8cb5` | defi-swap | 3136 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 277 | `0x0c795fcc8f38248ecdf1ec49ce2e97f68ca14e82` | ShibaSwap | 3136 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 278 | `0xbfa245e01d9e14f8b38f2ca19b2ac857e27e5640` | minidex | 3141 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 279 | `0x7407aef20b224a02c0f074a50b086b8de9d02509` | bamboodefi | 3165 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 280 | `0x6f4a05f54172e53d9f937a46f3ab9aca4f1dbd6e` | ShibaSwap | 3194 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 281 | `0xd0dcb7a4f8cfcdb29364d621ca5d997b7eddbc46` | ShibaSwap | 3350 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 282 | `0xdc033a6edf526ebd55ee64147a00d52f6059ed58` | unicly | 3439 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 283 | `0x67654fe31de4c8cbbced58fd8d27ab01126ec9cf` | ShibaSwap | 3603 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 284 | `0xa092794b8774e531f96664646775ec8183a4a7ec` | Kwikswap | 3676 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 285 | `0x96258bb42779bf300cf69c9b5bd2ba5245cb4bc4` | luaswap | 3752 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 286 | `0x2bd89edcc9130b113da1cfff86ee103e1545cc1b` | Kwikswap | 3767 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 287 | `0xe351c5517da206948e678018b98f248fa6759e5a` | ShibaSwap | 3848 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 288 | `0xd0a9bb124c4611ec375d93b5e9f20156c73b2004` | ethervista | 3949 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 289 | `0x3f2da328f692dae75bef1b9f93431c641bc14e15` | Kwikswap | 4018 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 290 | `0xc149ebc76142b337b2cd5ffa3b27af9812cd9952` | sumswap | 4096 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 291 | `0x4610ba8d5d10fba8c048a2051a0883ce04eabace` | ShibaSwap | 4128 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 292 | `0x4b09b1a92e8bc8e04c48fce66485cbd148405fbb` | ShibaSwap | 4151 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 293 | `0xc1576448b8e9ad83abadf38dffd4000bf51ac2f0` | Kwikswap | 4179 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 294 | `0xa04505aaa5d5e0e4d4a8e0b121d875e83a701d66` | ShibaSwap | 4279 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 295 | `0x0d0142f28c7c57b041bbf834fd260600a8ce07bc` | swipeswap | 4418 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 296 | `0x625217acc1dc368296febf69be184ebf3d9fb172` | ShibaSwap | 4510 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 297 | `0x302c53b6176f750e5547d775645dc8778524fcc1` | MotoSwap | 4520 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 298 | `0x63a65a174cc725824188940255ad41c371f28f28` | solidly-v2 | 4577 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 299 | `0x2c8bb9c001af6aefff130cb7fcb41bdefc8c385c` | ShibaSwap | 4637 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
| 300 | `0x3e30fbdf2b486a0d6ac62df0ac96afb7867d2984` | supernova | 4949 | amm-fork-thin-pool | amm | — | univ2-fork-allPairs | 4 |
