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
  if (response.status === 422) {
    // Pydantic validation error. Convert the raw {detail:[{loc,msg}]} JSON into
    // one human sentence so a field the frontend validators missed still shows a
    // readable message instead of a cryptic dump.
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      // fall through to generic message
    }
    const fields = Array.isArray(detail)
      ? [...new Set(detail.map((d) => (Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null)).filter(Boolean))]
      : [];
    const hint = fields.length ? `（字段：${fields.join("、")}）` : "";
    throw new Error(`提交内容格式不符，请检查必填项与格式${hint}`);
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}
