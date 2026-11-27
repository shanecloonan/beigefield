# Under-$5,000 balance-ranked queue (500 contracts)

Generated 2026-11-27T20:15:01Z · chain: ethereum · 500 contracts

Queue 3. Ordered by the ETH plus major-token balance measured at the address, highest first. Queue 1 and queue 2 are unchanged. Pushing `eth-scanner/signal-rerun.trigger` still scans queue 1. Pushing `eth-scanner/signal-rerun-q2.trigger` still scans queue 2. This file has no trigger, so adding it does not scan it.

## Cutoff

- **Band:** at least $0.01 and under $5,000 of native ETH plus WETH, USDC, USDT, DAI, WBTC, stETH, wstETH, and USDe.
- **Order:** measured dollars descending, then address.
- **Contracts only:** an empty account, a major token, or a router is left out.
- **Not this queue:** anything already in `small_value_queue.json`, `small_value_under5k_queue.json`, or `small_value_under5k_queue_2.json`, or on the signal-rerun seen skip list.
- **Range:** $0.34 to $4998.80. 239 of these 500 hold at least $100. 89 further measured balances in the band stay off this list.

## Where they came from

| list | n |
|---|---|
| curve-pool | 280 |
| llama-protocol | 177 |
| list-2 | 29 |
| holder | 7 |
| morpho-vault | 3 |
| registry | 2 |
| list-1 | 1 |
| univ2-fork-allPairs | 1 |

- Sources: held-measure=292, llama-address=177, remeasured=31
- The earlier held-funds run did not save the under-$5,000 figures. This list measured candidates again on a public RPC. Alchemy compute units used: 0.

## Later run

When a run is wanted, after the Alchemy cap resets: `cd eth-scanner && python -m eth_scanner signal-rerun --small-value-batch --queue 3 --batch-size 75 --budget-cu 250000 --deadline-minutes 55 --dry-run --json`

## Queue

| # | address | name | funds_usd | reason_class | list |
|---|---|---|---|---|---|
| 1 | `0x93ed3fbe21207ec2e8f2d3c3de6e058cb73bc04d` | Kleros | 4998.80 | unverified-leftover | llama-protocol |
| 2 | `0xc9bca88b04581699fab5aa276ccaff7df957cbbf` | Ethervista | 4900 | unverified-leftover | llama-protocol |
| 3 | `0x76ec974feaf0293f64cf8643e0f42dea5b71689b` | ShibaSwap | 4868.61 | amm-fork-thin-pool | univ2-fork-allPairs |
| 4 | `0x515d7e9d75e2b76db60f8a051cd890eba23286bc` | Governor DAO | 4854.16 | unverified-leftover | llama-protocol |
| 5 | `0x322135dd9cbae8afa84727d9ae1434b5b3eba44b` | Curve.fi Factory Crypto Pool: PRISMA/ETH | 4797.88 | amm-fork-thin-pool | curve-pool |
| 6 | `0xc57ce1ac61081c51596e55de38d35b19720d421e` | USDO/USDC | 4797.76 | amm-fork-thin-pool | curve-pool |
| 7 | `0x8b878afe454e31cf0a79c6d7cf2f077dd286c12f` | DeFi Stable Avengers | 4514.50 | amm-fork-thin-pool | curve-pool |
| 8 | `0xc8f40791b6c2ff6ae42836d3966b11874432edeb` | YLAY/ETH | 4476.57 | amm-fork-thin-pool | curve-pool |
| 9 | `0xd82c2eb10f4895cabed6eda6eeee234bd1a9838b` | Curve.fi Factory Plain Pool: ETHx/WETH | 4333.26 | amm-fork-thin-pool | curve-pool |
| 10 | `0x090185f2135308bad17527004364ebcc2d37e5f6` | Abracadabra Spell | 4327.58 | unverified-leftover | llama-protocol |
| 11 | `0x1e4ede388cbc9f4b5c79681b7f94d36a11abebc9` | X2Y2 | 4215.20 | unverified-leftover | llama-protocol |
| 12 | `0x83f14c06740d28f03a670b2e0f8a134d9ccb8efe` | evaUSDC Core | 3975.59 | amm-fork-thin-pool | curve-pool |
| 13 | `0x1f03a016c47efe9a43e367b694fc67277c21736c` | loAZND/AZND | 3910.17 | amm-fork-thin-pool | curve-pool |
| 14 | `0xc944e90c64b2c07662a292be6244bdf05cda44a7` | The Graph | 3839.11 | unverified-leftover | llama-protocol |
| 15 | `0x2e2d6c119bdf226c420cb40e3b9fc9689cf5986e` | iUSD/USDC | 3823.05 | amm-fork-thin-pool | curve-pool |
| 16 | `0x000000000073f8f0541e942d85ef5fb5d0e84844` | Major-token holder | 3529.32 | unverified-leftover | holder |
| 17 | `0x21bfbda47a0b4b5b1248c767ee49f7caa9b23697` | OVR | 3496.11 | unverified-leftover | llama-protocol |
| 18 | `0x8ce9137d39326ad0cd6491fb5cc0cba0e089b6a9` | Swipe | 3416.30 | unverified-leftover | llama-protocol |
| 19 | `0x88acdd2a6425c3faae4bc9650fd7e27e0bebb7ab` | Alchemist | 3365.41 | unverified-leftover | llama-protocol |
| 20 | `0x6685fcfce05e7502bf9f0aa03b36025b09374726` | vETH/ETH | 3319.08 | amm-fork-thin-pool | curve-pool |
| 21 | `0xe53ec727dbdeb9e2d5456c3be40cff031ab40a55` | SuperFarm | 3138.31 | unverified-leftover | llama-protocol |
| 22 | `0x389999216860ab8e0175387a0c90e5c52522c945` | Fegex | 3116.77 | unverified-leftover | llama-protocol |
| 23 | `0x767fe9edc9e0df98e07454847909b5e959d7ca0e` | Illuvium | 3026.43 | unverified-leftover | llama-protocol |
| 24 | `0xf05bc5c38a8f5e3d98c72f11bc59e713f8a32228` | ynRWAx/USDC | 2968.40 | amm-fork-thin-pool | curve-pool |
| 25 | `0xa4d7f7d37f806c73f40ef2340f371072eabd3ab6` | XAUt/WETH/WBTC | 2916.44 | amm-fork-thin-pool | curve-pool |
| 26 | `0xacd8f2523a4613eee78904354187c81bb05ae2b8` | Stand Cash | 2900 | unverified-leftover | llama-protocol |
| 27 | `0x2034b76bb7318d5fda07ec183c0308c5e06c9c8c` | SQUILL/ETH | 2880.96 | amm-fork-thin-pool | curve-pool |
| 28 | `0x50f3752289e1456bfa505afd37b241bca23e685d` | Curve.fi Factory Crypto Pool: BADGER/WBTC | 2799.16 | amm-fork-thin-pool | curve-pool |
| 29 | `0x30d20208d987713f46dfd34ef128bb16c404d10f` | Stader | 2795.45 | unverified-leftover | llama-protocol |
| 30 | `0x8ac64ba8e440ce5c2d08688f4020698b1826152e` | Curve.fi Factory Crypto Pool: dYFI/ETH | 2738.82 | amm-fork-thin-pool | curve-pool |
| 31 | `0x880f2fb3704f1875361de6ee59629c6c6497a5e3` | Curve.fi Factory Crypto Pool: eUSD/USDC | 2727.13 | amm-fork-thin-pool | curve-pool |
| 32 | `0x14fee680690900ba0cccfc76ad70fd1b95d10e16` | PAAL AI | 2706.51 | unverified-leftover | llama-protocol |
| 33 | `0x5d2a5da4245f24a954bb1fb3ca24726d7ff88056` | @G/USDT | 2669.78 | amm-fork-thin-pool | curve-pool |
| 34 | `0xd291e7a03283640fdc51b121ac401383a46cc623` | Rari Capital | 2469.84 | unverified-leftover | llama-protocol |
| 35 | `0x66a0f676479cee1d7373f3dc2e2952778bff5bd6` | Wise Token | 2466.23 | unverified-leftover | llama-protocol |
| 36 | `0xa36fdbbae3c9d55a1d67ee5821d53b50b63a1ab9` | Tempus Finance | 2421 | unverified-leftover | llama-protocol |
| 37 | `0x6123b0049f904d730db3c36a31167d9d4121fa6b` | Ribbon | 2380 | unverified-leftover | llama-protocol |
| 38 | `0x5a3e6a77ba2f983ec0d371ea3b475f8bc0811ad5` | 0x0.ai | 2324.61 | unverified-leftover | llama-protocol |
| 39 | `0x85eee30c52b0b379b046fb0f85f4f3dc3009afec` | KEEP Network | 2322 | unverified-leftover | llama-protocol |
| 40 | `0x583f5b3d9081d7e2f6eb4fa7787f25415b61f99e` | LMR/ETH | 2292.18 | amm-fork-thin-pool | curve-pool |
| 41 | `0x5fe72ed557d8a02fff49b3b826792c765d5ce162` | Shezmu | 2207.72 | unverified-leftover | llama-protocol |
| 42 | `0x92d6c1e31e14520e676a687f0a93788b716beff5` | dYdX V3 | 2193.11 | unverified-leftover | llama-protocol |
| 43 | `0x3bd7d4f524d09f4e331577247a048d56e4b67a7f` | 5ire Dapp Staking | 2127.08 | unverified-leftover | llama-protocol |
| 44 | `0x2861e4d8e26b10029e5cd1d236239f810c664b99` | Pinyottas | 2082.90 | unverified-leftover | list-1 |
| 45 | `0xaeb3607ec434454ceb308f5cd540875efb54309a` | Sturdy V2 | 2000 | unverified-leftover | llama-protocol |
| 46 | `0x081f67afa0ccf8c7b17540767bbe95df2ba8d97f` | CoinEx | 1986.10 | unverified-leftover | llama-protocol |
| 47 | `0xef3a1cae64848f9eb25022de4dcb77b40affe419` | a | 1963.17 | amm-fork-thin-pool | curve-pool |
| 48 | `0xef53462838000184f35f7d991452e5f25110b207` | Knit Finance | 1890.21 | unverified-leftover | llama-protocol |
| 49 | `0xd221b4c109841a97f241d8bfd45ad8f2b99cf22d` | MET/WETH | 1812.96 | amm-fork-thin-pool | curve-pool |
| 50 | `0xee04382c4ca6c450213923fe0f0dab19b0ff3939` | rswETH/ETH | 1805.58 | amm-fork-thin-pool | curve-pool |
| 51 | `0x286c0936c7eaf6651099ab5dab9ee5a6cb5d229d` | KwikSwap | 1762.50 | unverified-leftover | llama-protocol |
| 52 | `0xc5424b857f758e906013f3555dad202e4bdb4567` | Curve.fi ETH/sETH | 1752.25 | amm-fork-thin-pool | curve-pool |
| 53 | `0x8888801af4d980682e47f1a9036e589479e835c5` | 88mph | 1743.41 | unverified-leftover | llama-protocol |
| 54 | `0x57e114b691db790c35207b2e685d4a43181e6061` | Ethena USDe | 1694.59 | unverified-leftover | llama-protocol |
| 55 | `0x3322f41dfa379b6d3050c1e271b0b435b3ee3303` | LSDx Farm | 1658.04 | unverified-leftover | list-2 |
| 56 | `0xa9d2f92b7dedf7da162bfadc321407e28815fd4a` | USDX/USDC | 1641.39 | amm-fork-thin-pool | curve-pool |
| 57 | `0xe28b3b32b6c345a34ff64674606124dd5aceca30` | Injective Bridge | 1612.04 | unverified-leftover | llama-protocol |
| 58 | `0xe1b96555bbeca40e583bbb41a11c68ca4706a414` | apxUSD-USDC | 1604 | amm-fork-thin-pool | curve-pool |
| 59 | `0xc477d038d5420c6a9e0b031712f61c5120090de9` | Boson Protocol | 1595.41 | unverified-leftover | llama-protocol |
| 60 | `0xe63d6b308bce0f6193aec6b7e6eba005f41e36ab` | StoneDefi | 1479.01 | unverified-leftover | llama-protocol |
| 61 | `0x00d76633a1071e9aed6158ae1a5e1c4c5dc75e54` | StoneDefi | 1457.64 | unverified-leftover | list-2 |
| 62 | `0xbc396689893d065f41bc2c6ecbee5e0085233447` | Perpetual Protocol | 1450 | unverified-leftover | llama-protocol |
| 63 | `0x80ce3027a70e0a928d9268994e9b85d03bd4cdcf` | UniFarm | 1420.07 | unverified-leftover | list-2 |
| 64 | `0x455e53cbb86018ac2b8092fdcd39d8444affc3f6` | Polygon Bridge | 1333.59 | unverified-leftover | llama-protocol |
| 65 | `0x56be5d27878bf847189f5a6a29ed1350177c7420` | CJPY/ETH/TXJP | 1329.92 | amm-fork-thin-pool | curve-pool |
| 66 | `0xf403c135812408bfbe8713b5a23a04b3d48aae31` | Convex Booster | 1300 | unverified-leftover | registry |
| 67 | `0x2de509bf0014ddf697b220be628213034d320ece` | 9inch V2 | 1278.81 | unverified-leftover | list-2 |
| 68 | `0x3d6f0dea3ac3c607b3998e6ce14b6350721752d9` | Cardstarter | 1271.95 | unverified-leftover | llama-protocol |
| 69 | `0x498c00e1ccc2afff80f6cc6144eaeb95c46cc3b5` | Agility LSD | 1271.86 | unverified-leftover | list-2 |
| 70 | `0x466ebb6eeec7a3fd0628f6b05e53e848f9f3451f` | DBIT/WBTC | 1250.24 | amm-fork-thin-pool | curve-pool |
| 71 | `0x1ceb5cb57c4d4e2b2433641b95dd330a33185a44` | Keep3r Network | 1230.61 | unverified-leftover | llama-protocol |
| 72 | `0x6206ca315c2fcdd2a857b47efb285aa12c529a7a` | USDC/sUSDat | 1196.26 | amm-fork-thin-pool | curve-pool |
| 73 | `0x32b053f2cba79f80ada5078cb6b305da92bde6e1` | NeuralAI | 1180.51 | unverified-leftover | llama-protocol |
| 74 | `0x4e6706889d519ba6e6ced330d76582f875df3c9c` | Curve.fi Factory Crypto Pool: Schmeckles / ETH | 1159.39 | amm-fork-thin-pool | curve-pool |
| 75 | `0xd9c2d319cd7e6177336b0a9c93c21cb48d84fb54` | UniFarm | 1138.09 | unverified-leftover | list-2 |
| 76 | `0xf253f83aca21aabd2a20553ae0bf7f65c755a07f` | Curve.fi wBTC/sBTC | 1131.09 | amm-fork-thin-pool | curve-pool |
| 77 | `0x00836fe54625be242bcfa286207795405ca4fd10` | Spark.fi USDT Reserve | 1130 | amm-fork-thin-pool | curve-pool |
| 78 | `0x5da151b95657e788076d04d56234bd93e409cb09` | OTSea | 1122.17 | unverified-leftover | llama-protocol |
| 79 | `0x72e9d9038ce484ee986fea183f8d8df93f9ada13` | SmartCredit | 1114.28 | unverified-leftover | llama-protocol |
| 80 | `0x90343fc2e9449e9cd001be955fad9727c815ec6d` | WBTC/svetBTC | 1114.16 | amm-fork-thin-pool | curve-pool |
| 81 | `0xdad60c5b748306ba5a0c9a3c3482a8d1153dad2a` | Curve.fi Factory Crypto Pool: PAR/USDC | 1110.74 | amm-fork-thin-pool | curve-pool |
| 82 | `0x817bbdbc3e8a1204f3691d14bb44992841e3db35` | UniFarm | 1096 | unverified-leftover | list-2 |
| 83 | `0x941eb6f616114e4ecaa85377945ea306002612fe` | Curve.fi Factory Crypto Pool: FXS/ETH | 1090.65 | amm-fork-thin-pool | curve-pool |
| 84 | `0x6e77889ff348a16547caba3ce011cb120ed73bfc` | Curve.fi Factory Crypto Pool: frETH/WETH | 1084.13 | amm-fork-thin-pool | curve-pool |
| 85 | `0x993864e43caa7f7f12953ad6feb1d1ca635b875f` | SingularityDAO | 1053.03 | unverified-leftover | llama-protocol |
| 86 | `0xf8c3527cc04340b208c854e985240c02f7b7793f` | UniFarm | 1050 | unverified-leftover | list-2 |
| 87 | `0x77777777772cf0455fb38ee0e75f38034dfa50de` | XY Finance | 1028.47 | unverified-leftover | llama-protocol |
| 88 | `0x1f9840a85d5af5bf1d1762f925bdaddc4201f984` | Uniswap V3 | 1027.57 | unverified-leftover | llama-protocol |
| 89 | `0xe689585a8663a3dfcd28bfb274284610e6cca038` | fBOMB/USDC | 1014.66 | amm-fork-thin-pool | curve-pool |
| 90 | `0x26642be81ffd799b8588a5602758d1f34e9ff7ba` | Varen | 1005.37 | unverified-leftover | list-2 |
| 91 | `0x320623b8e4ff03373931769a31fc52a4e78b5d70` | Reserve Protocol | 1002 | unverified-leftover | llama-protocol |
| 92 | `0x86772b1409b61c639eaac9ba0acfbb6e238e5f83` | Indexed Finance | 1000 | unverified-leftover | llama-protocol |
| 93 | `0x97d0cfeb4fde54b430307c9482d6f79c761fe9b6` | Epoch Island | 1000 | unverified-leftover | llama-protocol |
| 94 | `0xa12cc123ba206d4031d1c7f6223d1c2ec249f4f3` | Zama | 1000 | unverified-leftover | llama-protocol |
| 95 | `0x4484a052a0be82af20896ea3c8d891a3d11e8d1a` | LLAMAwnft/ETH | 995.16 | amm-fork-thin-pool | curve-pool |
| 96 | `0x9570e20ff75058ccf212deb20a352c4f971de11a` | Aivnir/USDC | 953.76 | amm-fork-thin-pool | curve-pool |
| 97 | `0x44971abf0251958492fee97da3e5c5ada88b9185` | based AI | 953.30 | unverified-leftover | llama-protocol |
| 98 | `0xa0b73e1ff0b80914ab6fe0444e65848c4c34450b` | Defi Swap | 940.79 | unverified-leftover | llama-protocol |
| 99 | `0x94e653af059550657e839a5dfcca5a17fd17efdf` | Domination Finance | 918.07 | unverified-leftover | list-2 |
| 100 | `0x05001f08e5ab5a4c6b6996bdfb5c7f5ed3fb3809` | wolf/usdc | 891.45 | amm-fork-thin-pool | curve-pool |
| 101 | `0x8cd52ee292313c4d851e71a7064f096504ab3ee9` | TricryptoGHO | 874.40 | amm-fork-thin-pool | curve-pool |
| 102 | `0xe8d6db9c5ccb3a2fc299a348a19f7439c06e847a` | Curve.fi Factory Crypto Pool: CAW/ETH | 835.03 | amm-fork-thin-pool | curve-pool |
| 103 | `0x43dfc4159d86f3a37a5a4b3d4580b888ad7d4ddd` | DODO AMM | 828.64 | unverified-leftover | llama-protocol |
| 104 | `0xbbbbca6a901c926f240b89eacb641d8aec7aeafd` | Loopring | 793.87 | unverified-leftover | llama-protocol |
| 105 | `0x33918bdc50e021d057145e17d3f31ac97f589e1d` | Ensuro | 773.36 | unverified-leftover | list-2 |
| 106 | `0x717170b66654292dfbd89c39f5ae6753d2ac1381` | Cryptex V1 | 768.33 | unverified-leftover | list-2 |
| 107 | `0x8c8687fc965593dfb2f0b4eaefd55e9d8df348df` | UniFarm | 749.12 | unverified-leftover | list-2 |
| 108 | `0xf2e47b9bcb26463a12b1409be06fdaa1c308aa65` | vetBTC/WBTC | 743.01 | amm-fork-thin-pool | curve-pool |
| 109 | `0xbe739fe57b9862e9cf17835687e8c008cf8e121c` | AID/USDC | 737.11 | amm-fork-thin-pool | curve-pool |
| 110 | `0xd3a0e00f11a91da9797eef5b74df8fc325fc50e0` | Domination Finance | 730.06 | unverified-leftover | list-2 |
| 111 | `0x292fcdd1b104de5a00250febba9bc6a5092a0076` | HashAI | 729.65 | unverified-leftover | llama-protocol |
| 112 | `0x195734d862dfb5380eeda0acd8acf697ea95d370` | Varen | 727.22 | unverified-leftover | list-2 |
| 113 | `0x0cec1a9154ff802e7934fc916ed7ca50bde6844e` | PoolTogether V3 | 718.85 | unverified-leftover | llama-protocol |
| 114 | `0x61635d1de721dd1db35f8acfd0f1ea367df65671` | Risk Harbor | 709.59 | unverified-leftover | list-2 |
| 115 | `0x7448c7456a97769f6cd04f1e83a4a23ccdc46abd` | Maverick V1 | 706.79 | unverified-leftover | llama-protocol |
| 116 | `0x6055dc6ff1077eebe5e6d2ba1a1f53d7ef8430de` | Eclipse Bridge | 698.96 | unverified-leftover | llama-protocol |
| 117 | `0x31b46c84e4fb0704de69dbf4b054b5cb81aa3736` | LYU/USD | 684.58 | amm-fork-thin-pool | curve-pool |
| 118 | `0x51f5466690978173f45270f57e06e25b0c888261` | tacUSD/USDT | 676.14 | amm-fork-thin-pool | curve-pool |
| 119 | `0x590f820444fa3638e022776752c5eef34e2f89a6` | Alephium Bridge | 663.95 | unverified-leftover | list-2 |
| 120 | `0x4e0915c88bc70750d68c481540f081fefaf22273` | Curve.fi 4pool USDC/USDT/UST/FRAX | 648.71 | amm-fork-thin-pool | curve-pool |
| 121 | `0xd084b83c305dafd76ae3e1b4e1f1fe2ecccb3988` | UniFarm | 647.50 | unverified-leftover | list-2 |
| 122 | `0x5a8c7623fee10542614e492c670a67e3dfe922f8` | USDQ/USDT | 636.70 | amm-fork-thin-pool | curve-pool |
| 123 | `0xb723a224c9acf3891b20437b4d55dd45600f5fa3` | trUSD/USDC | 616.86 | amm-fork-thin-pool | curve-pool |
| 124 | `0x523f6b7c7b314228f0de8c9924b8b8c8c08a2bff` | BTCD | 601.28 | unverified-leftover | list-2 |
| 125 | `0x2f57430a6ceda85a67121757785877b4a71b8e6d` | DefiPlaza | 599 | unverified-leftover | llama-protocol |
| 126 | `0xe63684bcf2987892cefb4caa79bd21b34e98a291` | ChickenSwap | 598.66 | unverified-leftover | llama-protocol |
| 127 | `0x95a4492f028aa1fd432ea71146b433e7b4446611` | APY Finance | 588.50 | unverified-leftover | llama-protocol |
| 128 | `0x5a98fcbea516cf06857215779fd812ca3bef1b32` | Lido | 584.80 | unverified-leftover | llama-protocol |
| 129 | `0xd478161c952357f05f0292b56012cd8457f1cfbf` | Meter Passport | 578 | unverified-leftover | list-2 |
| 130 | `0x3dd46846eed8d147841ae162c8425c08bd8e1b41` | mStable V2 | 575.16 | unverified-leftover | list-2 |
| 131 | `0x463626cf9028d96ead5084954ff634f813d5ffb9` | alUSDUSDC Almanak | 567.84 | amm-fork-thin-pool | curve-pool |
| 132 | `0xc2ba6b8e0ee3cf48b045d966f1dcda767df74833` | Cryptex V1 | 561.49 | unverified-leftover | list-2 |
| 133 | `0x58d97b57bb95320f9a05dc918aef65434969c2b2` | Morpho Blue | 560.89 | unverified-leftover | llama-protocol |
| 134 | `0x1f7e9321ce32af1f9ea1185fd10d31fea31ffd95` | hETH/WETH | 556.87 | amm-fork-thin-pool | curve-pool |
| 135 | `0xd3bcd417aee942fd4611b8fe6ffca500019045cf` | mUSD/USDT | 553.16 | amm-fork-thin-pool | curve-pool |
| 136 | `0x618679df9efcd19694bb1daa8d00718eacfa2883` | Universe XYZ | 547 | unverified-leftover | llama-protocol |
| 137 | `0xf57e7e7c23978c3caec3c3548e3d615c346e79ff` | Immutable zkEVM | 540.96 | unverified-leftover | llama-protocol |
| 138 | `0x37cee65899da4b1738412814155540c98dfd752c` | Varen | 528.91 | unverified-leftover | list-2 |
| 139 | `0x2865568ad1ca0fe12db53c8f866039fa4500962f` | Olive Network | 521.87 | unverified-leftover | list-2 |
| 140 | `0x3c3a81e81dc49a522a592e7622a7e711c06bf354` | Mantle Bridge | 512.94 | unverified-leftover | llama-protocol |
| 141 | `0xec53bf9167f50cdeb3ae105f56099aaab9061f83` | EigenCloud | 512.13 | unverified-leftover | llama-protocol |
| 142 | `0x9565c2036963697786705120fc59310f747bcfd0` | 9inch V2 | 502.47 | unverified-leftover | list-2 |
| 143 | `0x054f76beed60ab6dbeb23502178c52d6c5debe40` | BoringDAO | 500 | unverified-leftover | list-2 |
| 144 | `0x3abf2a4f8452ccc2cf7b4c1e4663147600646f66` | Juicebox V1 | 500 | unverified-leftover | llama-protocol |
| 145 | `0xb6ca7399b4f9ca56fc27cbff44f4d2e4eef1fc81` | NFT20 | 500 | unverified-leftover | llama-protocol |
| 146 | `0xfe3e6a25e6b192a42a44ecddcd13796471735acf` | UniFarm | 500 | unverified-leftover | list-2 |
| 147 | `0xff20817765cb7f73d4bde2e66e067e58d11095c2` | Flexa | 500 | unverified-leftover | llama-protocol |
| 148 | `0xeb964a1a6fab73b8c72a0d15c7337fa4804f484d` | Hemi Bridge | 499 | unverified-leftover | llama-protocol |
| 149 | `0x31429d1856ad1377a8a0079410b297e1a9e214c2` | Angle | 496.91 | unverified-leftover | llama-protocol |
| 150 | `0x75aaf03cbf330e2b3f0623c55b7a528cfcae8d75` | XUSD Money | 495.21 | unverified-leftover | list-2 |
| 151 | `0xda31d0d1bc934fc34f7189e38a413ca0a5e8b44f` | BitStable Finance | 489.48 | unverified-leftover | llama-protocol |
| 152 | `0x000000000000d0151e748d25b766e77efe2a6c83` | XDeFi | 486.05 | unverified-leftover | llama-protocol |
| 153 | `0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e` | Yearn Ether | 485.74 | unverified-leftover | llama-protocol |
| 154 | `0xcb84d72e61e383767c4dfeb2d8ff7f4fb89abc6e` | Vega Protocol | 484.98 | unverified-leftover | llama-protocol |
| 155 | `0x8e001d4bac0eae1eea348dfc22f9b8bda67dd211` | RLP/USDC | 479.67 | amm-fork-thin-pool | curve-pool |
| 156 | `0x838af967537350d2c44abb8c010e49e32673ab94` | Curve.fi Factory Crypto Pool: CNC/ETH | 459.54 | amm-fork-thin-pool | curve-pool |
| 157 | `0x6853836803fc110c2a23a821aa604efc1bef1783` | Curve.fi Factory Crypto Pool: QOM/ETH | 457.03 | amm-fork-thin-pool | curve-pool |
| 158 | `0xf0909ea2428bbba587797d6874a3f611b31d907c` | ROME+USDT | 445.96 | amm-fork-thin-pool | curve-pool |
| 159 | `0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9` | Aave V2 LendingPool | 430.58 | unverified-leftover | registry |
| 160 | `0xdc013262350d8add77b2e00d4fd48f87db916352` | Curve.fi Factory Crypto Pool: O/ETH | 416.31 | amm-fork-thin-pool | curve-pool |
| 161 | `0x3d3d35bb9bec23b06ca00fe472b50e7a4c692c30` | Vidya | 405.30 | unverified-leftover | llama-protocol |
| 162 | `0xf8e9f10c22840b613cda05a0c5fdb59a4d6cd7ef` | Dogs of Elon | 401.57 | unverified-leftover | llama-protocol |
| 163 | `0x752efadc0a7e05ad1bcccda22c141d01a75ef1e4` | CompliFi | 400 | unverified-leftover | llama-protocol |
| 164 | `0x8290333cef9e6d528dd5618fb97a76f268f3edd4` | Ankr | 400 | unverified-leftover | llama-protocol |
| 165 | `0x35d6db0280a927fade251d44d506ac4010c0dc9a` | shezETH/ETH | 393.05 | amm-fork-thin-pool | curve-pool |
| 166 | `0x79b6a7c23d23ef7c180e7fbe235c914dc5e6fa1f` | Maroshi USDC/sUSDe | 350.98 | amm-fork-thin-pool | curve-pool |
| 167 | `0xaa4e3edb11afa93c41db59842b29de64b72e355b` | MarginSwap | 350 | unverified-leftover | llama-protocol |
| 168 | `0x75a6787c7ee60424358b449b539a8b774c9b4862` | Curve.fi Factory Crypto Pool: PAL/ETH | 348.91 | amm-fork-thin-pool | curve-pool |
| 169 | `0x98638facf9a3865cd033f36548713183f6996122` | Curve SPELL-ETH | 348.53 | amm-fork-thin-pool | curve-pool |
| 170 | `0xc770eefad204b5180df6a14ee197d99d808ee52d` | ShapeShift | 332.34 | unverified-leftover | llama-protocol |
| 171 | `0x88800092ff476844f74dc2fc427974bbee2794ae` | Ambire Wallet | 329.55 | unverified-leftover | llama-protocol |
| 172 | `0x36a5bdda5cc5230b9189944cf4c8c8d58a5747d0` | ShezUSD/USDC | 318.65 | amm-fork-thin-pool | curve-pool |
| 173 | `0x7f9b09f4717072cf4dc18b95d1b09e2b30c76790` | Vault Tech | 310.17 | unverified-leftover | llama-protocol |
| 174 | `0xc881255e4d639b42e326158c7b8ccb7f33459261` | BitSwap | 310 | unverified-leftover | llama-protocol |
| 175 | `0x84d821f7fbdd595c4c4a50842913e6b1e07d7a53` | BNPL Pay | 300 | unverified-leftover | llama-protocol |
| 176 | `0x922d8563631b03c2c4cf817f4d18f6883aba0109` | Houdini Swap | 284.93 | unverified-leftover | llama-protocol |
| 177 | `0x4ca9b3063ec5866a4b82e437059d2c43d1be596f` | Curve.fi hBTC/wBTC | 280.60 | amm-fork-thin-pool | curve-pool |
| 178 | `0xf2f9a7e93f845b3ce154efbeb64fb9346fcce509` | UniPower | 264.08 | unverified-leftover | llama-protocol |
| 179 | `0x637213593e31bc25f49d37c74b43a89eb1743d73` | shezETH/ETH | 262.49 | amm-fork-thin-pool | curve-pool |
| 180 | `0x1bb9b64927e0c5e207c9db4093b3738eef5d8447` | Vector Reserve | 244 | unverified-leftover | llama-protocol |
| 181 | `0xeb83b63b9f943a2fe15a72dfac1a9e35858884d4` | ROME/USDT | 240.79 | amm-fork-thin-pool | curve-pool |
| 182 | `0x3496b523e5c00a4b4150d6721320cddb234c3079` | Numbers Protocol | 240.77 | unverified-leftover | llama-protocol |
| 183 | `0x043c308bb8a5ae96d0093444be7f56459f1340b1` | SumSwap | 238.46 | unverified-leftover | llama-protocol |
| 184 | `0xa0246c9032bc3a600820415ae600c6388619a14d` | Harvest Finance | 225.45 | unverified-leftover | llama-protocol |
| 185 | `0x1005f7406f32a61bd760cfa14accd2737913d546` | Curve.fi 2Pool USDC/USDT | 219.05 | amm-fork-thin-pool | curve-pool |
| 186 | `0x5ac4fcee123dcadfae22bc814c4cc72b96c93f38` | Curve.fi Factory Crypto Pool: eCFX/ETH | 210.24 | amm-fork-thin-pool | curve-pool |
| 187 | `0x6031bdd613e6a2f587b244e078053fe7bbabe3b5` | ZCHF/USDT | 202.07 | amm-fork-thin-pool | curve-pool |
| 188 | `0xdbb1d219d84eacefb850ee04cacf2f1830934580` | frxUSD/USDe | 200.65 | amm-fork-thin-pool | curve-pool |
| 189 | `0xed1167b6dc64e8a366db86f2e952a482d0981ebd` | Lybra V1 | 200 | unverified-leftover | llama-protocol |
| 190 | `0x2e1776968ec75bfd13dbc5b94ae57034d7e85fb9` | savUSD/USDC | 199.93 | amm-fork-thin-pool | curve-pool |
| 191 | `0xbfab6fa95e0091ed66058ad493189d2cb29385e6` | Curve.fi ETH/wBETH | 197.46 | amm-fork-thin-pool | curve-pool |
| 192 | `0x6e2076fbad47264e911cf8a63bc0451760b88a86` | wETH/DINGTHINGDING | 190.06 | amm-fork-thin-pool | curve-pool |
| 193 | `0xd9fcd98c322942075a5c3860693e9f4f03aae07b` | Euler V1 | 187.80 | unverified-leftover | llama-protocol |
| 194 | `0x579cea1889991f68acc35ff5c3dd0621ff29b0c9` | IQ | 186.08 | unverified-leftover | llama-protocol |
| 195 | `0x86ea1191a219989d2da3a85c949a12a92f8ed3db` | CDCETH | 182.85 | amm-fork-thin-pool | curve-pool |
| 196 | `0x404fdada7fc68b5b633d184067c9643732f8a045` | uniBTC/wBTC | 180.91 | amm-fork-thin-pool | curve-pool |
| 197 | `0xfd94a5dcb0e52fdd076bee3ea1aa16c48081660c` | LVBTC/WBTC | 180.23 | amm-fork-thin-pool | curve-pool |
| 198 | `0x66267c6e24fbcdebf06ae9104e0ccfb9c8b2ae08` | shezUSD/USDC | 179.36 | amm-fork-thin-pool | curve-pool |
| 199 | `0x9432242d9dc10ad5e2fe570b8fc053a16597caf6` | NPC Current Thing | 178.18 | amm-fork-thin-pool | curve-pool |
| 200 | `0x5f0e628b693018f639d10e4a4f59bd4d8b2b6b44` | Whiteheart | 177 | unverified-leftover | llama-protocol |
| 201 | `0x441761326490cacf7af299725b6292597ee822c2` | UniFi | 175 | unverified-leftover | llama-protocol |
| 202 | `0x6bfe880ed1d639bf80167b93cc9c56a39c1ba2dc` | Curve.fi Factory Crypto Pool: PAIR_ETH_MATIC | 172.71 | amm-fork-thin-pool | curve-pool |
| 203 | `0xf4cd3d3fda8d7fd6c5a500203e38640a70bf9577` | YFDAI | 172.19 | unverified-leftover | llama-protocol |
| 204 | `0x62bfea5673c6336d265865e5ea1d32f67c523c33` | POOH/wETH/crvUSD | 171.53 | amm-fork-thin-pool | curve-pool |
| 205 | `0xb4018cb02e264c3fcfe0f21a1f5cfbcaaba9f61f` | Curve.fi Factory Crypto Pool: ARTH/USDC | 168.99 | amm-fork-thin-pool | curve-pool |
| 206 | `0xa0df17b5ac76ababa36e1450e2cbcd18a620c845` | Fake World Assets V2 | 160.44 | unverified-leftover | llama-protocol |
| 207 | `0x19ae49b9f38dd836317363839a5f6bfbfa7e319a` | SaitaSwap | 160.42 | unverified-leftover | llama-protocol |
| 208 | `0xe95e4c2dac312f31dc605533d5a4d0af42579308` | Curve.fi Factory Plain Pool: sETH2/stETH | 153.92 | amm-fork-thin-pool | curve-pool |
| 209 | `0x955244edc797a1c1b04134b600f819ac23c76081` | Puzzle Ranges | 151.74 | unverified-leftover | list-2 |
| 210 | `0x408e41876cccdc0f92210600ef50372656052a38` | RenVM | 150 | unverified-leftover | llama-protocol |
| 211 | `0x5bcaa8a1216d8120a59489f7df4585e834c90eaf` | mUSDrec/USDT | 146.50 | amm-fork-thin-pool | curve-pool |
| 212 | `0xa0d3707c569ff8c87fa923d3823ec5d81c98be78` | Major-token holder | 144.29 | unverified-leftover | holder |
| 213 | `0xeed42ee7e775f0b0865976c3b2491d4e077dece1` | Major-token holder | 143.16 | unverified-leftover | holder |
| 214 | `0xe79c1c7e24755574438a26d5e062ad2626c04662` | AUSD/USDC | 140.03 | amm-fork-thin-pool | curve-pool |
| 215 | `0x8b0afa4b63a3581b731da9d79774a3eae63b5abd` | Curve.fi Factory Crypto Pool: DYDX/ETH | 137.96 | amm-fork-thin-pool | curve-pool |
| 216 | `0x509a38b7a1cc0dcd83aa9d06214663d9ec7c7f4a` | Ocean Point | 135.52 | unverified-leftover | llama-protocol |
| 217 | `0x4507cef57c46789ef8d1a19ea45f4216bae2b528` | TokenFi | 131.83 | unverified-leftover | llama-protocol |
| 218 | `0x9dbcfc09e651c040ee68d6dbeb8a09f8dd0caa77` | ZUN/WETH | 130.20 | amm-fork-thin-pool | curve-pool |
| 219 | `0xacce4fe9ce2a6fe9af83e7cf321a3ff7675e0ab6` | Curve.fi Factory Crypto Pool: ibGBP/USDC | 125.07 | amm-fork-thin-pool | curve-pool |
| 220 | `0x4f9254c83eb525f9fcf346490bbb3ed28a81c667` | cBridge | 125 | unverified-leftover | llama-protocol |
| 221 | `0x0391d2021f89dc339f60fff84546ea23e337750f` | BarnBridge | 123 | unverified-leftover | llama-protocol |
| 222 | `0xf980b4a4194694913af231de69ab4593f5e0fcdc` | mkUSD-USDC | 115.19 | amm-fork-thin-pool | curve-pool |
| 223 | `0x0acfc0d9afdd8e794eb1c3e3c675c89664fc0f1e` | EthGRD | 114.88 | amm-fork-thin-pool | curve-pool |
| 224 | `0x712c6efcdb10024997191a7020e783cd3b8d48eb` | USDR/USDT | 114.65 | amm-fork-thin-pool | curve-pool |
| 225 | `0x5500307bcf134e5851fb4d7d8d1dc556dcdb84b4` | Curve.fi Factory Crypto Pool: BSGG/USDT | 114.55 | amm-fork-thin-pool | curve-pool |
| 226 | `0x9dfad1b7102d46b1b197b90095b5c4e9f5845bba` | Botto | 114.47 | unverified-leftover | llama-protocol |
| 227 | `0x986ee2b944c42d017f52af21c4c69b84dbea35d8` | BitMart | 113.72 | unverified-leftover | llama-protocol |
| 228 | `0x69cae865bb5efec4990692bdeb2dacaacc77086f` | BNANA/ETH | 107.79 | amm-fork-thin-pool | curve-pool |
| 229 | `0x0ce863fbb67a6a532323d1f81b8f0fcd5f5099ff` | Curve.fi Factory Crypto Pool: USDT/DEV2 | 107.24 | amm-fork-thin-pool | curve-pool |
| 230 | `0x7704d01908afd31bf647d969c295bb45230cd2d6` | eBTC/WBTC | 105.84 | amm-fork-thin-pool | curve-pool |
| 231 | `0x9ae380f0272e2162340a5bb646c354271c0f5cfc` | Conic Finance | 103.06 | unverified-leftover | llama-protocol |
| 232 | `0x12e1e335f68e520ea9aa2ba708861d7e01c1b8dc` | USDC/GS | 101.89 | amm-fork-thin-pool | curve-pool |
| 233 | `0xa91ac63d040deb1b7a5e4d4134ad23eb0ba07e14` | Bella Protocol | 101.31 | unverified-leftover | llama-protocol |
| 234 | `0x6033f7f88332b8db6ad452b7c6d5bb643990ae3f` | Lisk Bridge | 100.39 | unverified-leftover | llama-protocol |
| 235 | `0x120a3879da835a5af037bb2d1456bebd6b54d4ba` | Revest Finance | 100.20 | unverified-leftover | llama-protocol |
| 236 | `0x5a6a4d54456819380173272a5e8e9b9904bdf41b` | Curve.fi Factory USD Metapool: Magic Internet Money 3Pool | 100 | amm-fork-thin-pool | curve-pool |
| 237 | `0xb1d9b4574077eb6ed75b791c7d090ea1f8c93474` | Curve.fi Factory Crypto Pool: SLD/USDT | 100 | amm-fork-thin-pool | curve-pool |
| 238 | `0xba3335588d9403515223f109edc4eb7269a9ab5d` | Gearbox | 100 | unverified-leftover | llama-protocol |
| 239 | `0xceaf7747579696a2f0bb206a14210e3c9e6fb269` | Curve.fi Factory USD Metapool: wormhole v2 UST-3Pool | 100 | amm-fork-thin-pool | curve-pool |
| 240 | `0xca14007eff0db1f8135f4c25b34de49ab0d42766` | Starknet Bridge | 99.08 | unverified-leftover | llama-protocol |
| 241 | `0x24fcfc492c1393274b6bcd568ac9e225bec93584` | Heroes of Mavia | 98.61 | unverified-leftover | llama-protocol |
| 242 | `0xb09a96129d113845f466215dfe8dfee261ea7d17` | tGBP/USDC | 96.40 | amm-fork-thin-pool | curve-pool |
| 243 | `0xcb1592591996765ec0efc1f92599a19767ee5ffa` | Bio Protocol | 92.27 | unverified-leftover | llama-protocol |
| 244 | `0x80441ed630a10f2a36955c993c2d45bd9f848af5` | GMAC/ETH/USDC | 90.28 | amm-fork-thin-pool | curve-pool |
| 245 | `0x5f64ab1544d28732f0a24f4713c2c8ec0da089f0` | Memento DFM | 90 | unverified-leftover | llama-protocol |
| 246 | `0x87d73e916d7057945c9bcd8cdd94e42a6f47f776` | NFTX | 88.10 | unverified-leftover | llama-protocol |
| 247 | `0xb3ed706b564bba9cab64042f4e1b391be7bebce5` | Augmented Finance | 88 | unverified-leftover | llama-protocol |
| 248 | `0xf43b15ab692fde1f9c24a9fce700adcc809d5391` | Curve.fi Factory Crypto Pool: BTRFLY/ETH | 86.58 | amm-fork-thin-pool | curve-pool |
| 249 | `0xa148bd19e26ff9604f6a608e22bfb7b772d0d1a3` | Curve.fi Factory Crypto Pool: bSTBL/DAI | 85.94 | amm-fork-thin-pool | curve-pool |
| 250 | `0xd4cedef74fb8885b8e1de21fba5a2e2f33f21f58` | Curve.fi Factory Plain Pool: xETH/stETH | 85.19 | amm-fork-thin-pool | curve-pool |
| 251 | `0x126331661101057c3a5879ac6af3f30cac6c66e2` | Blotix | 84.99 | amm-fork-thin-pool | curve-pool |
| 252 | `0x75231f58b43240c9718dd58b4967c5114342a86c` | OKX | 83.83 | unverified-leftover | llama-protocol |
| 253 | `0x4e352cf164e64adcbad318c3a1e222e9eba4ce42` | MCDEX | 83.38 | unverified-leftover | llama-protocol |
| 254 | `0x004c167d27ada24305b76d80762997fa6eb8d9b2` | CVG/ETH | 82.63 | amm-fork-thin-pool | curve-pool |
| 255 | `0x6a62ee3e5c4b412cd9167d3afd5e481e1e30715a` | TriOSAK | 79.53 | amm-fork-thin-pool | curve-pool |
| 256 | `0x9a81f5a6ea7e60632f659f3f4e772ba977d80bd5` | Curve.fi Factory Crypto Pool: VEE/USDC | 76.66 | amm-fork-thin-pool | curve-pool |
| 257 | `0x2be5e8c109e2197d077d13a82daead6a9b3433c5` | Tokamak Network Staking | 73.98 | unverified-leftover | llama-protocol |
| 258 | `0xd0a1d2a9350824516ae8729b8311557ba7e55bff` | Curve.fi Factory Crypto Pool: ETH/VIRTUE | 69.67 | amm-fork-thin-pool | curve-pool |
| 259 | `0xb5ae2a6b084f59ff9ef6b2e79302a1878306d58c` | Curve.fi Factory Crypto Pool: OGV/ETH | 64.76 | amm-fork-thin-pool | curve-pool |
| 260 | `0x66a0962628bde82cb3dda560f05264407f187827` | Curve.fi Factory Crypto Pool: SPOOL/ETH | 62.97 | amm-fork-thin-pool | curve-pool |
| 261 | `0x4149d1038575ce235e03e03b39487a80fd709d31` | Curve.fi Factory Crypto Pool: ALCX/FraxBP | 60 | amm-fork-thin-pool | curve-pool |
| 262 | `0x3c42b0f384d2912661c940d46cffe1cd10f1c66f` | Curve.fi Factory Crypto Pool: [Test] Test CTDL/wBTC | 59.92 | amm-fork-thin-pool | curve-pool |
| 263 | `0x1570af3df649fc74872c5b8f280a162a3bdd4eb6` | Curve.fi Factory Crypto Pool: ibEUR/USDC | 58.87 | amm-fork-thin-pool | curve-pool |
| 264 | `0x05bc11f64c6515bb384b05bfd3e0d0424fa65aa4` | Major-token holder | 58.51 | unverified-leftover | holder |
| 265 | `0xb8baa0e4287890a5f79863ab62b7f175cecbd433` | Swerve | 57.34 | unverified-leftover | llama-protocol |
| 266 | `0x5f6c431ac417f0f430b84a666a563fabe681da94` | deUSD/USDC | 57.01 | amm-fork-thin-pool | curve-pool |
| 267 | `0x43a96962254855f16b925556f9e97be436a43448` | Hord | 56.12 | unverified-leftover | llama-protocol |
| 268 | `0xbed58c1053fd347843883eade0781f562a66f623` | TriCVG | 55.30 | amm-fork-thin-pool | curve-pool |
| 269 | `0x425651ea3ab6240a317794579ed62fcf7e7e817e` | Cypher Capital USDC | 55 | clone-erc4626-inflation | morpho-vault |
| 270 | `0x259338656198ec7a76c729514d3cb45dfbf768a1` | Resolv USR | 54.12 | unverified-leftover | llama-protocol |
| 271 | `0x16a973f8e466f44e9ea67e7e2d3166bd460ea852` | AZND/frxUSD | 52.08 | amm-fork-thin-pool | curve-pool |
| 272 | `0x04e7a76a910a499b8bbcac18411ae68454ae348b` | Curve.fi Factory Crypto Pool: CHNT/USDC | 51.28 | amm-fork-thin-pool | curve-pool |
| 273 | `0x1495bc9e44af1f8bcb62278d2bec4540cf0c05ea` | Zero1 Labs | 50 | unverified-leftover | llama-protocol |
| 274 | `0x374cb8c27130e2c9e04f44303f3c8351b9de61c1` | Bao Masterchef V1 | 50 | unverified-leftover | llama-protocol |
| 275 | `0xaf5191b0de278c7286d6c7cc6ab6bb8a73ba2cd6` | Stargate V2 | 50 | unverified-leftover | llama-protocol |
| 276 | `0xd4f4d0a10bcae123bb6655e8fe93a30d01eebd04` | LinqAI | 50 | unverified-leftover | llama-protocol |
| 277 | `0xe60779cc1b2c1d0580611c526a8df0e3f870ec48` | unshETH | 49.54 | unverified-leftover | llama-protocol |
| 278 | `0x6865be0d0da507ea57684cee935cf22ea1d5a106` | OBUSD/USDC | 48.74 | amm-fork-thin-pool | curve-pool |
| 279 | `0x3593d125a4f7849a1b059e64f4517a86dd60c95d` | MANTRA DAO | 48.50 | unverified-leftover | llama-protocol |
| 280 | `0x7785ddcece9e3c7d86279cd5e79e4e155f8eb816` | Major-token holder | 47.56 | unverified-leftover | holder |
| 281 | `0x9e32b13ce7f2e80a01932b42553652e053d6ed8e` | Metis Bridge | 47 | unverified-leftover | llama-protocol |
| 282 | `0x95f07dcd938148ef3035134fc8aba146faa0961d` | WBTC-USDC-test | 41.77 | amm-fork-thin-pool | curve-pool |
| 283 | `0xc8102c13348d23077d09c2607b9c746b2ece8768` | bfUSD/USDT | 40.19 | amm-fork-thin-pool | curve-pool |
| 284 | `0x9ad37205d608b8b219e6a2573f922094cec5c200` | iZiSwap | 40 | unverified-leftover | llama-protocol |
| 285 | `0xe789587c77bc967b1dd63429be983fc8eb17fc89` | Test/Dont/Buy | 39.76 | amm-fork-thin-pool | curve-pool |
| 286 | `0x703e226526d010734a3ea61c3f2b9c9c10197343` | Curve.fi Factory Crypto Pool: hem/weth | 38.43 | amm-fork-thin-pool | curve-pool |
| 287 | `0xbeef047a543e45807105e51a8bbefcc5950fcfba` | Steakhouse USDT | 38.41 | clone-erc4626-inflation | morpho-vault |
| 288 | `0x27cb06f65d8b7228147375e15d37912b93b501cc` | MANA/ETH | 36.84 | amm-fork-thin-pool | curve-pool |
| 289 | `0x4164d2e7ae6d8bc0a633412c189088181df969b7` | sUSD/USDC | 36.32 | amm-fork-thin-pool | curve-pool |
| 290 | `0xe1fbaec91b8a211db901adf5acc5b31f9a988279` | rUSDY/USDC | 36.24 | amm-fork-thin-pool | curve-pool |
| 291 | `0x3c4b6e6e1ea3d4863700d7f76b36b7f3d3f13e3d` | Voyager | 35.95 | unverified-leftover | llama-protocol |
| 292 | `0xabaf76590478f2fe0b396996f55f0b61101e9502` | Tri BTC-Fi | 35.57 | amm-fork-thin-pool | curve-pool |
| 293 | `0x429ccfcca8ee06d2b41daa6ee0e4f0edbb77dfad` | Curve.fi Factory Crypto Pool: mevETH/ETH | 35.18 | amm-fork-thin-pool | curve-pool |
| 294 | `0x0d381fc68487365e90c32c90323352b325e21d23` | AZND/USDC | 34.78 | amm-fork-thin-pool | curve-pool |
| 295 | `0xc3b19502f8c02be75f3f77fd673503520deb51dd` | Curve.fi Factory USD Metapool: msUSD/FRAXBP | 34.12 | amm-fork-thin-pool | curve-pool |
| 296 | `0x43b4fdfd4ff969587185cdb6f0bd875c5fc83f8c` | Curve.fi Factory USD Metapool: Alchemix USD | 34.04 | amm-fork-thin-pool | curve-pool |
| 297 | `0xacdc85afcd8b83eb171affcbe29fad204f6ae45c` | UBQ/ETH | 33.71 | amm-fork-thin-pool | curve-pool |
| 298 | `0xed279fdd11ca84beef15af5d39bb4d4bee23f0ca` | Curve.fi Factory USD Metapool: Liquity | 33.40 | amm-fork-thin-pool | curve-pool |
| 299 | `0xcfeaead4947f0705a14ec42ac3d44129e1ef3ed5` | Notional V3 | 33.13 | unverified-leftover | llama-protocol |
| 300 | `0x85847ef522d78efdbec8afb0045dc7d6982837c3` | PAL/ETH | 32.66 | amm-fork-thin-pool | curve-pool |
| 301 | `0xa1faa113cbe53436df28ff0aee54275c13b40975` | Homora V2 | 30 | unverified-leftover | llama-protocol |
| 302 | `0xff75ced57419bcaebe5f05254983b013b0646ef5` | Cook Finance | 30 | unverified-leftover | llama-protocol |
| 303 | `0xcc4304a31d09258b0029ea7fe63d032f52e44efe` | TrustSwap | 29.89 | unverified-leftover | llama-protocol |
| 304 | `0x7c4e143b23d72e6938e06291f705b5ae3d5c7c7c` | deUSD/USDT | 29.16 | amm-fork-thin-pool | curve-pool |
| 305 | `0x5b692073f141c31384fae55856cfb6cbffe91e60` | Curve.fi Factory Crypto Pool: ibAUD/USDC | 29.02 | amm-fork-thin-pool | curve-pool |
| 306 | `0xe8fcbf3dabc939ea509bff0ecf2c228b6ded7de0` | crvUSD/WETH YB Oraclized Test | 28.34 | amm-fork-thin-pool | curve-pool |
| 307 | `0xfe4a08f22fe65759ba91db2e2cada09b4415b0d7` | Curve.fi Factory Crypto Pool: LFT/ETH | 28.26 | amm-fork-thin-pool | curve-pool |
| 308 | `0x3ee841f47947fefbe510366e4bbb49e145484195` | USR/USDC | 28.08 | amm-fork-thin-pool | curve-pool |
| 309 | `0x949d48eca67b17269629c7194f4b727d4ef9e5d6` | Merit Circle | 26.88 | unverified-leftover | llama-protocol |
| 310 | `0xef9cd7882c067686691b6ff49e650b43afbbcc6b` | FinNexus | 26.82 | unverified-leftover | llama-protocol |
| 311 | `0xd25f2cc6819fbd34641712122397efbaf9b6a6e2` | ebUSD/USDC Pool | 26.76 | amm-fork-thin-pool | curve-pool |
| 312 | `0xc20059e0317de91738d13af027dfc4a50781b066` | SparkLend | 26.11 | unverified-leftover | llama-protocol |
| 313 | `0xf48a252b65ef787bbb1b5c1e0e7f39df159147d4` | EMAUSD/USDC | 25.95 | amm-fork-thin-pool | curve-pool |
| 314 | `0xdd1ad9a21ce722c151a836373babe42c868ce9a4` | Proof of Humanity | 25.55 | unverified-leftover | llama-protocol |
| 315 | `0x9aeb50f542050172359a0e1a25a9933bc8c01259` | Oin Finance | 25.08 | unverified-leftover | llama-protocol |
| 316 | `0x9d65ff81a3c488d585bbfb0bfe3c7707c7917f54` | SSV Network | 24.78 | unverified-leftover | llama-protocol |
| 317 | `0x909e34d3f6124c324ac83dcca84b74398a6fa173` | Panther Protocol | 24.12 | unverified-leftover | llama-protocol |
| 318 | `0x81f17e97b1cea46301fe6728d5619e9db2e7fb2c` | crvUSD/USDT | 22.30 | amm-fork-thin-pool | curve-pool |
| 319 | `0xb3999f658c0391d94a37f7ff328f3fec942bcadc` | Hashflow | 21.49 | unverified-leftover | llama-protocol |
| 320 | `0xab96aa0ee764924f49fbb372f3b4db9c2cb24ea2` | USDLxUSDC | 20.10 | amm-fork-thin-pool | curve-pool |
| 321 | `0x10196c1871e52d2192d1aa675705f096aef089e2` | tCCD/USDT | 20 | amm-fork-thin-pool | curve-pool |
| 322 | `0x92cc36d66e9d739d50673d1f27929a371fb83a67` | WAGMI | 20 | unverified-leftover | llama-protocol |
| 323 | `0xdebf20617708857ebe4f679508e7b7863a8a8eee` | Curve.fi aDAI/aUSDC/aUSDT | 20 | amm-fork-thin-pool | curve-pool |
| 324 | `0xa5f2211b9b8170f694421f2046281775e8468044` | THORSwap | 19.41 | unverified-leftover | llama-protocol |
| 325 | `0xf2c8f52d07ee33d7a7db78cee084a33b40ab4654` | ZAI/USDC | 19 | amm-fork-thin-pool | curve-pool |
| 326 | `0xfa1c09fc8b491b6a4d3ff53a10cad29381b3f949` | Falcon Finance | 18.50 | unverified-leftover | llama-protocol |
| 327 | `0x5f0985a8aad85e82fd592a23cc0501e4345fb18c` | ABDS USDT | 17.76 | amm-fork-thin-pool | curve-pool |
| 328 | `0x6e314039f4c56000f4ebb3a7854a84cc6225fb92` | Curve.fi Factory Crypto Pool: BTRFLY/ETH | 17.50 | amm-fork-thin-pool | curve-pool |
| 329 | `0x482df7483a52496f4c65ab499966dfcdf4ddfdbc` | Ledgity Yield | 17.23 | unverified-leftover | llama-protocol |
| 330 | `0x5378c23f4cf85fc28fddea16153cf9213aefe9be` | instETH/stETH | 17.22 | amm-fork-thin-pool | curve-pool |
| 331 | `0x78e99ed484605ba66ca9804b0b6fe700242c85bc` | Major-token holder | 16.71 | unverified-leftover | holder |
| 332 | `0x5983b89fa184f14917013b9c3062afd9434c5b03` | M0 | 16.70 | unverified-leftover | llama-protocol |
| 333 | `0xc77103e44914a9e5e30b9f58cd48e990b22fb587` | Curve.fi Factory Crypto Pool: liq_ETH_AAVE | 16.69 | amm-fork-thin-pool | curve-pool |
| 334 | `0xdf9015472ea23e3bea6fbd6092915f9ed6980a99` | revPool | 16.19 | amm-fork-thin-pool | curve-pool |
| 335 | `0x6dea81c8171d0ba574754ef6f8b412f2ed88c54d` | Liquity V1 | 15.57 | unverified-leftover | llama-protocol |
| 336 | `0xa9335f627ba9d80d9dda76b5fea03dd885404132` | sUSDE/USDT | 15.15 | amm-fork-thin-pool | curve-pool |
| 337 | `0xdcafd1914afdbc5788b701f47283caeeaa5fbaed` | WETH/AMPH/wUSDA | 14.76 | amm-fork-thin-pool | curve-pool |
| 338 | `0xf01627c39b427654dc984571b3ae32e4136813ec` | USDT/USDN | 14.32 | amm-fork-thin-pool | curve-pool |
| 339 | `0x9804c30875127246ac92d72d5cdf0630aa356861` | YUSD/USDC | 13.90 | amm-fork-thin-pool | curve-pool |
| 340 | `0x9a6f2ffa30cddbb6156b98ac88a546e81205f6ba` | Curve.fi Factory Plain Pool: LETH/WETH | 13.36 | amm-fork-thin-pool | curve-pool |
| 341 | `0xf6f7a475b44a8296149d9a32b330c1b1b4b98ff4` | AUDD/USDT/WBTC | 13.19 | amm-fork-thin-pool | curve-pool |
| 342 | `0x4c19596f5aaff459fa38b0f7ed92f11ae6543784` | TrueFi | 13 | unverified-leftover | llama-protocol |
| 343 | `0xc52c326331e9ce41f04484d3b5e5648158028804` | Unizen | 13 | unverified-leftover | llama-protocol |
| 344 | `0x611a95bf3cc0ef593f22c4e4d8eb4d6c937e006c` | Curve.fi Factory Crypto Pool: jpyusd | 12.21 | amm-fork-thin-pool | curve-pool |
| 345 | `0xe97b3271f812ff43522312705dbe58c8c6077b5f` | USDA-USDC | 12 | amm-fork-thin-pool | curve-pool |
| 346 | `0xd6a9ad1ca9a5239889118c3b7bc59f90a0e65e15` | USD69/USDC | 11.97 | amm-fork-thin-pool | curve-pool |
| 347 | `0x8248270620aa532e4d64316017be5e873e37cc09` | DevvE | 11.80 | unverified-leftover | llama-protocol |
| 348 | `0x2af0a09b3421240f32953fffb13d2d2b8d24fbae` | Curve.fi Factory Crypto Pool: INV/ETH | 11.67 | amm-fork-thin-pool | curve-pool |
| 349 | `0xeb0265938c1190ab4e3e1f6583bc956df47c0f93` | Curve.fi Factory Crypto Pool: ibJPY/USDC | 11.63 | amm-fork-thin-pool | curve-pool |
| 350 | `0x5d898fd41875b14c1781fb497aecab8e9b24dfc9` | Curve.fi Factory Crypto Pool: CXD/ETH | 11.18 | amm-fork-thin-pool | curve-pool |
| 351 | `0x0418205c250a5eb1f4ecaab5f7c76c08b57b5aaf` | shezUSD/USDC | 10.79 | amm-fork-thin-pool | curve-pool |
| 352 | `0xf1dba688f6055d8a9ca2521c8e5324cedfb50e3b` | ShezETH/ETH | 10.34 | amm-fork-thin-pool | curve-pool |
| 353 | `0x0e29e5abbb5fd88e28b2d355774e73bd47de3bcd` | Hakka Finance | 10 | unverified-leftover | llama-protocol |
| 354 | `0x66fd8de541c0594b4dccdfc13bf3a390e50d3afd` | Turtle Club | 10 | unverified-leftover | llama-protocol |
| 355 | `0x6e2a43be0b1d33b726f0ca3b8de60b3482b8b050` | Arkham Exchange | 10 | unverified-leftover | llama-protocol |
| 356 | `0x888888435fde8e7d4c54cab67f206e4199454c60` | DFX V3 | 10 | unverified-leftover | llama-protocol |
| 357 | `0xa1a5a5bdb258a951786285d74efe72882ded7574` | Curve.fi Factory Crypto Pool: WTK/USDT | 10 | amm-fork-thin-pool | curve-pool |
| 358 | `0xa849eaae994fb86afa73382e9bd88c2b6b18dc71` | MVL Staking | 10 | unverified-leftover | llama-protocol |
| 359 | `0xf17a3fe536f8f7847f1385ec1bc967b2ca9cae8d` | Alongside | 10 | unverified-leftover | llama-protocol |
| 360 | `0x1631d0e588d475cee4be0f51b7410daaaabd7034` | Curve.fi Factory Crypto Pool: ETH/FRAX | 9.93 | amm-fork-thin-pool | curve-pool |
| 361 | `0x46f27bd3ec8f8d602f7ce85d312f4387fbda7b16` | Curve liUSD-1w/USDC | 9.83 | amm-fork-thin-pool | curve-pool |
| 362 | `0x154b0ecd38078819084e449ea1a657728fd37e43` | Curve.fi Factory Crypto Pool: MG/USDC | 8.89 | amm-fork-thin-pool | curve-pool |
| 363 | `0x19a0ca9a0dc2a5034f47dcc164169cffd7ed2410` | Curve.fi Factory Crypto Pool: ARTH/ETH | 8.83 | amm-fork-thin-pool | curve-pool |
| 364 | `0x13366f833e3d39e50db46687e4b39e56e1562fe6` | STOZ/USDC | 8.81 | amm-fork-thin-pool | curve-pool |
| 365 | `0x785af85cceb3ba1369925c5b43e90026343fc0bb` | Curve.fi Factory Pool: jpeth | 8.51 | amm-fork-thin-pool | curve-pool |
| 366 | `0x0aa29ef252c007577938dbc048ed7529d25f9d36` | hihikiki | 8.35 | amm-fork-thin-pool | curve-pool |
| 367 | `0xadb6851875b7496e3d565b754d8a79508480a203` | BOLD/USDC Pool | 8.20 | amm-fork-thin-pool | curve-pool |
| 368 | `0x423f4e6138e475d85cf7ea071ac92097ed631eea` | Pond0x | 8.01 | unverified-leftover | llama-protocol |
| 369 | `0xc26d714c76e98ec65d26a9cdc749734ba6ca03d2` | nBASIS/USDC | 7.96 | amm-fork-thin-pool | curve-pool |
| 370 | `0xc4ad0f4a231e8071dcccbbadfcdf78935d7c41c3` | AID/USDC | 7.74 | amm-fork-thin-pool | curve-pool |
| 371 | `0x5b3ba844b3859f56524e99ae54857b36c8ae3efe` | TriLDO | 7.57 | amm-fork-thin-pool | curve-pool |
| 372 | `0xfa883807fdf5d3f5c408f1f6d78707753af1ffe7` | AUSD/USDC | 7.45 | amm-fork-thin-pool | curve-pool |
| 373 | `0x5197fbe1a86679ff1360e27862bf88b0c5119bd8` | BITPIF | 7.33 | unverified-leftover | llama-protocol |
| 374 | `0xef04f337fcb2ea220b6e8db5edbe2d774837581c` | Curve.fi Factory Crypto Pool: ibKRW/USDC | 7.22 | amm-fork-thin-pool | curve-pool |
| 375 | `0x97130cc28e99d13ce1ae41d022268b5cc7409cda` | Curve.fi Factory Crypto Pool: RaeX | 7.14 | amm-fork-thin-pool | curve-pool |
| 376 | `0xfd9f287d1fb94c750601fabd89739bab9260f6e4` | Swdc/usdt | 7.14 | amm-fork-thin-pool | curve-pool |
| 377 | `0x643c4e15d7d62ad0abec4a9bd4b001aa3ef52d66` | Maple | 7.10 | unverified-leftover | llama-protocol |
| 378 | `0x3081cffcac989cb6f3af01dc5bc309d70f6c2884` | Curve.fi Factory Crypto Pool: IMK/wETH | 7.05 | amm-fork-thin-pool | curve-pool |
| 379 | `0xf8076eccbef6b3c6f3e96a1a2f506ed820a228f9` | EIGEN/ETH | 6.93 | amm-fork-thin-pool | curve-pool |
| 380 | `0x675efebfcf76d569c56f6021b12e9418932a602f` | usd | 6.82 | amm-fork-thin-pool | curve-pool |
| 381 | `0x2d9bf9c1befd77c094461df615bdbe905895f7c6` | USDtb-USDe | 6.71 | amm-fork-thin-pool | curve-pool |
| 382 | `0xc8eb2cf2f792f77af0cd9e203305a585e588179d` | pxETH/wETH | 6.62 | amm-fork-thin-pool | curve-pool |
| 383 | `0xc17c30e98541188614df99239cabd40280810ca3` | EverRise | 6.36 | unverified-leftover | llama-protocol |
| 384 | `0x03a2d569458fc51677af374a56f029b885b03cd0` | azGNIT/USDC | 6.29 | amm-fork-thin-pool | curve-pool |
| 385 | `0xc5b571e500a14bee10159a5a65de8c344213facb` | MTETH/WETH | 6.10 | amm-fork-thin-pool | curve-pool |
| 386 | `0x82a605d6d9114f4ad6d5ee461027477eeed31e34` | Sensay | 6 | unverified-leftover | llama-protocol |
| 387 | `0x73e4bec1a111869f395cbb24f6676826bf86d905` | swBTC/wBTC | 5.34 | amm-fork-thin-pool | curve-pool |
| 388 | `0xb0076de78dc50581770bba1d211ddc0ad4f2a241` | edgeX Bridge | 5.30 | unverified-leftover | llama-protocol |
| 389 | `0x88c885e1f54d206f5dbb88a735d84a70a170f7f0` | micunt global pool  | 5.23 | amm-fork-thin-pool | curve-pool |
| 390 | `0x2f0e2d1023fd3757aa58be7020b0fc58c6a45187` | Curve.fi Factory Crypto Pool: PAIR_ETH_AAVE | 5.22 | amm-fork-thin-pool | curve-pool |
| 391 | `0xe07bde9eb53deffa979dae36882014b758111a78` | Curve.fi Factory Crypto Pool: CADC/USDC | 5.03 | amm-fork-thin-pool | curve-pool |
| 392 | `0x39b46b212bdf15b42b166779b9d1787a68b9d0c3` | Dypius | 5 | unverified-leftover | llama-protocol |
| 393 | `0xcdfe5620a0ae057f580f1b0835740248cceae161` | stTEST2 | 5 | amm-fork-thin-pool | curve-pool |
| 394 | `0xde293e87ddcf51f944214388d21612e3059f1c45` | lrUSD/USDC | 5 | amm-fork-thin-pool | curve-pool |
| 395 | `0xf0c73c7acfbebb7f52564d55fb9b65fafba88a98` | LUSD/USDC | 5 | amm-fork-thin-pool | curve-pool |
| 396 | `0xeac874aed7761460dd4c89778ba6db7d320911a8` | eETH/ETH | 4.97 | amm-fork-thin-pool | curve-pool |
| 397 | `0x6bd67f8d68cf404105f89c6791c63fc8529f2f22` | USDT/Prospective | 4.76 | amm-fork-thin-pool | curve-pool |
| 398 | `0x64aa3364f17a4d01c6f1751fd97c2bd3d7e7f1d5` | Cooler Loans | 4.66 | unverified-leftover | llama-protocol |
| 399 | `0xf514a54693db2f3b4c43f78088d361b3f3a317a9` | Curve.fi Factory Crypto Pool: GBPT / USDC | 4.53 | amm-fork-thin-pool | curve-pool |
| 400 | `0xf8db2accdef8e7a26b0e65c3980adc8ce11671a4` | FDUSD/USDe | 4.34 | amm-fork-thin-pool | curve-pool |
| 401 | `0xb3341ca63b6cecf1e1a0d1a99bf0587f4c305652` | BLOOM/USDC | 4.32 | amm-fork-thin-pool | curve-pool |
| 402 | `0x1c14723fa5c8b20f5afd8ef07b6d6c877e0222cd` | Monolith testUSD/USDC | 4.23 | amm-fork-thin-pool | curve-pool |
| 403 | `0x6819068dc6d1afe3120454a3519ec1fa1a32fbd1` | aptUSD/USDC | 4.20 | amm-fork-thin-pool | curve-pool |
| 404 | `0x375349f7704de4acecdba864920e77b0bb5ce1e8` | STUSD/USDC | 4.19 | amm-fork-thin-pool | curve-pool |
| 405 | `0xb92b054b9cc33685e7f8c3f85177c4b6dc061391` | weETHs/WETH | 4.17 | amm-fork-thin-pool | curve-pool |
| 406 | `0xd6f6fa524d4c9f7a5cbc8fb9145a70d8d7ed6073` | Curve.fi Factory Crypto Pool: USDT/QUINTA | 4.06 | amm-fork-thin-pool | curve-pool |
| 407 | `0xd932bf031d44279ec6400c1c9635b7687109eb9b` | alqUSD/USDC | 4.01 | amm-fork-thin-pool | curve-pool |
| 408 | `0x4c022d12229460d10ddda4c99572bdefafb8d15b` | LUSD/USDC | 4 | amm-fork-thin-pool | curve-pool |
| 409 | `0x5f7e61d773eabb31df89720f0501abef0f2320f0` | stTEST2 | 4 | amm-fork-thin-pool | curve-pool |
| 410 | `0xd1419e4d76e74d3b4d8a224f3a34118622fb4df4` | EIGEN/WETH | 3.85 | amm-fork-thin-pool | curve-pool |
| 411 | `0x3dbdb2656f36a1b19971d798dd59f19440eda894` | RestakeFi rstETH/stETH | 3.80 | amm-fork-thin-pool | curve-pool |
| 412 | `0x256fbda404b96a283b1ae851b465d4b9601c25a6` | SPOT/USDC | 3.51 | amm-fork-thin-pool | curve-pool |
| 413 | `0x4e67db19044549ff420860834c91b45bad298722` | Zipcoin | 3.30 | unverified-leftover | llama-protocol |
| 414 | `0x249ca82617ec3dfb2589c4c17ab7ec9765350a18` | Verse | 3.27 | unverified-leftover | llama-protocol |
| 415 | `0xe1c121be7303f4760410b0c42c2141653bb57244` | Tri-LINK | 3.23 | amm-fork-thin-pool | curve-pool |
| 416 | `0x7e050cf658777cc1da4a4508e79d71859044b60e` | Curve.fi Factory Crypto Pool: JPEG/ETH | 3.15 | amm-fork-thin-pool | curve-pool |
| 417 | `0x349d27e78b3267180279687bf82cae3bd78f41e1` | IDRS/USDC | 3.02 | amm-fork-thin-pool | curve-pool |
| 418 | `0x2c7827010121aae14200e839f6c89913457ed34c` | WETH/Prospective | 3.01 | amm-fork-thin-pool | curve-pool |
| 419 | `0x00a23a5257cdc7f4b79b2d49a4689a1abd6dd415` | lrUSD/USDC | 3 | amm-fork-thin-pool | curve-pool |
| 420 | `0x429881672b9ae42b8eba0e26cd9c73711b891ca5` | Pickle | 3 | unverified-leftover | llama-protocol |
| 421 | `0xdd0f28e19c1780eb6396170735d45153d261490d` | Gauntlet USDC Prime | 3 | clone-erc4626-inflation | morpho-vault |
| 422 | `0x06936efcaaab49af1c8b9ce3ac8bd85aabef3a3e` | USD TRADE | 2.82 | amm-fork-thin-pool | curve-pool |
| 423 | `0x485d17a6f1b8780392d53d64751824253011a260` | Timewarp | 2.79 | unverified-leftover | llama-protocol |
| 424 | `0x18042f2fab99af6e374e4f5f3c2218102993cc23` | yStable | 2.56 | amm-fork-thin-pool | curve-pool |
| 425 | `0x86fecb2f93c537397f9dfd894bcf6a95fa87a25e` | sfrxUSD/USDe | 2.54 | amm-fork-thin-pool | curve-pool |
| 426 | `0xf6e29d74b906d26c564c4d12322abd602ae160a2` | jujukiki | 2.51 | amm-fork-thin-pool | curve-pool |
| 427 | `0x41ea3d7ef4375672f631be72cabc12d2d1c9f11a` | DOVX | 2.43 | amm-fork-thin-pool | curve-pool |
| 428 | `0x6d6e0a7871d614ab201bbace79d4be9b4d74007c` | QUA/USDT | 2.37 | amm-fork-thin-pool | curve-pool |
| 429 | `0x56070d3e700d66733ee530bd2c2c7df88ac1147c` | USDT/$ | 2.19 | amm-fork-thin-pool | curve-pool |
| 430 | `0xeb593fe90591923fddd97f2e5fcb1a14ce656e5d` | wA7A5/USDT | 2.19 | amm-fork-thin-pool | curve-pool |
| 431 | `0xaf693ade4596d45ac294ceab920df0943afb54d9` | Curve.fi Factory Crypto Pool: RPL/ETH | 2.17 | amm-fork-thin-pool | curve-pool |
| 432 | `0x5fc00b07a8f21de2cd312cdac73e13b5e9a14b1c` | test | 2.02 | amm-fork-thin-pool | curve-pool |
| 433 | `0x159a866f13f3931e256946ad7d921d18acbc599f` | Add gauge reward test pool | 2 | amm-fork-thin-pool | curve-pool |
| 434 | `0x584bc13c7d411c00c01a62e8019472de68768430` | Hegic | 2 | unverified-leftover | llama-protocol |
| 435 | `0x782115c863a05abf8795df377d89aad1aadf4dfa` | Curve.fi Factory Crypto Pool: CNC/ETH | 2 | amm-fork-thin-pool | curve-pool |
| 436 | `0x8273a8578ebf1818541c49f034d896616657b8ce` | USDeAD/USDC DeADStablePool ETH | 2 | amm-fork-thin-pool | curve-pool |
| 437 | `0xe33db3b492b1e6df86377ca172c7e198d34ac122` | PUSD/USDC | 2 | amm-fork-thin-pool | curve-pool |
| 438 | `0xb64aeaa56d6aa47c21ca9c829058ff9754c90a8a` | USDX/USDC | 1.85 | amm-fork-thin-pool | curve-pool |
| 439 | `0x02d7f419d731f718bdb22a3b03874c600bec3a40` | Curve.fi Factory Crypto Pool: QUINTA ECO  | 1.78 | amm-fork-thin-pool | curve-pool |
| 440 | `0xd18712370f840b1563d85ea6bd221f53d766ffa8` | Curve.fi Factory Crypto Pool: Curve Test/ETH | 1.69 | amm-fork-thin-pool | curve-pool |
| 441 | `0xc1ea9d1346d70e9eb16b392afbedc0e0e06c3fd3` | USDC/QUINTA/AIOZ | 1.61 | amm-fork-thin-pool | curve-pool |
| 442 | `0x6df0d77f0496ce44e72d695943950d8641fca5cf` | Curve.fi Factory Crypto Pool: ibCHF/USDC | 1.59 | amm-fork-thin-pool | curve-pool |
| 443 | `0x59a06b97b2d566b9dee2a368eac8787cfa57f95d` | sUSD/USDe | 1.58 | amm-fork-thin-pool | curve-pool |
| 444 | `0x35e78b3982e87ecfd5b3f3265b601c046cdbe232` | SideShift | 1.44 | unverified-leftover | llama-protocol |
| 445 | `0x771c91e699b4b23420de3f81de2aa38c4041632b` | USDU/USDC | 1.36 | amm-fork-thin-pool | curve-pool |
| 446 | `0xb5555ab6cb4f37f833f8fbd483b70ccdd4601057` | Stable Yield | 1.33 | amm-fork-thin-pool | curve-pool |
| 447 | `0x7e96ae239b9328acb57af401d1f2b6cf5b4ab8de` | Curve.fi Factory Crypto Pool: MMX/USDT | 1.31 | amm-fork-thin-pool | curve-pool |
| 448 | `0x9c9bc7e9f54155760fb03d406c8813453f284388` | crvUSD/WETH YB Oraclized Test v2 | 1.29 | amm-fork-thin-pool | curve-pool |
| 449 | `0xb78af33f29cee29403657bdb56cbccbc1c67769b` | BTC.b/WBTC | 1.09 | amm-fork-thin-pool | curve-pool |
| 450 | `0xc9f39993cf05f7442dd56ac2b87484c051ffdb5a` | Curve.fi Factory Crypto Pool: Spectra-PT/IBT | 1.08 | amm-fork-thin-pool | curve-pool |
| 451 | `0xb547eb5cebb2218a54b1839f3952d7ccc61a6997` | stusd | 1.06 | amm-fork-thin-pool | curve-pool |
| 452 | `0x054d3af2825a5cd8e4ef5dc28bc368efd396c216` | Tri-AAVE | 1.04 | amm-fork-thin-pool | curve-pool |
| 453 | `0x85de3add465a219ee25e04d22c39ab027cf5c12e` | ezETH/WETH | 1.04 | amm-fork-thin-pool | curve-pool |
| 454 | `0x2c861290d674783e5434d4de06e41470ca1a706b` | PUSD/USDT | 1 | amm-fork-thin-pool | curve-pool |
| 455 | `0x2edf094db69d6dcd487f1b3db9febe2eec0dd4c5` | ZeroSwap | 1 | unverified-leftover | llama-protocol |
| 456 | `0xc011a73ee8576fb46f5e1c5751ca3b9fe0af2a6f` | Synthetix V3 | 1 | unverified-leftover | llama-protocol |
| 457 | `0xcf3c8be2e2c42331da80ef210e9b1b307c03d36a` | Bepro Network | 1 | unverified-leftover | llama-protocol |
| 458 | `0xeea33df43acc023fe9a454fe87bb380b21eb6d46` | USDC/thUSD | 1 | amm-fork-thin-pool | curve-pool |
| 459 | `0xf0db65d17e30a966c2ae6a21f6bba71cea6e9754` | Lombard LBTC | 1 | unverified-leftover | llama-protocol |
| 460 | `0xfca116b6dd29856cec9e7e5d0f6dc3464b4568d2` | PUSD/DAI | 1 | amm-fork-thin-pool | curve-pool |
| 461 | `0x0f2f4d68308db60d36268a602ef273421a227021` | uniETH/ETH | 0.94 | amm-fork-thin-pool | curve-pool |
| 462 | `0x087a96c2961dbe228dd1dca45fa7c6e8738f3fa7` | TriCrypto-crvUSD | 0.93 | amm-fork-thin-pool | curve-pool |
| 463 | `0x9ed7a47cdee1a197b338706145735b62778979cf` | Curve.fi Factory Crypto Pool: Spectra-PT/IBT | 0.93 | amm-fork-thin-pool | curve-pool |
| 464 | `0x6c03b78ac79075a52249fdb4657924226c8b0003` | MkrGld Pennyweight'd | 0.92 | amm-fork-thin-pool | curve-pool |
| 465 | `0xaf4264916b467e2c9c8acf07acc22b9edddadf33` | Curve.fi Factory Crypto Pool: COIL/FRAXBP | 0.89 | amm-fork-thin-pool | curve-pool |
| 466 | `0xf1005ac82e89de676449525c3cb86959216864c1` | SolvBTC/WBTC | 0.89 | amm-fork-thin-pool | curve-pool |
| 467 | `0xfcca47ddd4336f08835005d912124b472ed29448` | ynUSDx/USD | 0.89 | amm-fork-thin-pool | curve-pool |
| 468 | `0xb2c57d651db0fccc96cabda11191df25e05b88b6` | Curve.fi Factory Plain Pool: ZeroLiquid zETH/WETH | 0.85 | amm-fork-thin-pool | curve-pool |
| 469 | `0xdaa3ab22cc31b89fca53cd97321a6957ec8b71c7` | wETH/SKK/SPX | 0.83 | amm-fork-thin-pool | curve-pool |
| 470 | `0x138f59a485a058d4fc449cea7a3a080f9af467f1` | Curve liUSD-8w/USDC | 0.82 | amm-fork-thin-pool | curve-pool |
| 471 | `0xddbdcebb989b1ef804338d6c9a902f91c2738936` | Curve.fi Factory Crypto Pool: RAREPEPE | 0.82 | amm-fork-thin-pool | curve-pool |
| 472 | `0xa551f34fc641f76f17498840c0abfec608410065` | Curve.fi Factory Crypto Pool: GOXC/USDT | 0.81 | amm-fork-thin-pool | curve-pool |
| 473 | `0xf38fafd8f396831999434c2863f9ec715ebb2e9c` | USDC/AIDaUSDC | 0.78 | amm-fork-thin-pool | curve-pool |
| 474 | `0x0093c860559fe7f6701e865744a267c0e9c21b02` | USDC/MAPU | 0.76 | amm-fork-thin-pool | curve-pool |
| 475 | `0x06cf5f9b93e9fcfdb33d6b3791eb152567cd8d36` | USPD/USDC | 0.73 | amm-fork-thin-pool | curve-pool |
| 476 | `0xfb76256401233fbb730b60b31f7976888ab7b735` | ckONE/WETH | 0.73 | amm-fork-thin-pool | curve-pool |
| 477 | `0xac72ed3390cfb7bf0f101262648a6afc2bef99c1` | Major-token holder | 0.71 | unverified-leftover | holder |
| 478 | `0x4d19e7fd118fd751fea7c0324d7e7b0a3d05eba4` | Curve.fi Factory Crypto Pool: ZARP/USDC | 0.67 | amm-fork-thin-pool | curve-pool |
| 479 | `0x68984391a8ce6203067ee65ff7eed38c7e0d2d88` | USDe/USDa | 0.66 | amm-fork-thin-pool | curve-pool |
| 480 | `0x7c0316c925e12ebfc55e0f325794b43ead425157` | Curve.fi Factory Pool: frxETH | 0.62 | amm-fork-thin-pool | curve-pool |
| 481 | `0x8595643f69d651817968d37d03e6f7d0c0e22949` | WEO/USDT | 0.59 | amm-fork-thin-pool | curve-pool |
| 482 | `0xee0dcaf26aa271ff18bb9b9b282620a7ce79f6ba` | Curve.fi Factory Crypto Pool: ETH/BTC | 0.59 | amm-fork-thin-pool | curve-pool |
| 483 | `0x96a3f551c99797998dc33e2d816d567db61ee1c2` | Curve.fi Factory Crypto Pool: RAI/USDC | 0.55 | amm-fork-thin-pool | curve-pool |
| 484 | `0x33b831beb7b7870b758850442eb59b5ee9f10543` | UUUUS | 0.52 | amm-fork-thin-pool | curve-pool |
| 485 | `0xfeb0784f5d0940686143b3a025af731ee6a81197` | Curve.fi Factory Crypto Pool: DUCK/USDT | 0.52 | amm-fork-thin-pool | curve-pool |
| 486 | `0x55db32b79de03b2b3093063407581c98f51d37d1` | USST/USDC | 0.51 | amm-fork-thin-pool | curve-pool |
| 487 | `0xc43c6bfeda065fe2c4c11765bf838789bd0bb5de` | RedStone Oracles | 0.50 | unverified-leftover | llama-protocol |
| 488 | `0xc73b0328bd40ea35aad34d0fdc1dbe64c4f9c59f` | tacETH | 0.50 | amm-fork-thin-pool | curve-pool |
| 489 | `0x6ee1955afb64146b126162b4ff018db1eb8f08c3` | ZAI/USDC | 0.49 | amm-fork-thin-pool | curve-pool |
| 490 | `0x8b0fb150fba4fc25cd4f6f5bd8a8f6944ad65af0` | sxETH/ETH | 0.47 | amm-fork-thin-pool | curve-pool |
| 491 | `0x6bd88c57523bf138a19b263e8ebc8661c836b171` | INV/WETH | 0.46 | amm-fork-thin-pool | curve-pool |
| 492 | `0xf03bd3cfe85f00bf5819ac20f0870ce8a8d1f0d8` | Curve.fi Factory Plain Pool: Sharedstake ETH/vETH2 | 0.44 | amm-fork-thin-pool | curve-pool |
| 493 | `0x5114f86027d4c9a509cba072b8135a171402c6d5` | Curve.fi Factory Crypto Pool: UNBNK/ETH | 0.43 | amm-fork-thin-pool | curve-pool |
| 494 | `0x7b707fe05b490b5f334432e345f1c23c72d3f464` | crv/q/gtec/grd/ibbt/real/usde/s | 0.42 | amm-fork-thin-pool | curve-pool |
| 495 | `0xe6d732379793ba0ebfb83028d4147b92b86fe6b8` | Astral Ether Stablepool | 0.42 | amm-fork-thin-pool | curve-pool |
| 496 | `0x181a7464554e68333193a71719eb164e0db7c038` | TrustProtocol.io XBEN/WETH/USDT | 0.40 | amm-fork-thin-pool | curve-pool |
| 497 | `0x0410a86e94e36bde78ccb97ed6826ce4834db400` | 41PU50C_TEST | 0.39 | amm-fork-thin-pool | curve-pool |
| 498 | `0x184f3fed33d4194a5603c14481241bd089268e4b` |  USAT/USDT | 0.39 | amm-fork-thin-pool | curve-pool |
| 499 | `0xb51368d4c52583b36007acaf62053c237ba3bac6` | wETH/QUINTA/iBBT | 0.38 | amm-fork-thin-pool | curve-pool |
| 500 | `0x1776e1f26f98b1a5df9cd347953a26dd3cb46671` | Erasure | 0.34 | unverified-leftover | llama-protocol |
