/**
 * Centralised API client.
 * Automatically injects the JWT Bearer token from localStorage.
 * Throws on non-2xx responses with the server's error detail.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || "";

function getToken() {
  return localStorage.getItem("mt_token");
}

async function request(method, path, { body, form, params } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let url = `${BASE}${path}`;
  if (params) {
    const q = new URLSearchParams(params);
    url += `?${q}`;
  }

  const init = { method, headers };

  if (form) {
    init.body = form; // FormData – no Content-Type header needed
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  const res = await fetch(url, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const e = new Error(err.detail || "Request failed");
    e.status = res.status;
    throw e;
  }

  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  if (ct.includes("text/csv")) return res; // return raw response for file download
  return res;
}

export const api = {
  get: (path, opts) => request("GET", path, opts),
  post: (path, opts) => request("POST", path, opts),
  delete: (path, opts) => request("DELETE", path, opts),

  // Auth
  login: (username, password) => {
    const form = new FormData();
    form.append("username", username);
    form.append("password", password);
    return request("POST", "/api/auth/login", { form });
  },

  // Media URL helper
  mediaUrl: (filename) => `${BASE}/api/media/${filename}`,
};
