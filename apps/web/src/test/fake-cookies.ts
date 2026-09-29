/**
 * A stand-in for the cookie store `cookies()` from next/headers resolves to, for tests of the
 * session and data access modules. A test file mocks the module once:
 *
 *   vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
 *
 * and then reads or seeds `fakeCookies` directly; `fakeCookies.reset()` clears it between tests.
 * Only the methods the app uses exist here.
 */
export interface FakeCookie {
  name: string;
  value: string;
  options: Record<string, unknown>;
}

export class FakeCookieStore {
  private readonly jar = new Map<string, FakeCookie>();

  get(name: string): { name: string; value: string } | undefined {
    const cookie = this.jar.get(name);
    return cookie === undefined ? undefined : { name: cookie.name, value: cookie.value };
  }

  has(name: string): boolean {
    return this.jar.has(name);
  }

  set(
    nameOrCookie: string | ({ name: string; value: string } & Record<string, unknown>),
    value?: string,
    options: Record<string, unknown> = {},
  ): this {
    if (typeof nameOrCookie === "string") {
      this.jar.set(nameOrCookie, { name: nameOrCookie, value: value ?? "", options });
    } else {
      const { name, value: cookieValue, ...rest } = nameOrCookie;
      this.jar.set(name, { name, value: cookieValue, options: rest });
    }
    return this;
  }

  delete(name: string): this {
    this.jar.delete(name);
    return this;
  }

  /** The last write of a cookie, with the options it was set with. */
  written(name: string): FakeCookie | undefined {
    return this.jar.get(name);
  }

  reset(): void {
    this.jar.clear();
  }
}

export const fakeCookies = new FakeCookieStore();

export function nextHeadersMock() {
  return { cookies: () => Promise.resolve(fakeCookies) };
}
