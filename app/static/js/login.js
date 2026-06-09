import { login, redirectByRole } from "./shared/auth.js";
import { getCurrentUser, getToken } from "./shared/state.js";

const DEMO_ACCOUNTS = {
  patient: { external_id: "patient-demo", password: "patient123" },
  doctor: { external_id: "doctor-demo", password: "doctor123" },
  admin: { external_id: "admin-demo", password: "admin123" },
};

const form = document.querySelector("#loginForm");
const userInput = document.querySelector("#loginUserInput");
const passwordInput = document.querySelector("#loginPasswordInput");
const errorBox = document.querySelector("#loginError");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

async function submitLogin(externalId, password) {
  errorBox.hidden = true;
  try {
    const user = await login(externalId, password);
    redirectByRole(user);
  } catch (error) {
    showError(error.message || "登录失败，请检查账号密码");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitLogin(userInput.value.trim(), passwordInput.value);
});

document.querySelectorAll("[data-demo-login]").forEach((button) => {
  button.addEventListener("click", () => {
    const account = DEMO_ACCOUNTS[button.dataset.demoLogin];
    if (!account) return;
    userInput.value = account.external_id;
    passwordInput.value = account.password;
    submitLogin(account.external_id, account.password);
  });
});

// Already logged in? Skip the form.
const existing = getCurrentUser();
if (existing && getToken()) {
  redirectByRole(existing);
}
