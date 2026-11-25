# Small-value high-probability scan queue (100 contracts)

Generated 2026-11-25T17:07:08Z · chain: ethereum · 100 contracts

## Cutoff rules

- **Small value:** on-chain funds held **<= $500,000** (hard cap). Strong preference for **<= $1,900** (list-2 junk-drawer band) and **<= $50,000**. The cap drops the mega Morpho / LYTPool / StakedAvant pools ($1M-$27M).
- **High probability of issues (not bare EOAs):** prior Maybe/heat board signals; unverified/decompilable bytecode holding funds; and clone-class structural signals — upgradeable proxy (unprotected initialize / public changeAdmin+upgradeTo), spot AMM oracle (no TWAP), ERC-4626 share-inflation, AMM-fork thin pool, and lending.
- **Excluded:** funds > $500k; prior verdict `yes`/`drain-found`; canonical blue-chip protocols (list-2 exclude rules). Role-gated Morpho-family vaults capped at 8 so they don't dominate.
- **Preference order:** score desc, then unscanned before scanned, then smaller funds. Fork-cleared `no` rows capped at 12.

## Selection sources / breakdown

| reason_class | n | meaning |
|---|---|---|
| unverified-leftover | 49 | Unverified/decompilable bytecode holding leftover funds, not yet scanned. |
| prior-maybe-small | 23 | Already on the board as Maybe or heat>=6, funds<=$500k — re-verify with fork on. |
| lending-underscanned | 20 | Lending contract holding funds, unscanned/under-scanned. |
| clone-erc4626-inflation | 4 | ERC-4626 vault signal — first-depositor share-inflation family. |
| clone-proxy-takeover | 4 | Upgradeable proxy signal — unprotected initialize / public changeAdmin+upgradeTo clone family. |

- Scan status: scanned-maybe=23, unscanned=73, scanned-no=4
- Candidate pool: list-1=25, board=17, list-2=58
- Funds: <=\$1,900: 59, <=\$50k: 16, <=\$500k: 25 (median \$664)

## How to run it

The 100 addresses are appended to `eth-scanner/src/eth_scanner/desk/signal_rerun_seed.json`. The signal-rerun job unions the seed with every stored signal, prioritizes by peak heat within a 4,000,000 CU budget, and scans each with fork verify on (read-only).
- **Trigger:** push `eth-scanner/signal-rerun.trigger` to `main` (done in this PR) → runs `.github/workflows/eth-scanner-signal-rerun.yml`.
- **Or manually:** Actions tab → *eth-scanner-signal-rerun* → *Run workflow* (`workflow_dispatch`).
- **Or local/CLI:** `cd eth-scanner && python -m eth_scanner signal-rerun --budget-cu 4000000 --deadline-minutes 55 --json`

## Queue

| # | address | name | funds_usd | reason_class | signals | unverified | prior | peak |
|---|---|---|---|---|---|---|---|---|
| 1 | `0xda4d2152b2230e33c80b0a88b7c28b1c464ee3c2` | xToken xU3LPStableProxy | 185,747 | prior-maybe-small | upgradeable,vault | — | maybe/h0 | 6 |
| 2 | `0x7cd5e2d0056a7a7f09cbb86e540ef4f6dccc97dd` | xToken xSNXAdminProxy | 229,077 | prior-maybe-small | upgradeable,vault | — | maybe/h9 | 9 |
| 3 | `0x1b2cb79a4564206f53ba80b4d780f251b4ae6765` | ERC-4626 vault | 3,401 | prior-maybe-small | vault | — | maybe/h3 | 6 |
| 4 | `0x56b49615b468c14237236caffee4d5b7c65a82f8` | CoinbaseSmartWallet | 119 | prior-maybe-small | — | — | maybe/h3 | 6 |
| 5 | `0x6110d61dd1133b0f845f1025d6678cd22a11a2fe` | Spice Finance | 3,526 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 6 | `0x7ee64f74792c307446cd92d23e551efae3172a28` | Wasabix | 4,536 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 7 | `0x8f0cb368c63fbedf7a90e43fe50f7eb8b9411746` | Bank of Chain | 7,013 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 8 | `0xf80e51afb613d764fa61751affd3313c190a86bb` | Altitude | 21,613 | prior-maybe-small | — | — | maybe/h3 | 6 |
| 9 | `0x686e8500b6be8812eb198aabbbfa14c95c03fc88` | GovernanceLockedRevenueDistributionToken | 135,186 | prior-maybe-small | — | — | maybe/h3 | 6 |
| 10 | `0x2e87d6bfa3f2a932e0c70a32607c0b839404984d` | MetaMorphoV1_1 | 139,666 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 11 | `0x3ace737610da61d004c748275eafd2ecc99802be` | VaultV2 | 143,859 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 12 | `0xedc72b49542e4362c677b8369bc23882ed635a75` | MetaMorphoV1_1 | 149,872 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 13 | `0x1f7bae0549f9f0baf15d0d637900056bb9434c36` | VaultV3 | 170,034 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 14 | `0x579a3bde631c3d8068cbfe3dc45b0f14ec18dd43` | BridgeImplementation | 173,488 | prior-maybe-small | — | — | maybe/h4 | 6 |
| 15 | `0xdcb9a6d103dae1ab571f746bb83ded53e665880a` | VaultV2 | 183,236 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 16 | `0x241e82c79452f51fbfc89fac6d912e021db1a3b7` | Hydro | 227,146 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 17 | `0x7ceb0f01cb7187a2ebed5661ecc4d5701d8f2350` | VaultV2 | 230,336 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 18 | `0xdb1281191bd51d4e4412b0e3323001759d18939f` | Vault | 314,366 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 19 | `0xdc55fe3d11d8eca631d9db6fcc999cd26fe733be` | EmeraldVault | 314,950 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 20 | `0x5e5b30c5fd07da26d1e515dfedb1d37c93417652` | VaultV2 | 330,746 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 21 | `0xc88f47067db2e25851317a2fdae73a22c0777c37` | oneBTC | 341,202 | prior-maybe-small | — | — | maybe/h3 | 6 |
| 22 | `0x7b9e07f03116e5f334b2c9f539515ca5e31fd063` | EmeraldVault | 351,870 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 23 | `0xd78f89b311c27c4c71487aeb73742665cd13b941` | VaultV2 | 462,608 | prior-maybe-small | — | — | maybe/h6 | 6 |
| 24 | `0x84e0a246dd437d911989e89667816a9ed97a1284` | MagicFox Vaults | 170 | clone-erc4626-inflation | vault | Y | unscanned | 4 |
| 25 | `0xed6e000def95780fb89734c07ee2ce9f6dcaf110` | Definitive Yield Vaults | 1,067 | clone-erc4626-inflation | vault | Y | unscanned | 4 |
| 26 | `0x7bbcf1b600565ae023a1806ef637af4739de3255` | PrimeFi | 124 | lending-underscanned | lending | Y | unscanned | 4 |
| 27 | `0x96650bebc549456f253974c11fc6cbe28172a2d2` | Peridot | 312 | lending-underscanned | lending | Y | unscanned | 4 |
| 28 | `0xdf53cc6771cec9b4ef97ac726725a16b0fb41aa3` | Lila Finance | 315 | lending-underscanned | lending | Y | unscanned | 4 |
| 29 | `0x10031e7cff689de64f1a5a8ecf4fbbc7aa068927` | Whitehole Finance | 947 | lending-underscanned | lending | Y | unscanned | 4 |
| 30 | `0xafccb724e3aec1657fc9514e3e53a0e71e80622d` | Vaultka | 5,962 | clone-erc4626-inflation | vault | Y | unscanned | 4 |
| 31 | `0x6dd963c510c2d2f09d5eddb48ede45fed063eb36` | Factor Leverage Vault | 29,035 | clone-erc4626-inflation | vault | Y | unscanned | 4 |
| 32 | `0xad3e02e83b886543d1171ff446c130d52068c106` | Sculptor Finance | 3,853 | lending-underscanned | lending | Y | unscanned | 4 |
| 33 | `0xe6af844d5740b6b297b6dd7fb2ce299ee9e3d16f` | SolidLizard Lending | 5,964 | lending-underscanned | lending | Y | unscanned | 4 |
| 34 | `0x3c70260eee0a2bfc4b375feb810325801f289fbd` | OCP Finance | 7,616 | lending-underscanned | lending | Y | unscanned | 4 |
| 35 | `0x17b7163cf1dbd286e262ddc68b553d899b93f526` | Qubit | 10,123 | lending-underscanned | lending | Y | unscanned | 4 |
| 36 | `0x2eadce7ebdedf3c7291f1f658208a2720ff4b74d` | Aquarius Loan | 17,140 | lending-underscanned | lending | Y | unscanned | 4 |
| 37 | `0x4d48d503ed04d50418c9abf163b1168ff834e47c` | Gloop | 26,228 | lending-underscanned | lending | Y | unscanned | 4 |
| 38 | `0x1c7a460413dd4e964f96d8dfc56e7223ce88cd85` | Seamless V2 | 39,355 | lending-underscanned | lending | Y | unscanned | 4 |
| 39 | `0xb3cb6d2f8f2fde203a022201c81a96c167607f15` | Green Planet | 47,614 | lending-underscanned | lending | Y | unscanned | 4 |
| 40 | `0x657d9aba1dbb59e53f9f3ecaa878447dcfc96dcb` | YieldNest ynETH MAX | 21,391 | clone-proxy-takeover | oracle,upgradeable,vault | — | no/h0 | 5 |
| 41 | `0x0391be54e72f7e001f6bbc331777710b4f2999ef` | Trava Finance | 52,033 | lending-underscanned | lending | Y | unscanned | 4 |
| 42 | `0x5de40c1152c990492eaeaeecc4ecaab788bbc4fd` | Segment Finance | 65,590 | lending-underscanned | lending | Y | unscanned | 4 |
| 43 | `0xe7df6907120684add86f686e103282ee5cd17b02` | USDFI Lending | 68,514 | lending-underscanned | lending | Y | unscanned | 4 |
| 44 | `0x2a0a59d6b975828e781ecac125dba40d7ee5ddc0` | Ripe Protocol | 70,434 | lending-underscanned | lending | Y | unscanned | 4 |
| 45 | `0xf0ce1d83b5fc9c67f157d8b97fd09e2cf8af899e` | ZebraDAO | 116,782 | lending-underscanned | lending | Y | unscanned | 4 |
| 46 | `0xc47d9753f3b32aa9548a7c3f30b6aec3b2d2798c` | Tender Finance | 144,172 | lending-underscanned | lending | Y | unscanned | 4 |
| 47 | `0x3082cc23568ea640225c2467653db90e9250aaa0` | Radiant V2 | 153,146 | lending-underscanned | lending | Y | unscanned | 4 |
| 48 | `0xe7e7e741c23a4767831a56a8c99f522c5ac1e7e7` | Everything | 289,228 | lending-underscanned | lending | Y | unscanned | 4 |
| 49 | `0x3c769d0e8d21d380228dfb7918c6933bb6ecb6d4` | Ledgity Yield | 359 | clone-proxy-takeover | upgradeable,vault | Y | no/h0 | 5 |
| 50 | `0x73fddfb941c11d16c827169bb94acc227841c396` | ACoconut | 495 | clone-proxy-takeover | upgradeable,vault | Y | no/h0 | 5 |
| 51 | `0x15f3ee2f609fbae0bc48e3a071d66dd917c682eb` | SuperReturn | 920 | clone-proxy-takeover | upgradeable,vault | Y | no/h0 | 5 |
| 52 | `0x93d504070ab0eede5449c89c5ea0f5e34d8103f8` | Archi Finance | 102 | unverified-leftover | — | Y | unscanned | 3 |
| 53 | `0xfcc9b8a55f63b1fec16622f02c64d85cc53d38a6` | BorB | 103 | unverified-leftover | — | Y | unscanned | 3 |
| 54 | `0xf45116c2e5be608152ea8a6a73917dfe75b707dc` | BaseYield | 109 | unverified-leftover | — | Y | unscanned | 3 |
| 55 | `0x9525b6375c19cd507ffe726fa09df237eaf8053b` | Poor Exchange | 122 | unverified-leftover | — | Y | unscanned | 3 |
| 56 | `0x00438ae909739f750c5df58b222fe0bde900c210` | Hotpot Finance | 137 | unverified-leftover | — | Y | unscanned | 3 |
| 57 | `0x3295fde99976e6b6b477e6834b2651a22deb1dd7` | SunFlower Finance | 138 | unverified-leftover | — | Y | unscanned | 3 |
| 58 | `0x6448be0ca45a7581d9c4c9dd665e14ec60b25113` | Biokript | 143 | unverified-leftover | — | Y | unscanned | 3 |
| 59 | `0x708baac4b235d3f62bd18e58c0594b8b20b2ed5b` | Satoshi Finance | 159 | unverified-leftover | — | Y | unscanned | 3 |
| 60 | `0xd954ecd262b3df276c39f89506ab39cef0272335` | Etherberry Finance | 161 | unverified-leftover | — | Y | unscanned | 3 |
| 61 | `0x50aa7a13b28eea97dc6c3f5e8aaa7fe512e7306d` | X Blue Finance | 163 | unverified-leftover | — | Y | unscanned | 3 |
| 62 | `0xfea6ab80cd850c3e63374bc737479aeec0e8b9a1` | Solana Farm | 169 | unverified-leftover | — | Y | unscanned | 3 |
| 63 | `0xbcb24afb019be7e93ea9c43b7e22bb55d5b7f45d` | BSCStation | 169 | unverified-leftover | — | Y | unscanned | 3 |
| 64 | `0x265a65ad2d2f9c6c7482a76f53b79ef12954c46f` | XBased | 175 | unverified-leftover | — | Y | unscanned | 3 |
| 65 | `0x4788de271f50ea6f5d5d2a5072b8d3c61d650326` | Basin DAO | 188 | unverified-leftover | — | Y | unscanned | 3 |
| 66 | `0x2303d1b31cf34fd06bbbeb3c1faa003d90fd7218` | IceSwap | 197 | unverified-leftover | — | Y | unscanned | 3 |
| 67 | `0xd63ebbe933f422bf8bc6f909fa27e467b537ca81` | Spooky Base | 208 | unverified-leftover | — | Y | unscanned | 3 |
| 68 | `0x322f15d4bedaa20c178fb75b2628663d2da19736` | Monopoly Finance | 213 | unverified-leftover | — | Y | unscanned | 3 |
| 69 | `0x590830dfdf9a3f68afcdde2694773debdf267774` | Giza | 224 | unverified-leftover | — | Y | unscanned | 3 |
| 70 | `0xa28bac0427e4a722246ce4e9ad89ec95ff8b87a3` | Statix Farm | 228 | unverified-leftover | — | Y | unscanned | 3 |
| 71 | `0xb64e280e9d1b5dbec4accedb2257a87b400db149` | Level Perps | 242 | unverified-leftover | — | Y | unscanned | 3 |
| 72 | `0xbbdaa8700a7caaaf3b4aac1fa6fb5ff76fc14c56` | NewSpace Finance | 256 | unverified-leftover | — | Y | unscanned | 3 |
| 73 | `0x31c91d8fb96bff40955dd2dbc909b36e8b104dde` | POISON FINANCE | 256 | unverified-leftover | — | Y | unscanned | 3 |
| 74 | `0xc2181d975c05c8c724b334bced0764c0b86b1d53` | Global Balanced Liquidity Index | 265 | unverified-leftover | — | Y | unscanned | 3 |
| 75 | `0xcd7cbc46d083a245b45e22cb4be2c569947ce896` | SamoDAO | 282 | unverified-leftover | — | Y | unscanned | 3 |
| 76 | `0xef0b2ccb53a683fa48799245f376d6a60929f003` | MoonBase | 297 | unverified-leftover | — | Y | unscanned | 3 |
| 77 | `0xb2dcbd5258a22385240e4ac13fc6726b66f0de96` | ZenithSwap | 308 | unverified-leftover | — | Y | unscanned | 3 |
| 78 | `0x576bb65b52425d59ac4c702376f88c527f5c7773` | TroyDefi | 378 | unverified-leftover | — | Y | unscanned | 3 |
| 79 | `0xafe5451185513925f5e757f001425338ff93412d` | Particles Money | 379 | unverified-leftover | — | Y | unscanned | 3 |
| 80 | `0x31535f7a83083e3f34899f356ecc7246fbf2e82d` | JaguarSwap | 393 | unverified-leftover | — | Y | unscanned | 3 |
| 81 | `0x5badd826aefa700446fa6d784e6ff97ed6eedca9` | AfraSwap | 397 | unverified-leftover | — | Y | unscanned | 3 |
| 82 | `0x12c415aafb1a521b42251e972bb7ce6795f7669b` | Xray Swap | 428 | unverified-leftover | — | Y | unscanned | 3 |
| 83 | `0xa5593837af2b99021fe657c80d70d2365f5cfd38` | Asgard Dao | 469 | unverified-leftover | — | Y | unscanned | 3 |
| 84 | `0x6012c3a742f92103d238f1c8306cf8fbcdeca8b3` | LuckyChip | 490 | unverified-leftover | — | Y | unscanned | 3 |
| 85 | `0x58cb98a966f62aa6f2190eb3aa03132a0c3de3d5` | OpenWorld Farm | 514 | unverified-leftover | — | Y | unscanned | 3 |
| 86 | `0x873177db4eac3581464ffa64deb39b25ce409bfd` | Narwhal Finance | 515 | unverified-leftover | — | Y | unscanned | 3 |
| 87 | `0xa26303226baa2299ada8d573a6fcd792ab1cfb07` | Glorb | 530 | unverified-leftover | — | Y | unscanned | 3 |
| 88 | `0x66b70221b22925c4663c46cd15f2f2eaac822ceb` | boobs.finance | 550 | unverified-leftover | — | Y | unscanned | 3 |
| 89 | `0x37d39950f9c753d62529dbf68fcb4dca4004fbfd` | SpaceDex | 554 | unverified-leftover | — | Y | unscanned | 3 |
| 90 | `0xc4743d049891ea4333f8b559d09a93c3511f0762` | BAS3D | 587 | unverified-leftover | — | Y | unscanned | 3 |
| 91 | `0x17a8541b82bf67e10b0874284b4ae66858cb1fd5` | Possum Finance | 591 | unverified-leftover | — | Y | unscanned | 3 |
| 92 | `0x4ae1a0d592dc4d1c51d37c2aefe6d2572fc47f7a` | Spectrumswap | 597 | unverified-leftover | — | Y | unscanned | 3 |
| 93 | `0x84fd7cc4cd689fc021ee3d00759b6d255269d538` | PanKUKU | 630 | unverified-leftover | — | Y | unscanned | 3 |
| 94 | `0x194f360d130f2393a5e9f3117a6a1b78abea1624` | Summer.fi Pro | 631 | unverified-leftover | — | Y | unscanned | 3 |
| 95 | `0xe594b57e7f11ec1e8af9f003f74fa52b7aefdc9f` | Horiza | 664 | unverified-leftover | — | Y | unscanned | 3 |
| 96 | `0x28f45ea79c50d3ed9e1fa8a41dc8595f636ec34d` | Nano Swap | 664 | unverified-leftover | — | Y | unscanned | 3 |
| 97 | `0x4957c1c073557bff33c01a7ca1436d0d2409d439` | ChampagneSwap | 686 | unverified-leftover | — | Y | unscanned | 3 |
| 98 | `0x602eb0d99a5e3e76d1510372c4d2020e12eaea8a` | OasisSwap | 693 | unverified-leftover | — | Y | unscanned | 3 |
| 99 | `0x52da160e9a8cef972ff0a797d4902ed67589f64c` | TrainSwap | 710 | unverified-leftover | — | Y | unscanned | 3 |
| 100 | `0xa6e53f07bd410df069e20ced725bdc9135146fe9` | RetroDefi | 717 | unverified-leftover | — | Y | unscanned | 3 |
