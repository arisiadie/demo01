import { escapeHtml } from "./format.js";

export function showToast(message, type = "success", duration = 3000) {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${type === "success" ? "✓" : type === "error" ? "✕" : "!"}</span>
    <div class="toast-content">
      <p>${escapeHtml(message)}</p>
    </div>
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = "slideOut 0.3s ease forwards";
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

export function setStatus(text) {
  const el = document.querySelector("#statusText");
  if (el) el.textContent = text;
}

const PENDING_TOAST_KEY = "oralcare_pending_toast";

// Queue a toast to be shown after a page navigation (survives the redirect).
export function setPendingToast(message, type = "success") {
  try {
    sessionStorage.setItem(PENDING_TOAST_KEY, JSON.stringify({ message, type }));
  } catch {
    // sessionStorage unavailable; skip silently
  }
}

// Show and clear any queued toast. Call once on page load.
export function flushPendingToast() {
  let pending = null;
  try {
    pending = JSON.parse(sessionStorage.getItem(PENDING_TOAST_KEY) || "null");
    sessionStorage.removeItem(PENDING_TOAST_KEY);
  } catch {
    return;
  }
  if (pending?.message) showToast(pending.message, pending.type || "success");
}

export function renderLoading(message = "正在加载...") {
  return `<div class="loading-spinner">${escapeHtml(message)}</div>`;
}

export function renderEmpty(message = "暂无数据") {
  return `<div class="empty">${escapeHtml(message)}</div>`;
}

// Creates a modal overlay from an inner-HTML string and appends it to the body.
// Returns the overlay element. Close buttons use [data-modal-close]; clicking the
// backdrop also closes. Returns { overlay, close } so callers can wire submit handlers.
export function openModal(innerHtml) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `<div class="modal">${innerHtml}</div>`;
  const close = () => overlay.remove();
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  overlay.querySelectorAll("[data-modal-close]").forEach((btn) => btn.addEventListener("click", close));
  document.body.appendChild(overlay);
  return { overlay, close };
}

export function closeModal(overlay) {
  if (overlay) overlay.remove();
  else document.querySelector(".modal-overlay")?.remove();
}

export function renderSimpleTable(title, rows, columns) {
  return `
    <div class="result-section">
      <h4>${escapeHtml(title)}</h4>
      ${rows && rows.length ? `
        <div class="data-table">
          <div class="data-table-head">${columns.map((column) => `<span>${escapeHtml(column)}</span>`).join("")}</div>
          ${rows.map((row) => `
            <div class="data-table-row">
              ${columns.map((column) => `<span>${escapeHtml(row[column])}</span>`).join("")}
            </div>
          `).join("")}
        </div>
      ` : "<p>暂无记录</p>"}
    </div>
  `;
}
