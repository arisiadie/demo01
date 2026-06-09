import { getToken, clearSession } from "./state.js";

const LOGIN_PAGE = "/static/index.html";

export function headers(json = true) {
  const result = {};
  const token = getToken();
  if (token) result.Authorization = `Bearer ${token}`;
  if (json) result["Content-Type"] = "application/json";
  return result;
}

export async function request(path, options = {}) {
  const opts = { ...options };
  if (!opts.headers) {
    opts.headers = opts.body instanceof FormData ? headers(false) : headers(true);
  }
  const response = await fetch(path, opts);
  if (response.status === 401) {
    clearSession();
    if (!location.pathname.endsWith("/index.html") && location.pathname !== "/") {
      location.href = LOGIN_PAGE;
    }
    throw new Error("登录态已失效，请重新登录");
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}
