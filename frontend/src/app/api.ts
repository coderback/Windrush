export async function authFetch(url: string, options: RequestInit = {}) {
  const token = localStorage.getItem("windrush_token");
  const headers = new Headers(options.headers || {});

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    localStorage.removeItem("windrush_token");
    window.location.href = "/login";
  }

  return response;
}
