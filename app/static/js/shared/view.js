import { escapeHtml } from "./format.js";

// ===== Navigation + section switching =====
// Pages declare nav buttons with [data-section] inside #appNav, and content
// sections with [data-section] inside .app-workspace. showSection() flips both.

export function showSection(section) {
  document.querySelectorAll(".app-workspace > [data-section]").forEach((el) => {
    el.hidden = el.dataset.section !== section;
  });
  setActiveNav(section);
  closeNav();
}

export function setActiveNav(section) {
  document.querySelectorAll("#appNav [data-section]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.section === section);
  });
}

// Wire nav buttons + mobile toggle. onChange(section) fires on every switch
// (use it to lazy-load the section's data).
export function initNav(defaultSection, onChange) {
  const nav = document.querySelector("#appNav");
  const toggle = document.querySelector("#navToggle");
  if (toggle) toggle.addEventListener("click", () => nav?.classList.toggle("open"));

  nav?.querySelectorAll("[data-section]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const section = btn.dataset.section;
      showSection(section);
      if (onChange) onChange(section);
    });
  });
  if (defaultSection) {
    showSection(defaultSection);
    if (onChange) onChange(defaultSection);
  }
}

function closeNav() {
  document.querySelector("#appNav")?.classList.remove("open");
}

export function setPageTitle(text) {
  const el = document.querySelector("#sectionTitle");
  if (el) el.textContent = text;
}

// ===== Drawer (right-side detail panel) =====
export function openDrawer(title, innerHtml) {
  let drawer = document.querySelector("#appDrawer");
  let backdrop = document.querySelector("#drawerBackdrop");
  if (!drawer) {
    drawer = document.createElement("aside");
    drawer.id = "appDrawer";
    drawer.className = "app-drawer";
    document.body.appendChild(drawer);
  }
  if (!backdrop) {
    backdrop = document.createElement("div");
    backdrop.id = "drawerBackdrop";
    backdrop.className = "drawer-backdrop";
    backdrop.addEventListener("click", closeDrawer);
    document.body.appendChild(backdrop);
  }
  drawer.innerHTML = `
    <div class="app-drawer-header">
      <h3>${escapeHtml(title)}</h3>
      <button class="modal-close" id="drawerCloseBtn">&times;</button>
    </div>
    <div class="app-drawer-body">${innerHtml}</div>
  `;
  drawer.querySelector("#drawerCloseBtn").addEventListener("click", closeDrawer);
  drawer.hidden = false;
  backdrop.hidden = false;
}

export function closeDrawer() {
  const drawer = document.querySelector("#appDrawer");
  const backdrop = document.querySelector("#drawerBackdrop");
  if (drawer) drawer.hidden = true;
  if (backdrop) backdrop.hidden = true;
}

// ===== Loading / empty / error states =====
export function renderSkeleton(rows = 4) {
  return `<div class="skeleton">${Array.from({ length: rows }, () => '<div class="skeleton-row"></div>').join("")}</div>`;
}

export function showSkeleton(container, rows = 4) {
  if (container) container.innerHTML = renderSkeleton(rows);
}

export function renderEmptyState(message = "暂无数据") {
  return `<div class="empty-state"><p>${escapeHtml(message)}</p></div>`;
}

export function showEmpty(container, message) {
  if (container) container.innerHTML = renderEmptyState(message);
}

// Render an error with an optional retry button wired to retryFn.
export function setError(container, message, retryFn) {
  if (!container) return;
  container.innerHTML = `
    <div class="error-state">
      <p>${escapeHtml(message)}</p>
      ${retryFn ? '<button class="small" data-retry>重试</button>' : ""}
    </div>
  `;
  if (retryFn) {
    container.querySelector("[data-retry]")?.addEventListener("click", retryFn);
  }
}

// ===== Busy state for submit buttons =====
export function setBusy(button, on, busyText = "处理中...") {
  if (!button) return;
  if (on) {
    button.dataset.idleText = button.textContent;
    button.disabled = true;
    button.textContent = busyText;
  } else {
    button.disabled = false;
    if (button.dataset.idleText) button.textContent = button.dataset.idleText;
  }
}

// Run an async task with a busy button + standardized error toast hook.
export async function withBusy(button, busyText, task) {
  setBusy(button, true, busyText);
  try {
    return await task();
  } finally {
    setBusy(button, false);
  }
}
