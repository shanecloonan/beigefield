/**
 * Offline whatsabi surface. No signature lookup and no provider.
 * Prints JSON. A missing package prints {"available": false} and exits 0.
 */
const code = process.argv[2] || "";

async function load() {
  const roots = [
    process.env.ETH_SCANNER_WHATSABI_ROOT || "",
    new URL("./node_modules/@shazow/whatsabi/dist/index.js", import.meta.url).pathname,
  ].filter(Boolean);
  try {
    return await import("@shazow/whatsabi");
  } catch {
    for (const root of roots) {
      try {
        return await import(root);
      } catch {
        // try the next location
      }
    }
  }
  return null;
}

const loaded = await load();
if (!loaded) {
  process.stdout.write(JSON.stringify({ available: false }));
  process.exit(0);
}

const api = loaded.whatsabi || loaded;
const selectors = typeof api.selectorsFromBytecode === "function" ? api.selectorsFromBytecode(code) : [];
const abi = typeof api.abiFromBytecode === "function" ? api.abiFromBytecode(code) : [];
const functions = [];
const seen = new Set();
for (const item of abi || []) {
  if (!item || item.type !== "function" || !item.selector) continue;
  const selector = String(item.selector).toLowerCase();
  if (seen.has(selector)) continue;
  seen.add(selector);
  functions.push({
    selector,
    stateMutability: item.stateMutability || (item.payable ? "payable" : ""),
    payable: Boolean(item.payable),
  });
}
for (const selector of selectors || []) {
  const text = String(selector).toLowerCase();
  if (seen.has(text)) continue;
  seen.add(text);
  functions.push({ selector: text, stateMutability: "", payable: false });
}

let proxies = [];
if (api.proxies && typeof api.proxies.proxiesFromBytecode === "function") {
  try {
    proxies = api.proxies.proxiesFromBytecode(code) || [];
  } catch {
    proxies = [];
  }
}

const raw = String(code).toLowerCase().replace(/^0x/, "");
let eip7702 = "";
if (raw.startsWith("ef0100") && raw.length >= 46) {
  eip7702 = "0x" + raw.slice(6, 46);
}

process.stdout.write(JSON.stringify({
  available: true,
  functions: functions.slice(0, 128),
  proxies: (proxies || []).slice(0, 8).map((item) => ({
    name: String(item.name || item.constructor?.name || ""),
    implementation: item.resolvedAddress || item.implementation || "",
  })),
  eip7702,
}));
