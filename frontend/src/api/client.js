const BASE_URL = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const TOKEN_KEY = 'duka_erp_token'

// "Remember me" off keeps the token in sessionStorage, so it is gone when the
// browser is closed; on (the default) keeps it in localStorage.
let rememberSession = true

export function setRememberSession(remember) {
  rememberSession = remember
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(TOKEN_KEY)
  if (token) (rememberSession ? localStorage : sessionStorage).setItem(TOKEN_KEY, token)
}

export class ApiError extends Error {
  constructor(status, body) {
    super(typeof body === 'string' ? body : (body?.detail || 'Request failed'))
    this.status = status
    this.body = body
  }
}

/** The request never reached the server (no connection, server down,
 * timed out) — unlike an ApiError, nothing was refused, so it's safe to
 * try again later. */
export class NetworkError extends Error {
  constructor(cause) {
    super('No connection to the server.')
    this.cause = cause
  }
}

/** True when trying again later may succeed: no connection, the server
 * or the proxy in front of it is down, or the session needs signing in again. */
export function isTransient(err) {
  return err instanceof NetworkError || (err instanceof ApiError && (err.status >= 500 || err.status === 401 || err.status === 408 || err.status === 429))
}

/** fetch(), with a failure to reach the server — or `timeout` ms passing —
 * raised as NetworkError. An abort through `init.signal` is the caller's
 * own and is rethrown as is. */
async function send(url, init = {}, timeout) {
  const { signal } = init
  try {
    return await fetch(url, {
      ...init,
      signal: timeout ? AbortSignal.any([signal, AbortSignal.timeout(timeout)].filter(Boolean)) : signal,
    })
  } catch (err) {
    if (err?.name === 'AbortError' && signal?.aborted) throw err
    throw new NetworkError(err)
  }
}

function buildUrl(path, params) {
  const url = new URL(path.replace(/^\//, ''), BASE_URL.endsWith('/') ? BASE_URL : BASE_URL + '/')
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue
      url.searchParams.set(key, value)
    }
  }
  return url.toString()
}

async function request(method, path, { params, body, signal, timeout } = {}) {
  const token = getToken()
  const headers = { Accept: 'application/json' }
  if (token) headers.Authorization = `Token ${token}`

  // FormData (file uploads) must NOT be JSON-encoded and must NOT get an
  // explicit Content-Type — the browser sets its own multipart boundary,
  // which we'd otherwise clobber.
  const isFormData = body instanceof FormData
  if (body !== undefined && !isFormData) headers['Content-Type'] = 'application/json'

  const response = await send(buildUrl(path, params), {
    method,
    headers,
    body: body === undefined ? undefined : (isFormData ? body : JSON.stringify(body)),
    signal,
  }, timeout)

  if (response.status === 204) return null

  const isJson = response.headers.get('content-type')?.includes('application/json')
  const data = isJson ? await response.json() : await response.text()

  if (!response.ok) {
    endSessionIfRejected(response, token)
    throw new ApiError(response.status, data)
  }
  return data
}

/** A 401 on a request that carried a token means the session expired (or
 * an admin ended it): drop the token and tell AuthContext, which returns
 * to the sign-in screen with a notice. */
function endSessionIfRejected(response, token) {
  if (response.status === 401 && token) {
    setToken(null)
    window.dispatchEvent(new Event('auth:expired'))
  }
}

export const client = {
  get: (path, params, options) => request('GET', path, { params, ...options }),
  post: (path, body, options) => request('POST', path, { body, ...options }),
  patch: (path, body, options) => request('PATCH', path, { body, ...options }),
  put: (path, body, options) => request('PUT', path, { body, ...options }),
  delete: (path, options) => request('DELETE', path, options),
}

/** Fetches every page of a DRF-paginated list endpoint and returns the flat array. */
export async function listAll(path, params) {
  const token = getToken()
  const headers = { Accept: 'application/json' }
  if (token) headers.Authorization = `Token ${token}`

  let results = []
  let next = buildUrl(path, params)
  while (next) {
    const response = await send(next, { headers })
    if (!response.ok) {
      endSessionIfRejected(response, token)
      throw new ApiError(response.status, await response.json().catch(() => null))
    }
    const page = await response.json()
    results = results.concat(page.results)
    next = page.next
  }
  return results
}

/** Saves a file the API generates (e.g. a CSV export) — a plain link can't
 * carry the sign-in token. */
export async function download(path, params, filename) {
  const token = getToken()
  const headers = token ? { Authorization: `Token ${token}` } : {}
  const response = await send(buildUrl(path, params), { headers })
  if (!response.ok) {
    endSessionIfRejected(response, token)
    throw new ApiError(response.status, await response.json().catch(() => null))
  }
  const url = URL.createObjectURL(await response.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
