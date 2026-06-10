// Hash-based routing: keeps the active section in the URL so refresh restores
// it, browser back/forward works, and links are shareable.
// Format: #section  or  #section?key=value&key2=value2

export function parseHash(hash = location.hash) {
  const raw = (hash || "").replace(/^#/, "");
  if (!raw) return { section: null, params: {} };
  const [section, query = ""] = raw.split("?");
  const params = {};
  if (query) {
    for (const pair of query.split("&")) {
      const [k, v = ""] = pair.split("=");
      if (k) params[decodeURIComponent(k)] = decodeURIComponent(v);
    }
  }
  return { section: section || null, params };
}

export function buildHash(section, params = {}) {
  const keys = Object.keys(params).filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== "");
  const query = keys
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join("&");
  return `#${section}${query ? `?${query}` : ""}`;
}

export function currentRoute() {
  return parseHash();
}

// Write a new route without reloading. Replacing avoids stacking duplicate
// history entries when re-selecting the same section.
export function navigate(section, params = {}, { replace = false } = {}) {
  const next = buildHash(section, params);
  if (next === location.hash) return;
  if (replace) {
    history.replaceState(null, "", next);
    // replaceState doesn't fire hashchange; callers relying on onRouteChange
    // should handle the initial route explicitly.
  } else {
    location.hash = next;
  }
}

export function onRouteChange(handler) {
  window.addEventListener("hashchange", () => handler(parseHash()));
}
