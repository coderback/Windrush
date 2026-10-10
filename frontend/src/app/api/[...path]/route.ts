import { NextRequest, NextResponse } from "next/server";

// Forwards /api/* to the FastAPI backend when nothing else is in front of the frontend
// (e.g. on Vercel). Under docker compose, nginx serves /api itself and this never runs.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_URL = process.env.API_URL?.replace(/\/+$/, "");

// Only what the API reads. Cookies and the host header stay on this side.
const FORWARDED_REQUEST_HEADERS = [
  "authorization",
  "content-type",
  "accept",
  "accept-language",
  "last-event-id",
];

// fetch() hands back a decoded body, so the upstream framing headers no longer describe it.
const DROPPED_RESPONSE_HEADERS = [
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  "keep-alive",
];

async function proxy(request: NextRequest) {
  if (!API_URL) {
    return NextResponse.json({ detail: "API_URL not configured" }, { status: 503 });
  }

  // Taken from the raw URL so percent-encoding and the query string survive.
  const { pathname, search } = request.nextUrl;
  const target = `${API_URL}${pathname.replace(/^\/api(?=\/|$)/, "")}${search}`;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const init: RequestInit & { duplex?: string } = {
    method: request.method,
    headers,
    cache: "no-store",
    // Closing the tab cancels the upstream call, which is what ends a live apply session.
    signal: request.signal,
  };

  if (request.method !== "GET" && request.method !== "HEAD" && request.body) {
    init.duplex = "half";
    init.body = request.body;
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    if (request.signal.aborted) {
      return new NextResponse(null, { status: 499 });
    }
    return NextResponse.json({ detail: "API unreachable" }, { status: 502 });
  }

  const responseHeaders = new Headers(upstream.headers);
  for (const name of DROPPED_RESPONSE_HEADERS) {
    responseHeaders.delete(name);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export {
  proxy as GET,
  proxy as HEAD,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
