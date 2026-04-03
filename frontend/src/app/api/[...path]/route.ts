import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL;

async function proxy(request: NextRequest, path: string) {
  if (!API_URL) {
    return new NextResponse("API_URL not configured", { status: 503 });
  }

  const contentType = request.headers.get("content-type") ?? "";
  const init: RequestInit & { duplex?: string } = {
    method: request.method,
    headers: { "content-type": contentType },
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.duplex = "half";
    init.body = request.body;
  }

  const upstream = await fetch(`${API_URL}/${path}`, init);

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  });
}

export async function GET(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path.join("/"));
}

export async function POST(
  req: NextRequest,
  { params }: { params: { path: string[] } }
) {
  return proxy(req, params.path.join("/"));
}
