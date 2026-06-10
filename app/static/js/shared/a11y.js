// Accessibility helpers for overlays (modal/drawer): trap Tab focus inside the
// container, close on Esc, and restore focus to the element that opened it.

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "textarea:not([disabled])",
  "input:not([disabled])", "select:not([disabled])", '[tabindex]:not([tabindex="-1"])',
].join(",");

let lastFocused = null;

function focusable(container) {
  return Array.from(container.querySelectorAll(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

// Trap Tab within container; focus the first focusable element. Returns a
// cleanup function that removes the listener.
export function trapFocus(container) {
  lastFocused = document.activeElement;
  const handler = (event) => {
    if (event.key !== "Tab") return;
    const items = focusable(container);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  container.addEventListener("keydown", handler);
  const firstItem = focusable(container)[0];
  if (firstItem) firstItem.focus();
  return () => container.removeEventListener("keydown", handler);
}

// Return focus to wherever it was before the overlay opened.
export function restoreFocus() {
  if (lastFocused && typeof lastFocused.focus === "function") {
    lastFocused.focus();
  }
  lastFocused = null;
}

// Close container on Escape. Returns a cleanup function.
export function bindEscapeClose(container, onClose) {
  const handler = (event) => {
    if (event.key === "Escape") onClose();
  };
  // document-level so Esc works even if focus drifts.
  document.addEventListener("keydown", handler);
  return () => document.removeEventListener("keydown", handler);
}

// Politely announce a status message to screen readers via a shared aria-live region.
export function announceStatus(message) {
  let region = document.querySelector("#a11yLiveRegion");
  if (!region) {
    region = document.createElement("div");
    region.id = "a11yLiveRegion";
    region.setAttribute("aria-live", "polite");
    region.setAttribute("aria-atomic", "true");
    region.style.cssText = "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);border:0;";
    document.body.appendChild(region);
  }
  region.textContent = "";
  // next tick so repeated identical messages still announce
  setTimeout(() => { region.textContent = message; }, 30);
}
