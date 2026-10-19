<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createAiCopyApi } from './api.js'
const props = defineProps({ brandId: String, brandName: String, userId: String, canModerate: Boolean, refreshKey: Number, disabled: Boolean })
const emit = defineEmits(['restore'])
const api = createAiCopyApi(() => props.brandId)
const profile = ref(null)
const records = ref([])
const error = ref('')
const loading = ref(false)
const busy = ref(false)
const edits = ref({})
const broad = ref({})
let epoch = 0
let closed = false
const scopeLabel = { title: '标题', body: '正文', both: '标题与正文' }
async function load() {
  const current = ++epoch
  loading.value = true
  try {
    const [next, history] = await Promise.all([api.profile(), api.history()])
    if (closed || current !== epoch) return
    if (next.brand_id !== props.brandId || history.brand_id !== props.brandId) throw new Error('品牌不一致，请重新选择')
    profile.value = next
    records.value = history.records
  } catch (exc) { if (!closed && current === epoch) error.value = exc.message }
  finally { if (!closed && current === epoch) loading.value = false }
}
async function changePreference(p, status) {
  if (busy.value || props.disabled) return
  busy.value = true
  error.value = ''
  try {
    const saved = await api.preference(p.id, { expected_brand_id: props.brandId, version: profile.value.version, status, ...(status === 'active' ? { text: edits.value[p.id] ?? p.text, scope_mode: broad.value[p.id] ? 'brand' : 'source' } : {}) })
    if (!closed) profile.value = saved
  } catch (exc) { if (!closed) { error.value = exc.message; await load() } }
  finally { busy.value = false }
}
async function sampleAction(sample, analyze = false) {
  if (busy.value || props.disabled) return
  busy.value = true
  error.value = ''
  try {
    if (analyze) {
      const saved = await api.analyze(sample.id)
      if (saved.analysis_status === 'failed') error.value = '偏好分析未完成，选用样本仍已保存，可稍后重试。'
    } else await api.sample(sample.id, { expected_brand_id: props.brandId, version: profile.value.version, enabled: !sample.enabled })
    if (!closed) await load()
  } catch (exc) { if (!closed) error.value = exc.message }
  finally { busy.value = false }
}
async function restore(record) {
  if (busy.value || props.disabled) return
  busy.value = true
  try {
    const detail = await api.historyDetail(record.generation_id)
    if (!closed && detail.brand_id === props.brandId) emit('restore', detail)
  } catch (exc) { if (!closed) error.value = exc.message }
  finally { busy.value = false }
}
onMounted(load)
watch(() => props.refreshKey, load)
onBeforeUnmount(() => { closed = true; epoch += 1 })
</script>
<template>
  <details class="brand-copy-panel" open>
    <summary><strong>{{ brandName }} · 品牌写作画像</strong><span>同品牌共享</span></summary>
    <p class="memory-help">导入发布台成功后，实际导入的字段会自动成为品牌选用样本；这不代表已经发布。长期偏好确认后生效。</p>
    <p v-if="error" class="memory-error" role="alert">{{ error }}</p>
    <button type="button" :disabled="loading || busy || disabled" @click="load">{{ loading ? '读取中…' : '刷新画像' }}</button>
    <template v-if="profile">
      <p class="memory-help">已积累 {{ profile.sample_count }} 组选用样本 · {{ profile.preferences.filter(p => p.status === 'active').length }} 条生效偏好</p>
      <section>
        <b>已确认的品牌偏好</b>
        <p v-if="!profile.preferences.some(p => p.status === 'active')" class="memory-help">暂无；导入后的改稿可用于分析候选偏好。</p>
        <article v-for="p in profile.preferences.filter(p => p.status === 'active')" :key="p.id">
          <small>{{ scopeLabel[p.scope] }} · {{ Object.keys(p.conditions).length ? '来源场景与风格' : '本品牌所有场景与风格' }}</small><p>{{ p.text }}</p>
          <button :disabled="busy || disabled" @click="changePreference(p, 'disabled')">停用偏好</button>
        </article>
      </section>
      <section v-if="profile.preferences.some(p => p.status === 'pending')">
        <b>待确认偏好</b>
        <p class="memory-help">以下为模型提出的候选。请检查适用范围和含义，确认后才会影响同品牌后续生成。</p>
        <article v-for="p in profile.preferences.filter(p => p.status === 'pending')" :key="p.id">
          <small>{{ scopeLabel[p.scope] }} · 适用于来源文案的场景与风格</small><textarea :value="edits[p.id] ?? p.text" maxlength="300" rows="2" :disabled="busy || disabled" aria-label="候选偏好内容" @input="edits[p.id] = $event.target.value" />
          <blockquote v-if="p.source_quote">{{ p.source_quote }}</blockquote>
          <small v-else>依据已选用改稿推断，尚无用户原话佐证。</small>
          <label class="scope-choice"><input v-model="broad[p.id]" type="checkbox" :disabled="busy || disabled" />适用于本品牌所有场景与风格</label>
          <div><button :disabled="busy || disabled" @click="changePreference(p, 'active')">确认为品牌偏好</button><button :disabled="busy || disabled" @click="changePreference(p, 'rejected')">忽略</button></div>
        </article>
      </section>
      <details><summary>选用样本 · 最近 {{ profile.samples.length }} 组</summary>
        <article v-for="sample in profile.samples" :key="sample.id">
          <b>{{ sample.title }}</b><p v-if="sample.field_scope !== 'title'">{{ sample.body }}</p><small>{{ sample.source === 'workbench_import' ? '导入发布台选用 · ' : '历史手动采用 · ' }}{{ sample.field_scope === 'title' ? '仅标题 · ' : '标题与正文 · ' }}{{ sample.enabled ? '用于表达参考' : '已撤回' }}</small>
          <template v-if="sample.actor_id === userId || canModerate">
            <button :disabled="busy || disabled" @click="sampleAction(sample)">{{ sample.enabled ? '撤回样本及其偏好' : '恢复样本' }}</button>
            <button v-if="sample.enabled && sample.analysis_status !== 'complete'" :disabled="busy || disabled" @click="sampleAction(sample, true)">{{ busy ? '处理中…' : '分析偏好候选' }}</button>
          </template>
        </article>
      </details>
      <details><summary>最近文案</summary>
        <article v-for="record in records" :key="record.generation_id"><b>{{ record.title }}</b><p>{{ record.body }}</p>
          <button v-if="record.owner_id === userId" :disabled="busy || disabled" @click="restore(record)">继续编辑</button><small v-else>其他用户文案</small>
        </article>
      </details>
    </template>
  </details>
</template>
<style scoped>
.brand-copy-panel { margin-bottom:22px; padding:18px; border:1px solid #d9e1d3; border-radius:16px; background:#f7f9f3; color:#263d31; }
summary { cursor:pointer; } .brand-copy-panel > summary { display:flex; justify-content:space-between; gap:10px; font-size:15px; }
small,.brand-copy-panel > summary span { color:#718073; font-size:11px; }
.memory-help { color:#718073; font-size:12px; line-height:1.7; } .memory-error { color:#a74332; font-size:13px; }
section,details { margin-top:16px; } article { padding:12px 0; border-top:1px solid #dce4d6; }
article p,blockquote { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; line-height:1.7; }
blockquote { margin:8px 0; padding-left:10px; border-left:2px solid #cdd9c7; color:#718073; }
button { padding:6px 10px; margin:4px 6px 4px 0; border:1px solid #d0dcc9; border-radius:7px; background:#fff; color:#426147; cursor:pointer; font-size:12px; }
.scope-choice { display:block; font-size:12px; margin:10px 0; }
textarea { display:block; width:100%; box-sizing:border-box; margin:8px 0; padding:8px; border:1px solid #d0dcc9; border-radius:7px; font:inherit; }
button:disabled { opacity:.55; cursor:wait; }
</style>
