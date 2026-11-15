#!/usr/bin/env bash
# Install the four pinned Blend engines. A failed download is logged and
# skipped so the scan loop still starts. Nothing here broadcasts a transaction.
#
# Pins (do not float to "latest"):
#   ityfuzz  nightly-35b7f08962fdd0c2e02df7ef8a43164913d514d9
#   halmos   0.3.3
#   medusa   1.5.1
#   echidna  2.4.0
#
# Binaries land in ${ETH_SCANNER_BIN_DIR:-$HOME/.local/bin}. Halmos is a pip
# package at exactly halmos==0.3.3. Override a path with ETH_SCANNER_*_BIN.

set -u

DEST="${ETH_SCANNER_BIN_DIR:-${HOME}/.local/bin}"
mkdir -p "${DEST}"
case ":${PATH}:" in
  *":${DEST}:"*) ;;
  *) export PATH="${DEST}:${PATH}" ;;
esac

if [ -n "${GITHUB_PATH:-}" ]; then
  echo "${DEST}" >> "${GITHUB_PATH}"
fi

note() { printf 'blend-install: %s\n' "$*"; }

fetch_one() {
  name="$1"
  url="$2"
  bin_name="$3"
  archive="/tmp/${name}-blend.tgz"
  work="/tmp/${name}-blend-unpack"
  rm -rf "${work}"
  mkdir -p "${work}"
  if ! curl -fsSL --retry 3 --retry-delay 2 -o "${archive}" "${url}"; then
    note "${name} download failed — that engine will SKIP"
    return 0
  fi
  if ! tar -xzf "${archive}" -C "${work}"; then
    note "${name} archive unpack failed — that engine will SKIP"
    return 0
  fi
  found="$(find "${work}" -type f -name "${bin_name}" | head -n 1)"
  if [ -z "${found}" ]; then
    note "${name} binary ${bin_name} not in the archive — that engine will SKIP"
    return 0
  fi
  install -m 0755 "${found}" "${DEST}/${bin_name}"
  note "${name} installed ${DEST}/${bin_name}"
}

fetch_one \
  ityfuzz \
  "https://github.com/fuzzland/ityfuzz/releases/download/nightly-35b7f08962fdd0c2e02df7ef8a43164913d514d9/ityfuzz_nightly_linux_amd64.tar.gz" \
  ityfuzz

fetch_one \
  medusa \
  "https://github.com/crytic/medusa/releases/download/v1.5.1/medusa-linux-x64.tar.gz" \
  medusa

fetch_one \
  echidna \
  "https://github.com/crytic/echidna/releases/download/v2.4.0/echidna-2.4.0-x86_64-linux.tar.gz" \
  echidna

if command -v python3 >/dev/null 2>&1; then
  if python3 -m pip install -q "halmos==0.3.3"; then
    note "halmos==0.3.3 installed"
  else
    note "halmos==0.3.3 pip install failed — Halmos will SKIP"
  fi
  # Medusa compiles through crytic-compile. Missing compiler => that engine skips.
  python3 -m pip install -q "crytic-compile==0.3.7" || note "crytic-compile helper missing — Medusa may SKIP"
else
  note "python3 missing — Halmos will SKIP"
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  [ -x "${DEST}/ityfuzz" ] && echo "ETH_SCANNER_ITYFUZZ_BIN=${DEST}/ityfuzz" >> "${GITHUB_ENV}"
  [ -x "${DEST}/medusa" ] && echo "ETH_SCANNER_MEDUSA_BIN=${DEST}/medusa" >> "${GITHUB_ENV}"
  [ -x "${DEST}/echidna" ] && echo "ETH_SCANNER_ECHIDNA_BIN=${DEST}/echidna" >> "${GITHUB_ENV}"
  halmos_path="$(command -v halmos || true)"
  [ -n "${halmos_path}" ] && echo "ETH_SCANNER_HALMOS_BIN=${halmos_path}" >> "${GITHUB_ENV}"
fi

note "versions:"
"${DEST}/ityfuzz" --help 2>&1 | head -n 1 || note "ityfuzz not runnable"
"${DEST}/medusa" --version 2>&1 | head -n 2 || note "medusa not runnable"
"${DEST}/echidna" --version 2>&1 | head -n 2 || note "echidna not runnable"
halmos --version 2>&1 | head -n 2 || note "halmos not runnable"
# Ensemble layers. A failed install is logged. That layer skips at scan time.
# Nothing here broadcasts a transaction.
#
# Extra pins (versions that actually publish an artifact):
#   slither            0.11.6
#   aderyn             0.6.8
#   scribble           eth-scribble 0.7.10  (0.8.x is not on npm)
#   crytic-properties  shallow clone of crytic/properties
#   gambit             1.0.6 linux binary
#   foundry            1.9.0 (forge)
#   solc               0.8.28 SMTChecker
#   pyrometer          no GitHub release — left skipped

if command -v python3 >/dev/null 2>&1; then
  python3 -m pip install -q "slither-analyzer==0.11.6" \
    && note "slither-analyzer==0.11.6 installed" \
    || note "slither-analyzer==0.11.6 pip install failed — Slither will SKIP"
fi

if command -v npm >/dev/null 2>&1; then
  if npm install -g --prefix "${HOME}/.local" "eth-scribble@0.7.10" >/tmp/scribble-install.log 2>&1; then
    note "eth-scribble@0.7.10 installed"
  else
    note "eth-scribble@0.7.10 npm install failed — Scribble will SKIP (harness asserts still run)"
  fi
else
  note "npm missing — Scribble will SKIP"
fi

if [ ! -x "${DEST}/gambit" ]; then
  if curl -fsSL --retry 3 --retry-delay 2 -o "${DEST}/gambit" \
      "https://github.com/Certora/gambit/releases/download/v1.0.6/gambit-linux-v1.0.6"; then
    chmod 0755 "${DEST}/gambit"
    note "gambit 1.0.6 installed"
  else
    note "gambit 1.0.6 download failed — Gambit will SKIP"
    rm -f "${DEST}/gambit"
  fi
fi

if [ ! -x "${DEST}/forge" ]; then
  if curl -fsSL --retry 3 --retry-delay 2 -o /tmp/foundry.tgz \
      "https://github.com/foundry-rs/foundry/releases/download/v1.9.0/foundry_v1.9.0_linux_amd64.tar.gz" \
      && tar -xzf /tmp/foundry.tgz -C "${DEST}" forge; then
    chmod 0755 "${DEST}/forge"
    note "forge 1.9.0 installed"
  else
    note "forge 1.9.0 download failed — Foundry invariant will SKIP"
  fi
fi

if [ ! -x "${DEST}/aderyn" ]; then
  if curl -fsSL --retry 3 --retry-delay 2 -o /tmp/aderyn.tar.xz \
      "https://github.com/Cyfrin/aderyn/releases/download/aderyn-v0.6.8/aderyn-x86_64-unknown-linux-gnu.tar.xz" \
      && tar -xJf /tmp/aderyn.tar.xz -C /tmp \
      && install -m 0755 "$(find /tmp -type f -name aderyn | head -n 1)" "${DEST}/aderyn"; then
    note "aderyn 0.6.8 installed"
  else
    note "aderyn 0.6.8 archive not in the release (checksums only) — Aderyn will SKIP"
  fi
fi

PROPS="${ETH_SCANNER_CRYTIC_PROPERTIES:-${HOME}/.local/share/eth-scanner/crytic-properties}"
if [ ! -d "${PROPS}/.git" ]; then
  mkdir -p "$(dirname "${PROPS}")"
  if git clone --depth 1 https://github.com/crytic/properties.git "${PROPS}"; then
    note "crytic/properties cloned at ${PROPS}"
  else
    note "crytic/properties clone failed — pack ids are still instrumented, upstream files SKIP"
  fi
else
  note "crytic/properties already present at ${PROPS}"
fi

if ! command -v solc >/dev/null 2>&1; then
  SOLC_URL="https://github.com/ethereum/solidity/releases/download/v0.8.28/solc-static-linux"
  if curl -fsSL --retry 3 --retry-delay 2 -o "${DEST}/solc" "${SOLC_URL}"; then
    chmod 0755 "${DEST}/solc"
    note "solc 0.8.28 installed for SMTChecker"
  else
    note "solc 0.8.28 download failed — SMTChecker will SKIP"
  fi
else
  note "solc already on PATH — SMTChecker can run"
fi

# nascentxyz/pyrometer has no GitHub release and no tags. Do not invent a binary.
note "pyrometer has no published release — numeric bounds from Pyrometer SKIP until a binary is on PATH"

note "done (missing engines and layers skip at scan time; the loop keeps going)"
exit 0
