<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiRequest } from '../../api-client.js'

const profile = ref(null)
const error = ref('')
const loading = ref(false)
const busy = ref(false)
const editing = ref(null)
const revisions = ref([])
const historyOpen = ref(false)
const showRevoked = ref(false)
let disposed = false
let timer
let requestId = 0
const kinds = { background: '品牌背景', rule: '分析规则', goal: '阶段目标', preference: '用户偏好', correction: '纠正信息' }
const entries = computed(() => (profile.value?.entries || []).filter(e => showRevoked.value || e.state !== 'retracted'))
const status = computed(() => {
  if (!profile.value) return '正在读取品牌记忆…'
  if (!profile.value.enabled) return '长期记忆已关闭，当前使用近期对话'
  if (!profile.value.configured) return '请先启用 LLM 适配器，已有记忆仍可查看'
  const jobs = profile.value.jobs || {}
  if (jobs.running) return '正在提取长期记忆'
  if (jobs.pending || jobs.retry) return '等待更新长期记忆'
  if (jobs.failed) return '部分记忆更新失败，可重试'
  return profile.value.updated_at ? '长期记忆已更新' : '尚未提取到长期记忆'
})

async function load() {
  if (loading.value || busy.value || editing.value) return
  const id = ++requestId
  loading.value = true
  try {
    const result = await apiRequest('/api/dashboard/memory')
    if (!disposed && id === requestId) { profile.value = result; error.value = '' }
  } catch (e) {
    if (!disposed && id === requestId) error.value = e.message
  } finally { if (!disposed) loading.value = false }
}

function beginEdit(entry) {
  editing.value = { id: entry.id, version: profile.value.version, value: entry.value, period: entry.period || '', expires_on: entry.expires_on || '' }
}

async function change(path, method, body) {
  if (busy.value) return
  busy.value = true
  ++requestId
  error.value = ''
  try {
    const result = await apiRequest(`/api/dashboard/memory${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: body == null ? undefined : JSON.stringify(body) })
    if (!disposed) {
      profile.value = result; editing.value = null; revisions.value = []
      if (historyOpen.value) await loadRevisions()
    }
  } catch (e) {
    if (!disposed) error.value = e.message
  } finally { if (!disposed) busy.value = false }
}

function save() {
  const edit = editing.value
  return change(`/items/${edit.id}`, 'PATCH', { version: edit.version, value: edit.value.trim(), period: edit.period || null, expires_on: edit.expires_on || null })
}

async function loadRevisions() {
  const id = requestId
  try {
    const result = await apiRequest('/api/dashboard/memory/revisions')
    if (!disposed && id === requestId) revisions.value = result.revisions
  } catch (e) { if (!disposed && id === requestId) error.value = e.message }
}

function scope(entry) {
  return [entry.period || '跨周期', entry.content_type === 'image' ? '图文' : entry.content_type === 'video' ? '视频' : '全部内容', entry.tag_id, entry.expires_on && `截至 ${entry.expires_on}`].filter(Boolean).join(' · ')
}

onMounted(() => { load(); timer = setInterval(load, 5000) })
onUnmounted(() => { disposed = true; ++requestId; clearInterval(timer) })
</script>

<template>
  <section class="brand-memory-panel" aria-label="品牌记忆">
    <div class="memory-intro"><strong>{{ profile?.brand_name || '当前品牌' }} · 品牌记忆</strong><p>保存在当前账户的品牌档案中，可跨周期使用。用户提供的背景不代表已独立核实。</p><small role="status">{{ status }} · 版本 {{ profile?.version || 0 }}</small></div>
    <p v-if="error" class="memory-error" role="alert">{{ error }}</p>
    <div class="memory-actions"><button type="button" :disabled="loading || busy" @click="editing = null; load()">刷新</button><button v-if="profile?.jobs?.failed" type="button" :disabled="busy || !profile?.configured || !profile?.enabled" @click="change('/retry', 'POST')">重试更新</button><label><input v-model="showRevoked" type="checkbox">显示已撤销</label></div>
    <p v-if="!loading && !entries.length" class="memory-empty">暂无记忆。明确提供品牌背景、长期要求或阶段目标后，助手会在回答成功后后台整理。</p>
    <article v-for="entry in entries" :key="entry.id" class="memory-entry" :class="{ revoked: entry.state === 'retracted' }">
      <header><strong>{{ kinds[entry.kind] }}</strong><span>{{ entry.state === 'pending' ? '待澄清 · 暂不使用' : entry.state === 'retracted' ? '已撤销' : entry.manual ? '手动维护' : '有效' }}</span></header>
      <form v-if="editing?.id === entry.id" class="memory-edit" @submit.prevent="save">
        <label>记忆内容<textarea v-model="editing.value" maxlength="500" rows="4" required /></label>
        <label>适用周期<input v-model="editing.period" type="month"><small>留空表示跨周期；阶段目标必须有周期或结束日期。</small></label>
        <label>结束日期<input v-model="editing.expires_on" type="date"></label>
        <div><button type="submit" :disabled="busy || !editing.value.trim()">保存</button><button type="button" :disabled="busy" @click="editing = null">取消</button></div>
      </form>
      <template v-else><p>{{ entry.value }}</p><small>{{ scope(entry) }}</small><div class="memory-entry-actions"><button type="button" :disabled="busy" @click="beginEdit(entry)">{{ entry.state === 'retracted' ? '编辑并恢复' : '编辑' }}</button><button v-if="entry.state !== 'retracted'" type="button" :disabled="busy" @click="change(`/items/${entry.id}`, 'DELETE', { version: profile.version })">撤销</button></div></template>
      <details><summary>查看来源</summary><blockquote>{{ entry.source?.quote || entry.source_quote }}</blockquote><small>来源消息 {{ entry.source?.message_id || entry.source_message_id }} · 分析周期 {{ entry.source?.period || '未指定' }}<br>原消息时间 {{ entry.source?.created_at || '—' }}（UTC）<br>记忆更新 {{ entry.updated_at }}</small><p v-if="entry.manual">当前内容由你维护，自动提取不会覆盖。来源显示的是最初提取依据。</p></details>
    </article>
    <details class="memory-history" @toggle="event => { historyOpen = event.target.open; if (historyOpen) loadRevisions() }"><summary>版本历史</summary><p>恢复旧版本会取消旧提取任务；被移除的记忆保留撤销状态。</p><div v-for="revision in revisions" :key="revision.version"><span>版本 {{ revision.version }} · {{ revision.reason }}</span><button v-if="revision.version !== profile?.version" type="button" :disabled="busy" @click="change('/rollback', 'POST', { version: profile.version, target_version: revision.version })">恢复此版本</button></div></details>
  </section>
</template>

<style scoped>
.brand-memory-panel { flex: 1; min-height: 0; overflow-y: auto; padding: 16px; color: #365a3e; font-size: 12px; }
.memory-intro p, .memory-entry p { line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.memory-intro small, .memory-entry small { color: #657766; line-height: 1.6; }
.memory-actions, .memory-entry-actions, .memory-edit > div { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 12px 0; }
button { padding: 6px 10px; border: 1px solid #cbd8bf; border-radius: 6px; background: #f4f8e9; color: #365a3e; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
.memory-entry { margin: 12px 0; padding: 12px; border: 1px solid #dce6d4; border-radius: 10px; background: white; }
.memory-entry header { display: flex; justify-content: space-between; gap: 8px; }
.memory-entry header span { color: #718369; }
.memory-entry.revoked { background: #f2f3ef; }
.memory-entry blockquote { margin: 10px 0; padding-left: 10px; border-left: 3px solid #d5dfbb; white-space: pre-wrap; overflow-wrap: anywhere; }
.memory-edit { display: grid; gap: 10px; margin-top: 10px; }
.memory-edit label { display: grid; gap: 4px; }
.memory-edit textarea, .memory-edit input { box-sizing: border-box; width: 100%; padding: 8px; border: 1px solid #cbd8bf; border-radius: 6px; font: inherit; }
.memory-error { color: #9e342d; }
.memory-empty { padding: 20px 0; color: #6b7e65; line-height: 1.7; }
.memory-history { margin-top: 20px; }
.memory-history > div { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin: 10px 0; }
</style>
