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
note "done (missing engines skip at scan time; the loop keeps going)"
exit 0
