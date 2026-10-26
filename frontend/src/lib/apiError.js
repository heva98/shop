/** Human-readable message from an ApiError: DRF's {detail} or its
 * per-field {field: [messages]} shape, else `fallback`. */
export function apiErrorText(err, fallback) {
  const body = err?.body
  if (body?.detail) return body.detail
  if (body && typeof body === 'object') return Object.values(body).flat().join(' ')
  return fallback
}
