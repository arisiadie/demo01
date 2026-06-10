// Field-level form error rendering. Pairs with shared/validators.js, which
// returns { ok, errors, fieldErrors:{fieldId: message} }. These helpers mark the
// offending inputs inline (red border + red text below) instead of relying on a
// toast or the backend's raw 422 JSON.
import { announceStatus } from "./a11y.js";

// Mark a single input as invalid: red border + a .field-error message node
// inserted right after it. Re-marking updates the existing message.
export function markField(inputEl, message) {
  if (!inputEl) return;
  inputEl.classList.add("field-invalid");
  inputEl.setAttribute("aria-invalid", "true");
  let errorNode = inputEl.nextElementSibling;
  if (!errorNode || !errorNode.classList || !errorNode.classList.contains("field-error")) {
    errorNode = document.createElement("div");
    errorNode.className = "field-error";
    inputEl.insertAdjacentElement("afterend", errorNode);
  }
  errorNode.textContent = message;
  if (inputEl.id) inputEl.setAttribute("aria-describedby", `${inputEl.id}-error`);
  errorNode.id = inputEl.id ? `${inputEl.id}-error` : "";
  // Clear the error as soon as the user starts fixing this field.
  if (!inputEl.dataset.clearBound) {
    const handler = () => clearField(inputEl);
    inputEl.addEventListener("input", handler);
    inputEl.addEventListener("change", handler);
    inputEl.dataset.clearBound = "1";
  }
}

export function clearField(inputEl) {
  if (!inputEl) return;
  inputEl.classList.remove("field-invalid");
  inputEl.removeAttribute("aria-invalid");
  const next = inputEl.nextElementSibling;
  if (next && next.classList && next.classList.contains("field-error")) {
    next.remove();
  }
}

export function clearFormErrors(container) {
  if (!container) return;
  container.querySelectorAll(".field-invalid").forEach((el) => {
    el.classList.remove("field-invalid");
    el.removeAttribute("aria-invalid");
  });
  container.querySelectorAll(".field-error").forEach((el) => el.remove());
}

// Apply { fieldId: message } onto the matching inputs within container.
// Focuses the first invalid field and announces it. Returns true if any error.
export function applyErrors(container, fieldErrors) {
  const entries = Object.entries(fieldErrors || {});
  if (!entries.length) return false;
  let first = null;
  for (const [fieldId, message] of entries) {
    const input = (container || document).querySelector(`#${fieldId}`);
    if (input) {
      markField(input, message);
      if (!first) first = input;
    }
  }
  if (first) {
    first.focus();
    announceStatus(entries[0][1]);
  }
  return true;
}
