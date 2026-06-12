import { escapeHtml } from "./format.js";
import { trapFocus, restoreFocus, bindEscapeClose } from "./a11y.js";

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
// backdrop also closes. Focus is trapped inside and restored on close; Esc closes.
export function openModal(innerHtml) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML = `<div class="modal">${innerHtml}</div>`;
  let releaseTrap = () => {};
  let releaseEsc = () => {};
  const close = () => {
    releaseTrap();
    releaseEsc();
    overlay.remove();
    restoreFocus();
  };
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  overlay.querySelectorAll("[data-modal-close]").forEach((btn) => btn.addEventListener("click", close));
  document.body.appendChild(overlay);
  releaseTrap = trapFocus(overlay);
  releaseEsc = bindEscapeClose(overlay, close);
  return { overlay, close };
}

export function closeModal(overlay) {
  if (overlay) overlay.remove();
  else document.querySelector(".modal-overlay")?.remove();
  restoreFocus();
}

// Enterprise-style delete confirmation dialog. Returns a Promise<boolean> that
// resolves true only when the user explicitly confirms. Backdrop/Esc/cancel all
// resolve false. When highRisk is true, the confirm button stays disabled until
// the user types the exact word "删除" — a deliberate friction step for
// irreversible/compliance-sensitive deletions (audit logs, high-risk records).
export function confirmDelete({ title = "确认删除", message = "", count = 1, highRisk = false, confirmLabel } = {}) {
  return new Promise((resolve) => {
    const label = confirmLabel || (count > 1 ? `删除 ${count} 条记录` : "确认删除");
    const riskBlock = highRisk
      ? `
        <div class="confirm-danger-guard">
          <p class="confirm-danger-hint">此操作不可恢复。请输入 <strong>删除</strong> 两字以确认。</p>
          <input id="confirmDangerInput" class="confirm-danger-input" type="text"
                 autocomplete="off" placeholder="输入：删除" aria-label="输入删除以确认" />
        </div>`
      : "";
    const inner = `
      <div class="modal-header">
        <h3>${escapeHtml(title)}</h3>
        <button class="modal-close" data-modal-close aria-label="关闭">×</button>
      </div>
      <div class="modal-body">
        <div class="confirm-delete-body ${highRisk ? "high-risk" : ""}">
          <div class="confirm-delete-icon">${highRisk ? "⚠️" : "🗑️"}</div>
          <div class="confirm-delete-text">${message ? escapeHtml(message) : "确定要删除选中的记录吗？"}</div>
        </div>
        ${riskBlock}
      </div>
      <div class="modal-footer">
        <button data-modal-close>取消</button>
        <button id="confirmDeleteBtn" class="danger"${highRisk ? " disabled" : ""}>${escapeHtml(label)}</button>
      </div>
    `;
    let settled = false;
    const { overlay, close } = openModal(inner);
    const finish = (value) => {
      if (settled) return;
      settled = true;
      observer.disconnect();
      close();
      resolve(value);
    };
    // openModal binds its own Esc handler that removes the overlay WITHOUT going
    // through our finish(), which would otherwise hang this promise forever.
    // Observe removal of the overlay so the Esc path resolves to false too.
    const observer = new MutationObserver(() => {
      if (!document.body.contains(overlay) && !settled) {
        settled = true;
        observer.disconnect();
        resolve(false);
      }
    });
    observer.observe(document.body, { childList: true });
    // Backdrop and close-button paths are handled explicitly below.
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) finish(false);
    });
    overlay.querySelectorAll("[data-modal-close]").forEach((btn) =>
      btn.addEventListener("click", () => finish(false))
    );
    const confirmBtn = overlay.querySelector("#confirmDeleteBtn");
    if (highRisk) {
      const input = overlay.querySelector("#confirmDangerInput");
      input.addEventListener("input", () => {
        confirmBtn.disabled = input.value.trim() !== "删除";
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !confirmBtn.disabled) finish(true);
      });
      setTimeout(() => input.focus(), 0);
    } else {
      setTimeout(() => confirmBtn.focus(), 0);
    }
    confirmBtn.addEventListener("click", () => {
      if (!confirmBtn.disabled) finish(true);
    });
  });
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
