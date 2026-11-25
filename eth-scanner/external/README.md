# External suites

These two directories are unmodified git submodules. Their licenses are AGPL-3.0.
Nothing in `eth_scanner` imports them, and their Solidity is not copied into this
package.

| Directory | Upstream | Pin | License |
| --- | --- | --- | --- |
| `erc4626-tests` | https://github.com/a16z/erc4626-tests | `ac485460e014f22807c1ff687e0b4dc3af96ee40` | AGPL-3.0 |
| `crytic-properties` | https://github.com/crytic/properties | `5ea14b813ff296e24b4257ab52a0402360f916f6` | AGPL-3.0 |

Check them out with `git submodule update --init --depth 1`. The unit-test job
does not fetch them. `python -m eth_scanner external-suites` skips a suite whose
marker file is absent, writes a thin MIT adapter under the work directory, and
points Medusa and Echidna at the crytic checkout. Set `ETH_SCANNER_ERC4626_DIR`
or `ETH_SCANNER_CRYTIC_DIR` to use a checkout somewhere else.
