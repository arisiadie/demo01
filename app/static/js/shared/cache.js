// In-memory TTL cache for read requests. Lets sections that re-load on every
// nav switch reuse a recent response instead of re-hitting the API.

const store = new Map(); // key -> { value, expires }

// Returns the cached value if fresh, otherwise runs loader(), caches, returns it.
// Concurrent callers with the same key share one in-flight promise.
export async function cachedRequest(key, loader, ttlMs = 30000) {
  const hit = store.get(key);
  const now = Date.now();
  if (hit && hit.expires > now) {
    return hit.pending ? hit.pending : hit.value;
  }
  const pending = Promise.resolve()
    .then(loader)
    .then((value) => {
      store.set(key, { value, expires: Date.now() + ttlMs });
      return value;
    })
    .catch((err) => {
      store.delete(key); // don't cache failures
      throw err;
    });
  // Park the in-flight promise so parallel callers dedupe.
  store.set(key, { pending, expires: now + ttlMs });
  return pending;
}

// Drop cache entries whose key starts with prefix (call after writes).
export function invalidateCache(prefix = "") {
  if (!prefix) {
    store.clear();
    return;
  }
  for (const key of store.keys()) {
    if (key.startsWith(prefix)) store.delete(key);
  }
}
