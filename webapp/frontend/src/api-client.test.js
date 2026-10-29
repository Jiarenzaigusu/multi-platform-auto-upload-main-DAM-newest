import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'
import { apiRequest, configureApiClient, setApiSession, StaleSessionError } from './api-client.js'

let unauthorized = 0
const storageListeners = []
globalThis.window = { addEventListener: (event, listener) => { if (event === 'storage') storageListeners.push(listener) } }
globalThis.document = { cookie: 'mpau_csrf_v2=test-csrf' }
globalThis.localStorage = { setItem() {} }
const reply = (payload, status = 200, owner = 'A') => new Response(JSON.stringify(payload), {
  status, headers: { 'Content-Type': 'application/json', 'X-MPAU-User-ID': owner },
})
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

beforeEach(() => {
  unauthorized = 0
  document.cookie = 'mpau_csrf_v2=test-csrf'
  setApiSession('A', { broadcast: false })
  configureApiClient({ onUnauthorized: () => { unauthorized += 1 } })
})

test('late old-user response is rejected even if fetch ignores cancellation', async () => {
  const pending = deferred()
  globalThis.fetch = () => pending.promise
  const request = apiRequest('/api/jobs')
  setApiSession('B', { broadcast: false })
  pending.resolve(reply({ jobs: ['A-secret'] }))
  await assert.rejects(request, StaleSessionError)
  assert.equal(unauthorized, 0)
})

test('logging out and back into the same user invalidates old requests', async () => {
  const pending = deferred()
  globalThis.fetch = () => pending.promise
  const request = apiRequest('/api/jobs')
  setApiSession(null, { broadcast: false })
  setApiSession('A', { broadcast: false })
  pending.resolve(reply({ jobs: ['old-session'] }))
  await assert.rejects(request, StaleSessionError)
})

test('session changes during JSON parsing cannot deliver old data', async () => {
  const body = deferred(), started = deferred()
  globalThis.fetch = async () => ({ ok: true, status: 200,
    headers: new Headers({ 'X-MPAU-User-ID': 'A' }),
    json: () => { started.resolve(); return body.promise },
  })
  const request = apiRequest('/api/jobs')
  await started.promise
  setApiSession('B', { broadcast: false })
  body.resolve({ jobs: ['old'] })
  await assert.rejects(request, StaleSessionError)
})

test('a late 401 cannot log out a newer session', async () => {
  const pending = deferred()
  globalThis.fetch = () => pending.promise
  const request = apiRequest('/api/jobs')
  setApiSession('B', { broadcast: false })
  pending.resolve(reply({ detail: 'expired' }, 401))
  await assert.rejects(request, StaleSessionError)
  assert.equal(unauthorized, 0)
})

test('wrong cached owner is rejected before its body is read', async () => {
  let parsed = false
  globalThis.fetch = async () => ({ ok: true, status: 200,
    headers: new Headers({ 'X-MPAU-User-ID': 'B' }),
    json: async () => { parsed = true; return { secret: true } },
  })
  await assert.rejects(apiRequest('/api/jobs'), StaleSessionError)
  assert.equal(parsed, false)
  assert.equal(unauthorized, 1)
})

test('a local job requires a proof returned through the local helper', async () => {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push([url, options])
    if (url === '/api/agent/local-identity/challenge') return reply({ ticket: 'challenge' })
    if (url.startsWith('http://127.0.0.1:48765/v1/identity')) return reply({ proof: 'verified-proof', agent_id: 'device-A' })
    return reply({ job: { id: 'job-A' } })
  }
  const result = await apiRequest('/api/accounts/jd/shop/login', { method: 'POST' })
  assert.equal(result.job.id, 'job-A')
  assert.equal(calls.length, 3)
  const headers = calls[2][1].headers
  assert.equal(headers.get('X-MPAU-Agent-Proof'), 'verified-proof')
  assert.equal(headers.get('X-MPAU-User-ID'), 'A')
  assert.equal(headers.get('X-CSRF-Token'), 'test-csrf')
})

test('wrong local helper prevents job creation', async () => {
  let writes = 0
  globalThis.fetch = async (url) => {
    if (url === '/api/agent/local-identity/challenge') return reply({ ticket: 'challenge' })
    if (url.startsWith('http://127.0.0.1:48765/')) return reply({ detail: 'wrong helper' }, 403)
    writes += 1
    return reply({})
  }
  await assert.rejects(apiRequest('/api/accounts/jd/shop/login', { method: 'POST' }), /wrong helper/)
  assert.equal(writes, 0)
})

test('changing session during helper verification prevents the mutation', async () => {
  const pending = deferred(), started = deferred()
  let writes = 0
  globalThis.fetch = async (url) => {
    if (url === '/api/agent/local-identity/challenge') return reply({ ticket: 'challenge' })
    if (url.startsWith('http://127.0.0.1:48765/')) { started.resolve(); return pending.promise }
    writes += 1
    return reply({})
  }
  const request = apiRequest('/api/accounts/jd/shop/login', { method: 'POST' })
  await started.promise
  setApiSession('B', { broadcast: false })
  pending.resolve(reply({ proof: 'old-proof' }))
  await assert.rejects(request, StaleSessionError)
  assert.equal(writes, 0)
})

test('cross-tab identity change invalidates the current UI', () => {
  storageListeners[0]({ key: 'mpau_auth_session_event_v1', newValue: JSON.stringify({ userId: 'B' }) })
  assert.equal(unauthorized, 1)
})

test('same-user login in another tab invalidates the old cookie context before a write', async () => {
  let writes = 0
  globalThis.fetch = async () => { writes += 1; return reply({}) }
  document.cookie = 'mpau_csrf_v2=replaced-session-csrf'
  await assert.rejects(apiRequest('/api/media', { method: 'POST' }), StaleSessionError)
  assert.equal(writes, 0)
  assert.equal(unauthorized, 1)
})
