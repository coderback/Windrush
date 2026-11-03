import { DEMO_MODE, demoFetch } from "@/lib/demo";

export async function authFetch(url: string, options: RequestInit = {}) {
  if (DEMO_MODE) return demoFetch(url, options);

  let token = null;
  if (typeof window !== "undefined") {
    token = localStorage.getItem("windrush_token");
  }
  
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401 && typeof window !== "undefined") {
    localStorage.removeItem("windrush_token");
    window.location.href = "/login";
  }

  return response;
}
