# Erigon archive sample

This directory is a config sample for an Erigon 3 archive node. The host is not provisioned, and the image is not pulled by CI.

The node is for read-only historical `eth_getCode`, debug, and trace. It does not send transactions. Leave `EXTERNAL_IP` unset; sync is outbound. Publish the RPC on `127.0.0.1:8545` only.

Pick `--prune.mode=archive` before the first sync. Pruning is irreversible. The datadir needs 2–4 TB of NVMe.

`ARCHIVE_RPC_URL` may point at `http://127.0.0.1:8545` after an operator starts the node themselves. When that variable is unset, historical reads fall back to `ETH_RPC_URL`. The scanner does not probe `debug_traceTransaction` to discover the API, because that call is about 1,000 CU.

The systemd unit has no install target, so it stays disabled.
