<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createAiCopyApi } from './api.js'
import AiCopyView from './AiCopyView.vue'
const props = defineProps({ userId: String, canModerate: Boolean, active: Boolean })
const emit = defineEmits(['import-to-workbench'])
const api = createAiCopyApi()
const brands = ref([])
const selected = ref('')
const profileOpen = ref(false)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const saving = ref(false)
const managing = ref(false)
const editingId = ref('')
const editVersion = ref(0)
const name = ref('')
const enabled = ref(true)
let closed = false
let loadEpoch = 0
const selectionKey = `mpau_copy_brand_v1:${props.userId}`
function editBrand(brand) {
  editingId.value = brand?.id || ''
  editVersion.value = brand?.version || 0
  name.value = brand?.name || ''
  enabled.value = brand?.enabled ?? true
  error.value = ''
  notice.value = ''
  managing.value = true
}
async function load(preferred = '') {
  const epoch = ++loadEpoch
  loading.value = true
  error.value = ''
  try {
    const response = await api.brands()
    if (closed || epoch !== loadEpoch) return false
    brands.value = response.brands
    let remembered = preferred || selected.value
    try { remembered ||= localStorage.getItem(selectionKey) || '' } catch { /* Storage may be unavailable. */ }
    selected.value = brands.value.some(b => b.id === remembered && b.enabled) ? remembered : ''
    return true
  } catch (exc) { if (!closed && epoch === loadEpoch) error.value = exc.message; return false }
  finally { if (!closed && epoch === loadEpoch) loading.value = false }
}
function mergeBrand(brand) {
  const index = brands.value.findIndex(b => b.id === brand.id)
  if (index >= 0) brands.value.splice(index, 1, { ...brands.value[index], ...brand })
  else brands.value.push(brand)
  brands.value.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
  selected.value = brand.enabled ? brand.id : ''
}
async function save() {
  if (saving.value || !name.value.trim()) return
  saving.value = true
  error.value = ''
  notice.value = ''
  // Invalidate an older refresh so it cannot overwrite the newly created brand.
  loadEpoch += 1
  loading.value = false
  try {
    const payload = editingId.value
      ? { name: name.value, enabled: enabled.value, version: editVersion.value }
      : { name: name.value }
    const brand = await api.saveBrand(editingId.value, payload)
    if (closed) return
    mergeBrand(brand)
    managing.value = false
    notice.value = editingId.value ? '品牌已更新。' : `已创建并选中「${brand.name}」。`
  } catch (exc) {
    if (closed) return
    const existing = exc.details?.existing_brand
    if (!editingId.value && exc.status === 409 && existing?.enabled) {
      mergeBrand(existing)
      managing.value = false
      notice.value = `品牌已存在，已为你选中「${existing.name}」。`
    } else error.value = exc.message
  } finally { if (!closed) saving.value = false }
}
watch(selected, value => { try { localStorage.setItem(selectionKey, value) } catch { /* Optional local state. */ } })
onMounted(() => load())
onBeforeUnmount(() => { closed = true; loadEpoch += 1 })
</script>
<template>
  <section class="copy-studio">
  <section class="copy-brand-bar" aria-label="文案品牌选择">
    <div class="brand-actions">
      <label>文案品牌 <select v-model="selected" :disabled="loading || saving" aria-label="选择文案品牌">
        <option value="">{{ loading ? '正在读取品牌…' : '请选择品牌' }}</option>
        <option v-for="brand in brands.filter(b => b.enabled)" :key="brand.id" :value="brand.id">{{ brand.name }}</option>
      </select></label>
      <button type="button" :disabled="loading || saving" @click="load()">刷新品牌</button>
      <button type="button" :disabled="loading || saving" @click="editBrand(null)">新增品牌</button>
      <button v-if="canModerate && selected" type="button" :disabled="loading || saving" @click="editBrand(brands.find(b => b.id === selected))">管理当前品牌</button>
      <button class="copy-profile-launch" type="button" :disabled="!selected || loading || saving"
        :aria-expanded="profileOpen && Boolean(selected)" aria-controls="copy-brand-profile" @click="profileOpen = !profileOpen">品牌画像</button>
    </div>
    <details v-if="canModerate && brands.some(b => !b.enabled)"><summary>已停用品牌</summary><button v-for="b in brands.filter(b => !b.enabled)" :key="b.id" type="button" :disabled="loading || saving" @click="editBrand(b)">{{ b.name }} · 管理</button></details>
    <p>同品牌共享选用样本与已确认偏好；导入发布台后自动积累样本。</p>
    <p v-if="!loading && !brands.some(b => b.enabled) && !error" class="brand-empty">暂无可选品牌，点击“新增品牌”即可创建。</p>
    <p v-if="error" role="alert" class="brand-error">{{ error }}</p>
    <p v-if="notice" role="status" class="brand-notice">{{ notice }}</p>
    <form v-if="managing" @submit.prevent="save">
      <strong>{{ editingId ? '管理文案品牌' : '新增文案品牌' }}</strong>
      <label>品牌名称 <input v-model="name" required maxlength="80" :disabled="saving" aria-label="品牌名称" placeholder="输入品牌名称" /></label>
      <label v-if="editingId"><input v-model="enabled" type="checkbox" :disabled="saving" />启用品牌</label>
      <div><button :disabled="saving || !name.trim()" type="submit">{{ saving ? '保存中…' : editingId ? '保存品牌' : '创建并选中' }}</button><button :disabled="saving" type="button" @click="managing = false">取消</button></div>
    </form>
  </section>
  <AiCopyView v-if="selected" :key="userId + ':' + selected" :user-id="userId" :active="active" v-model:profile-open="profileOpen"
    :brand-id="selected" :brand-name="brands.find(b => b.id === selected)?.name || ''" :can-moderate="canModerate"
    @import-to-workbench="emit('import-to-workbench', $event)" />
  <p v-else class="copy-brand-empty">请先从上方下拉框选择品牌，或点击“新增品牌”创建。选择后即可生成文案。</p>
  </section>
</template>
<style scoped>
.copy-studio { min-width:0; }
.copy-profile-launch { margin-left:auto; font-weight:750; }
.copy-brand-bar { background:#f7f9f3; border:1px solid #d9e1d3; border-radius:12px; padding:12px 16px; margin-bottom:16px; color:#263d31; }
.brand-actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.copy-brand-bar label { display:inline-flex; align-items:center; gap:8px; margin:4px 12px 4px 0; font-size:13px; }
select,input:not([type=checkbox]),button { padding:8px 12px; border:1px solid #cdd9c7; border-radius:7px; background:white; color:inherit; }
select { min-width:210px; max-width:100%; } button { margin:4px 0; cursor:pointer; } button:disabled { opacity:.5; cursor:wait; }
p,small { font-size:12px; line-height:1.7; margin:6px 0 0; } .brand-error { color:#a74332; } .brand-notice { color:#35613c; }
.brand-empty { padding:10px; border-radius:7px; background:#edf2e5; }
form { border-top:1px solid #d9e1d3; margin-top:12px; padding-top:12px; } form > strong { display:block; margin-bottom:10px; font-size:14px; } form button { margin-right:8px; }
.copy-brand-empty { padding:32px; text-align:center; color:#718073; }
@media (max-width:640px) { .brand-actions label { width:100%; } select { flex:1; min-width:0; } }
</style>
