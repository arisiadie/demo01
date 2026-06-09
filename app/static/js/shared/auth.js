import { request } from "./api.js";
import { setToken, setCurrentUser, clearSession, getCurrentUser } from "./state.js";
import { setPendingToast } from "./components.js";

const LOGIN_PAGE = "/static/index.html";

const ROLE_PAGE = {
  patient: "/static/patient.html",
  doctor: "/static/doctor.html",
  admin: "/static/admin.html",
};

const ROLE_LABEL = { patient: "患者", doctor: "医生", admin: "管理员" };

export async function login(externalId, password) {
  const data = await request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ external_id: externalId, password }),
  });
  setToken(data.access_token);
  setCurrentUser(data);
  return data;
}

export function logout() {
  clearSession();
  location.href = LOGIN_PAGE;
}

export function redirectByRole(user) {
  const target = ROLE_PAGE[user?.role];
  if (target) location.href = target;
  else location.href = LOGIN_PAGE;
}

// Guard a role-specific page. Verifies the session server-side via /api/auth/me.
// On mismatch or no session, redirects (to the correct page or login) and returns null.
export async function requireRole(role) {
  if (!getCurrentUser()) {
    location.href = LOGIN_PAGE;
    return null;
  }
  try {
    const me = await request("/api/auth/me");
    setCurrentUser(me);
    if (me.role !== role) {
      const dest = ROLE_LABEL[me.role] || "对应";
      setPendingToast(`无权限访问${ROLE_LABEL[role] || ""}页面，已返回${dest}工作台`, "warning");
      redirectByRole(me);
      return null;
    }
    return me;
  } catch {
    clearSession();
    location.href = LOGIN_PAGE;
    return null;
  }
}
