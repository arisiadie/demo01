// Concurrency guard: when the same logical task is triggered repeatedly (e.g.
// clicking two doctor reports quickly), only the latest call's result is allowed
// to land. Stale results are discarded by comparing a per-key token.

const tokens = new Map(); // taskKey -> latest token

// Runs asyncFn but resolves to a sentinel-aware result. If a newer runLatest
// with the same key started before this one finished, the stale result is
// dropped (resolves to undefined) instead of overwriting fresh UI.
export async function runLatest(taskKey, asyncFn) {
  const token = (tokens.get(taskKey) || 0) + 1;
  tokens.set(taskKey, token);
  const result = await asyncFn();
  if (tokens.get(taskKey) !== token) {
    return undefined; // superseded by a newer call
  }
  return result;
}

// True if a later runLatest for this key has started since `token`.
export function isStale(taskKey, token) {
  return tokens.get(taskKey) !== token;
}
