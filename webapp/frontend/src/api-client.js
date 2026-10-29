const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

let apiBase = ''
let unauthorizedHandler = null
let generation = 0
let userId = ''
let sessionCsrf = ''
const pendingRequests = new Set()
let listeningForSessions = false
const SESSION_EVENT_KEY = 'mpau_auth_session_event_v1'

export function captureApiContext() { return { generation, userId } }
export function isApiContextCurrent(context) {
  return context.generation === generation && context.userId === userId
    && (!userId || sessionCsrf === cookieValue('mpau_csrf_v2'))
}
export class StaleSessionError extends Error {
  constructor() { super('旧会话请求已取消'); this.staleSession = true }
}
function ensureCurrent(context) {
  if (!isApiContextCurrent(context)) {
    if (context.generation === generation && userId && sessionCsrf !== cookieValue('mpau_csrf_v2')) {
      unauthorizedHandler?.({ broadcast: false })
    }
    throw new StaleSessionError()
  }
}

export function setApiSession(nextUserId, { broadcast = true } = {}) {
  generation += 1
  for (const controller of pendingRequests) controller.abort()
  pendingRequests.clear()
  userId = nextUserId || ''
  sessionCsrf = userId ? cookieValue('mpau_csrf_v2') : ''
  if (broadcast && typeof localStorage !== 'undefined') {
    try { localStorage.setItem(SESSION_EVENT_KEY, JSON.stringify({ userId, nonce: `${Date.now()}-${Math.random()}` })) } catch {}
  }
}

/** Apply the same cancellation/epoch checks to loopback uploads as API calls. */
export async function sessionFetch(url, options = {}) {
  const context = captureApiContext()
  ensureCurrent(context)
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  pendingRequests.add(controller)
  try {
    const response = await fetch(url, { ...options, signal: controller.signal })
    ensureCurrent(context)
    return response
  } catch (error) {
    ensureCurrent(context)
    throw error
  } finally {
    pendingRequests.delete(controller)
    options.signal?.removeEventListener('abort', abort)
  }
}

function needsAgent(path, method, options) {
  if (SAFE_METHODS.has(method)) return false
  const route = path.split('?')[0]
  return /^\/api\/accounts\/[^/]+\/[^/]+(?:\/(?:login|check|resume))?$/.test(route)
    || /^\/api\/jobs\/(?:publish|batch\/)/.test(route)
    || /^\/api\/batches\/[^/]+\/retry-failed$/.test(route)
    || route === '/api/agent/local-upload-ticket'
    || (['/api/ai-copy/product-references', '/api/ai-copy/generate'].includes(route)
      && /(?:tmall\.com|taobao\.com)/i.test(String(options.body || '')))
}

async function localAgentProof() {
  const context = captureApiContext()
  const challenge = await apiRequest('/api/agent/local-identity/challenge', { method: 'POST' })
  ensureCurrent(context)
  const response = await sessionFetch(
    `http://127.0.0.1:48765/v1/identity?ticket=${encodeURIComponent(challenge.ticket)}`,
    { method: 'POST', mode: 'cors', cache: 'no-store', signal: AbortSignal.timeout(10_000) },
  ).catch((error) => {
    if (error.staleSession) throw error
    throw new Error('无法验证当前电脑的 Windows 助手，请更新助手并确认其连接的是当前服务和账号')
  })
  const result = await response.json().catch(() => ({}))
  ensureCurrent(context)
  if (!response.ok || !result.proof) throw new Error(result.detail || '本机助手验证失败，请更新助手后重新配对')
  return result.proof
}

/** Configure the shared browser client once when the Vue application starts. */
export function configureApiClient({ baseUrl = '', onUnauthorized = null } = {}) {
  apiBase = baseUrl.replace(/\/$/, '')
  unauthorizedHandler = onUnauthorized
  if (!listeningForSessions && typeof window !== 'undefined') {
    listeningForSessions = true
    window.addEventListener('storage', (event) => {
      if (event.key !== SESSION_EVENT_KEY || !event.newValue || !userId) return
      try {
        if (JSON.parse(event.newValue).userId !== userId || sessionCsrf !== cookieValue('mpau_csrf_v2')) {
          unauthorizedHandler?.({ broadcast: false })
        }
      } catch {}
    })
  }
}

/** Return a named Cookie value without exposing the HttpOnly session Cookie. */
function cookieValue(name) {
  const prefix = `${encodeURIComponent(name)}=`
  const entry = document.cookie
    .split(';')
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : ''
}

/** Convert FastAPI validation and application errors into one readable message. */
function errorMessage(body) {
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return body.detail
      .map((item) => (item.msg || '输入内容不符合要求').replace(/^Value error,\s*/i, ''))
      .join('；')
  }
  return '请求失败，请稍后重试'
}

/** Send an authenticated API request and attach CSRF proof to every mutation. */
export async function apiFetch(path, options = {}) {
  const context = captureApiContext()
  ensureCurrent(context)
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers || {})
  if (context.userId) headers.set('X-MPAU-User-ID', context.userId)
  if (needsAgent(path, method, options)) {
    headers.set('X-MPAU-Agent-Proof', await localAgentProof())
    ensureCurrent(context)
  }
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = cookieValue('mpau_csrf_v2')
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
  }

  const response = await sessionFetch(`${apiBase}${path}`, {
    ...options,
    method,
    headers,
    credentials: 'include',
    cache: 'no-store',
  })
  ensureCurrent(context)
  if (response.ok && context.userId && response.headers.get('X-MPAU-User-ID') !== context.userId) {
    unauthorizedHandler?.({ broadcast: false })
    throw new StaleSessionError()
  }
  return response
}

export async function apiRequest(path, options = {}) {
  const context = captureApiContext()
  const response = await apiFetch(path, options)
  const body = response.status === 204
    ? null
    : await response.json().catch(() => ({}))
  ensureCurrent(context)
  if (response.headers.get('X-MPAU-Session-Changed') === '1') {
    unauthorizedHandler?.({ broadcast: false })
    throw new StaleSessionError()
  }
  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler && !options.skipUnauthorizedHandler) {
      unauthorizedHandler()
    }
    const error = new Error(errorMessage(body || {}))
    error.status = response.status
    error.details = body || {}
    throw error
  }
  return body
}

/** Build an API URL for browser-native downloads such as Excel templates. */
export function apiUrl(path) {
  return `${apiBase}${path}`
}
