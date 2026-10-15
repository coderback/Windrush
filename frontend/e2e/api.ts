import { expect, type Page, type Request } from "@playwright/test";

type Reply = { status?: number; json: unknown };
/** The JSON body, { status, json }, or a function of the request returning either. */
type Mock = ((request: Request) => unknown) | object;

/**
 * Mock the API in the browser. Keys are "METHOD /api/path" (query strings ignored). Every call is
 * recorded, and a call with no mock is answered with a 599 and recorded in `unmocked`, which
 * `expectAllMocked` checks at the end of a test.
 */
export async function mockApi(page: Page, handlers: Record<string, Mock>) {
  const calls: Request[] = [];
  const unmocked: string[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    calls.push(request);
    if (!(key in handlers)) {
      unmocked.push(key);
      return route.fulfill({ status: 599, json: { detail: `not mocked: ${key}` } });
    }
    const mock = handlers[key];
    const reply = typeof mock === "function" ? mock(request) : mock;
    const isReply = typeof reply === "object" && reply !== null && "json" in reply;
    await route.fulfill(isReply ? { status: (reply as Reply).status ?? 200, json: (reply as Reply).json }
                                : { status: 200, json: reply });
  });
  return {
    calls,
    /** Query parameters of the calls to a path, oldest first. */
    params: (path: string) =>
      calls.filter((r) => new URL(r.url()).pathname === path).map((r) => new URL(r.url()).searchParams),
    expectAllMocked: () => expect(unmocked, "API calls without a mock").toEqual([]),
  };
}

export async function signIn(page: Page) {
  await page.addInitScript(() => localStorage.setItem("windrush_token", "test-token"));
}
