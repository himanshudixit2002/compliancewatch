/**
 * A stand-in for the cookie store `cookies()` from next/headers resolves to, for tests of the
 * session and data access modules. A test file mocks the module once:
 *
 *   vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());
 *
 * and then reads or seeds `fakeCookies` directly; `fakeCookies.reset()` clears it between tests.
 * Only the methods the app uses exist here.
 *
 * Like a browser, the store keeps one cookie per name and path (no path means `/`), and a write
 * that expires a cookie removes it. `visit(pathname)` makes the reads answer as the request a
 * browser sends to that path: a cookie scoped to another path is not in it, so a test can show
 * what an action posted to /onboarding cannot see of a cookie scoped to /settings. Until a test
 * visits a path, every cookie is sent whatever its path.
 */
export interface FakeCookie {
  name: string;
  value: string;
  options: Record<string, unknown>;
}

function pathOf(options: Record<string, unknown>): string {
  return typeof options.path === "string" && options.path !== "" ? options.path : "/";
}

/** RFC 6265 path matching: the cookie's path is the request path or one of its directories. */
function pathMatches(cookiePath: string, requestPath: string): boolean {
  if (requestPath === cookiePath) return true;
  if (!requestPath.startsWith(cookiePath)) return false;
  return cookiePath.endsWith("/") || requestPath.charAt(cookiePath.length) === "/";
}

function expires(options: Record<string, unknown>): boolean {
  if (typeof options.maxAge === "number") return options.maxAge <= 0;
  return options.expires instanceof Date && options.expires.getTime() <= Date.now();
}

function jarKey(name: string, path: string): string {
  return `${path}\u0000${name}`;
}

export class FakeCookieStore {
  /** The browser's jar, one cookie per path and name. */
  private readonly jar = new Map<string, FakeCookie>();
  /** The last write of each name, expiring writes included. */
  private readonly writes = new Map<string, FakeCookie>();
  private requestPath: string | null = null;

  /** Answers the reads that follow as the request a browser sends to this path. */
  visit(pathname: string): this {
    this.requestPath = pathname;
    return this;
  }

  get(name: string): { name: string; value: string } | undefined {
    // A browser lists longer paths first, and Next keeps the last value of a repeated name.
    const cookie = this.sent(name).at(-1);
    return cookie === undefined ? undefined : { name: cookie.name, value: cookie.value };
  }

  has(name: string): boolean {
    return this.sent(name).length > 0;
  }

  set(
    nameOrCookie: string | ({ name: string; value: string } & Record<string, unknown>),
    value?: string,
    options: Record<string, unknown> = {},
  ): this {
    let cookie: FakeCookie;
    if (typeof nameOrCookie === "string") {
      cookie = { name: nameOrCookie, value: value ?? "", options };
    } else {
      const { name, value: cookieValue, ...rest } = nameOrCookie;
      cookie = { name, value: cookieValue, options: rest };
    }
    const key = jarKey(cookie.name, pathOf(cookie.options));
    this.writes.set(cookie.name, cookie);
    if (expires(cookie.options)) this.jar.delete(key);
    else this.jar.set(key, cookie);
    return this;
  }

  /** Like Next's store: a name (the cookie at `/`), or the options naming the cookie and path. */
  delete(nameOrOptions: string | ({ name: string } & Record<string, unknown>)): this {
    const [name, path] =
      typeof nameOrOptions === "string"
        ? [nameOrOptions, "/"]
        : [nameOrOptions.name, pathOf(nameOrOptions)];
    this.jar.delete(jarKey(name, path));
    this.writes.delete(name);
    return this;
  }

  /** The last write of a cookie, with the options it was set with. */
  written(name: string): FakeCookie | undefined {
    return this.writes.get(name);
  }

  reset(): void {
    this.jar.clear();
    this.writes.clear();
    this.requestPath = null;
  }

  /** The cookies of this name the current request carries, longest path first. */
  private sent(name: string): FakeCookie[] {
    const requestPath = this.requestPath;
    return [...this.jar.values()]
      .filter(
        (cookie) =>
          cookie.name === name &&
          (requestPath === null || pathMatches(pathOf(cookie.options), requestPath)),
      )
      .sort((a, b) => pathOf(b.options).length - pathOf(a.options).length);
  }
}

export const fakeCookies = new FakeCookieStore();

export function nextHeadersMock() {
  return { cookies: () => Promise.resolve(fakeCookies) };
}
