import { describe, expect, it } from "vitest";
import {
  clientIpOf,
  ipInAllowList,
  parseAllowList,
  parseCidr,
  parseIp,
  parseIpv4,
  parseIpv6,
} from "./cidr";

describe("parseIpv4 and parseIpv6", () => {
  it("read dotted quads and refuse anything else", () => {
    expect(parseIpv4("10.0.0.1")).toBe(0x0a000001n);
    expect(parseIpv4("255.255.255.255")).toBe(0xffffffffn);
    expect(parseIpv4("256.0.0.1")).toBeNull();
    expect(parseIpv4("10.0.0")).toBeNull();
    expect(parseIpv4("::1")).toBeNull();
  });

  it("read full, compressed, bracketed, zoned and IPv4-mapped IPv6 addresses", () => {
    expect(parseIpv6("::1")).toBe(1n);
    expect(parseIpv6("::")).toBe(0n);
    expect(parseIpv6("2001:db8::1")).toBe(0x20010db8000000000000000000000001n);
    expect(parseIpv6("2001:0db8:0000:0000:0000:0000:0000:0001")).toBe(
      0x20010db8000000000000000000000001n,
    );
    expect(parseIpv6("[2001:db8::1]")).toBe(0x20010db8000000000000000000000001n);
    expect(parseIpv6("fe80::1%eth0")).toBe(0xfe800000000000000000000000000001n);
    expect(parseIpv6("::ffff:10.0.0.1")).toBe(0xffff0a000001n);
    expect(parseIpv6("2001:db8:::1")).toBeNull();
    expect(parseIpv6("2001:db8::1::2")).toBeNull();
    expect(parseIpv6("1:2:3:4:5:6:7:8:9")).toBeNull();
    expect(parseIpv6("1:2:3:4:5:6:7")).toBeNull();
    expect(parseIpv6("gggg::1")).toBeNull();
  });

  it("tells the families apart and unmaps IPv4-mapped addresses", () => {
    expect(parseIp("10.0.0.1")).toEqual({ family: 4, value: 0x0a000001n });
    expect(parseIp("::ffff:10.0.0.1")).toEqual({ family: 4, value: 0x0a000001n });
    expect(parseIp("2001:db8::1")?.family).toBe(6);
    expect(parseIp("nope")).toBeNull();
  });
});

describe("parseCidr and ipInAllowList", () => {
  it("parse ranges and bare addresses, masking the network", () => {
    expect(parseCidr("10.1.2.3/8")).toEqual({ family: 4, network: 0x0a000000n, prefix: 8 });
    expect(parseCidr("10.1.2.3")).toEqual({ family: 4, network: 0x0a010203n, prefix: 32 });
    expect(parseCidr("2001:db8:ffff::1/32")).toEqual({
      family: 6,
      network: 0x20010db8000000000000000000000000n,
      prefix: 32,
    });
    expect(parseCidr("10.0.0.0/33")).toBeNull();
    expect(parseCidr("10.0.0.0/8/1")).toBeNull();
    expect(parseCidr("10.0.0.0/x")).toBeNull();
    expect(parseCidr("")).toBeNull();
  });

  it("answer membership per family, and never for a missing address", () => {
    const { ranges, invalid } = parseAllowList([
      "10.0.0.0/8",
      "2001:db8::/32",
      "203.0.113.7",
      "junk",
    ]);
    expect(invalid).toEqual(["junk"]);
    expect(ranges).toHaveLength(3);
    expect(ipInAllowList("10.255.1.1", ranges)).toBe(true);
    expect(ipInAllowList("11.0.0.1", ranges)).toBe(false);
    expect(ipInAllowList("203.0.113.7", ranges)).toBe(true);
    expect(ipInAllowList("203.0.113.8", ranges)).toBe(false);
    expect(ipInAllowList("2001:db8:1234::9", ranges)).toBe(true);
    expect(ipInAllowList("2001:db9::1", ranges)).toBe(false);
    expect(ipInAllowList("::ffff:10.0.0.1", ranges)).toBe(true);
    expect(ipInAllowList(null, ranges)).toBe(false);
    expect(ipInAllowList("nope", ranges)).toBe(false);
    expect(ipInAllowList("10.0.0.1", [])).toBe(false);
    const everything = parseAllowList(["0.0.0.0/0", "::/0"]).ranges;
    expect(ipInAllowList("198.51.100.1", everything)).toBe(true);
    expect(ipInAllowList("2001:db8::1", everything)).toBe(true);
  });
});

describe("clientIpOf", () => {
  it("reads the proxy headers only when they are trusted, x-real-ip first, then the first hop", () => {
    const headers = new Headers({
      "x-real-ip": " 203.0.113.9 ",
      "x-forwarded-for": "198.51.100.1, 10.0.0.1",
    });
    expect(clientIpOf(headers, { trustForwardedIp: true })).toBe("203.0.113.9");
    expect(clientIpOf(headers, { trustForwardedIp: false })).toBeNull();
    const forwarded = new Headers({ "x-forwarded-for": "198.51.100.1, 10.0.0.1" });
    expect(clientIpOf(forwarded, { trustForwardedIp: true })).toBe("198.51.100.1");
    expect(
      clientIpOf(new Headers({ "x-forwarded-for": " " }), { trustForwardedIp: true }),
    ).toBeNull();
    expect(clientIpOf(new Headers(), { trustForwardedIp: true })).toBeNull();
  });
});
