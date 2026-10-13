/**
 * IP allow-lists for the proxy's /admin gate: IPv4 and IPv6 addresses and CIDR ranges
 * (`10.0.0.0/8`, `2001:db8::/32`, a bare address being its own /32 or /128), and the client
 * address a request's headers name. Pure, so the proxy's decision is a unit test.
 */
export interface CidrRange {
  family: 4 | 6;
  /** The network address as a bigint, masked. */
  network: bigint;
  prefix: number;
}

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
const HEX_GROUP = /^[0-9a-f]{1,4}$/i;

/** The 32-bit value of an IPv4 address, or null. */
export function parseIpv4(text: string): bigint | null {
  const match = IPV4.exec(text.trim());
  if (match === null) return null;
  let value = 0n;
  for (const part of match.slice(1, 5)) {
    const octet = Number(part);
    if (octet > 255) return null;
    value = (value << 8n) | BigInt(octet);
  }
  return value;
}

/** The 128-bit value of an IPv6 address (with `::` and an embedded IPv4 tail), or null. */
export function parseIpv6(text: string): bigint | null {
  let value = text.trim();
  const zone = value.indexOf("%");
  if (zone !== -1) value = value.slice(0, zone);
  if (value.startsWith("[") && value.endsWith("]")) value = value.slice(1, -1);
  if (value === "" || value.includes(":::")) return null;
  const halves = value.split("::");
  if (halves.length > 2) return null;
  const groups = (part: string): string[] | null => {
    if (part === "") return [];
    const items = part.split(":");
    const last = items[items.length - 1] as string;
    if (last.includes(".")) {
      const v4 = parseIpv4(last);
      if (v4 === null) return null;
      items.pop();
      items.push(((v4 >> 16n) & 0xffffn).toString(16), (v4 & 0xffffn).toString(16));
    }
    return items.every((item) => HEX_GROUP.test(item)) ? items : null;
  };
  const head = groups(halves[0] as string);
  const tail = halves.length === 2 ? groups(halves[1] as string) : [];
  if (head === null || tail === null) return null;
  const missing = 8 - head.length - tail.length;
  if (halves.length === 2 ? missing < 1 : missing !== 0) return null;
  const all = [...head, ...Array<string>(halves.length === 2 ? missing : 0).fill("0"), ...tail];
  let result = 0n;
  for (const group of all) result = (result << 16n) | BigInt(parseInt(group, 16));
  return result;
}

/** An address of either family with its bit width, or null. */
export function parseIp(text: string): { family: 4 | 6; value: bigint } | null {
  const v4 = parseIpv4(text);
  if (v4 !== null) return { family: 4, value: v4 };
  const v6 = parseIpv6(text);
  if (v6 === null) return null;
  // An IPv4-mapped IPv6 address (::ffff:a.b.c.d) is the IPv4 address it maps.
  if (v6 >> 32n === 0xffffn) return { family: 4, value: v6 & 0xffffffffn };
  return { family: 6, value: v6 };
}

function mask(family: 4 | 6, prefix: number): bigint {
  const width = family === 4 ? 32 : 128;
  if (prefix === 0) return 0n;
  return ((1n << BigInt(width)) - 1n) ^ ((1n << BigInt(width - prefix)) - 1n);
}

/** `a.b.c.d/n`, `x::y/n`, or a bare address; null when it is not one. */
export function parseCidr(text: string): CidrRange | null {
  const [address, prefixText, extra] = text.trim().split("/");
  if (address === undefined || extra !== undefined) return null;
  const ip = parseIp(address);
  if (ip === null) return null;
  const width = ip.family === 4 ? 32 : 128;
  let prefix = width;
  if (prefixText !== undefined) {
    if (!/^\d{1,3}$/.test(prefixText)) return null;
    prefix = Number(prefixText);
    if (prefix > width) return null;
  }
  return { family: ip.family, network: ip.value & mask(ip.family, prefix), prefix };
}

/** Every entry parsed; an entry that is not an address or a range is reported by text. */
export function parseAllowList(entries: readonly string[]): {
  ranges: CidrRange[];
  invalid: string[];
} {
  const ranges: CidrRange[] = [];
  const invalid: string[] = [];
  for (const entry of entries) {
    const range = parseCidr(entry);
    if (range === null) invalid.push(entry);
    else ranges.push(range);
  }
  return { ranges, invalid };
}

/** True when the address is inside one of the ranges; a null address matches nothing. */
export function ipInAllowList(ip: string | null, ranges: readonly CidrRange[]): boolean {
  if (ip === null) return false;
  const parsed = parseIp(ip);
  if (parsed === null) return false;
  return ranges.some(
    (range) =>
      range.family === parsed.family &&
      (parsed.value & mask(range.family, range.prefix)) === range.network,
  );
}

export interface ClientIpOptions {
  /** Read the proxy's headers (CW_WEB_TRUST_FORWARDED_IP): only behind a proxy you control. */
  trustForwardedIp: boolean;
}

/**
 * The client's address as the request's headers name it: `x-real-ip`, else the first hop of
 * `x-forwarded-for`, both only when the deployment trusts its proxy to set them (on Vercel it
 * does; elsewhere the headers are the client's to forge). Otherwise null: Next's proxy has no
 * socket address to fall back on (`NextRequest.ip` went in Next 15).
 */
export function clientIpOf(headers: Headers, options: ClientIpOptions): string | null {
  if (!options.trustForwardedIp) return null;
  const real = headers.get("x-real-ip")?.trim();
  if (real) return real;
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded ? forwarded : null;
}
