import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { captureApiContext, isApiContextCurrent, setApiSession } from './api-client.js'

const require = createRequire(import.meta.url)
const compiler = createRequire(require.resolve('vue/compiler-sfc')).resolve('@vue/compiler-sfc')
const { parse } = createRequire(compiler)('@babel/parser')
globalThis.document = { cookie: 'mpau_csrf_v2=test-csrf' }
const source = fs.readFileSync(new URL('./App.vue', import.meta.url), 'utf8').split('<script setup>')[1].split('</script>')[0]
const program = parse(source, { sourceType: 'module' }).program
const ref = value => ({ value })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function action(name, scope) {
  const node = program.body.find(item => item.type === 'FunctionDeclaration' && item.id.name === name)
  const values = { captureApiContext, isApiContextCurrent, ...scope }
  return new Function(...Object.keys(values), `${source.slice(node.start, node.end)}; return ${name}`)(...Object.values(values))
}

test('old task details cannot populate a newer user UI', async () => {
  setApiSession('A', { broadcast: false })
  const pending = deferred()
  const selectedJob = ref(null), jobLogs = ref([])
  const loadJob = action('loadJob', { request: () => pending.promise, selectedJob,
    jobLogs, selectedBatch: ref(null), activeView: ref('publish') })
  const running = loadJob('A-job')
  setApiSession('B', { broadcast: false })
  pending.resolve({ job: { id: 'A-job' }, logs: ['A-private-log'] })
  await running
  assert.equal(selectedJob.value, null)
  assert.deepEqual(jobLogs.value, [])
})

test('old agent response cannot overwrite the current connection state', async () => {
  setApiSession('A', { broadcast: false })
  const pending = deferred()
  const agentStatus = { online: false, deviceName: 'B-PC', checking: false }
  let applied = 0
  const refresh = action('refreshAgentStatus', {
    request: () => pending.promise, agentStatus, applyAgentStatus: () => { applied += 1 },
  })
  const running = refresh()
  setApiSession('B', { broadcast: false })
  agentStatus.checking = false
  pending.resolve({ online: true, agents: [{ device_name: 'A-PC' }] })
  await running
  assert.equal(applied, 0)
  assert.equal(agentStatus.deviceName, 'B-PC')
  assert.equal(agentStatus.checking, false)
})

test('an account action waiting for connection cannot submit after switching users', async () => {
  setApiSession('A', { broadcast: false })
  const pending = deferred()
  let writes = 0
  const accountAction = action('accountAction', { requireOnlineAgent: () => pending.promise,
    request: async () => { writes += 1 }, showNotice() {}, form: { platform: 'jd', account: 'shop' } })
  const running = accountAction('login')
  setApiSession('B', { broadcast: false })
  pending.resolve(true)
  await running
  assert.equal(writes, 0)
})

test('switching users clears every in-memory media workspace while keeping saved drafts separate', () => {
  const workspaceMedia = {
    tmall_video: { video: 'A-video', images: [], coverImage: 'A-cover' },
    jd_article: { video: null, images: ['A-image'], coverImage: null },
  }
  const node = program.body.find(item => item.type === 'FunctionDeclaration' && item.id.name === 'resetUserInterface')
  const names = [...source.slice(node.start, node.end).matchAll(/\b(\w+)\.value\b/g)].map(item => item[1])
  const scope = Object.fromEntries(names.map(name => [name, ref('A-state')]))
  Object.assign(scope, { workspaceMedia, workspaceDrafts: { tmall_video: {} },
    form: {}, batchForm: {}, agentStatus: {}, persistTimer: null, dashboardRefreshPromise: null,
    window: { clearTimeout() {} }, createEmptyWorkspaceDraft: () => ({}),
  })
  action('resetUserInterface', scope)()
  assert.equal(workspaceMedia.tmall_video.video, null)
  assert.equal(workspaceMedia.tmall_video.coverImage, null)
  assert.deepEqual(workspaceMedia.jd_article.images, [])
  assert.equal(scope.submitting.value, false)
})
