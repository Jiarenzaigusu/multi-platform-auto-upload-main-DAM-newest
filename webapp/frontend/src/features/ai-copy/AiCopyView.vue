<!--
  AiCopyView.vue：AI 文案工坊主视图。

  功能：
  - 通过 Excel 匹配商品核心卖点，或直接输入核心卖点（二选一）
  - 可选直接输入文案参考，与核心卖点共同参与生成
  - 调用 LLM 生成标题与正文（含风格/场景/节日/参考字数）
  - 复制结果或导入发布工作台

  参考字数：输入过程不夹紧、失焦时归位到默认值或合法范围，生成结果允许合理浮动。
  生成前必须所有商品 ID 都能在卖点表中匹配。
-->
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { createAiCopyApi } from './api.js'
import AiCopyDropdown from './AiCopyDropdown.vue'
import WorkbenchImportDialog from './WorkbenchImportDialog.vue'
import BrandCopyPanel from './BrandCopyPanel.vue'
import BrandProfileDrawer from './BrandProfileDrawer.vue'
import {
  clearAiCopyDraft, clearSellingPointWorkbook, loadSellingPointWorkbook, readAiCopyDraft,
  saveAiCopyDraft, saveSellingPointWorkbook,
} from './ai-copy-draft-store.js'

const props = defineProps({
  apiBase: { type: String, default: '' },
  active: { type: Boolean, default: false },
  userId: { type: String, default: '' },
  brandId: { type: String, default: '' },
  brandName: { type: String, default: '' },
  canModerate: { type: Boolean, default: false },
  profileOpen: { type: Boolean, default: false },
})
const emit = defineEmits(['import-to-workbench', 'update:profileOpen'])

const api = createAiCopyApi(() => props.brandId)
const options = ref({ styles: [], scenes: [], festivals: [], llm: { ready: false, model: '', provider: '' } })
const titleLimitPresets = [10, 15]
const bodyLimitPresets = [25, 50, 100, 200]
const titleCountPresets = [1, 3, 5]
const bodyCountPresets = [1, 2, 3]
const titleMin = 2
const titleMax = 100
const bodyMin = 10
const bodyMax = 1000
const candidateCountMin = 1
const candidateCountMax = 10
const titleLimitDefault = 15
const bodyLimitDefault = 100
const titleCountDefault = 1
const bodyCountDefault = 1
const hanCharacterPattern = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/g
const createDefaultForm = () => ({
  sellingPointInputMode: 'excel',
  productIdentifiers: '',
  manualSellingPoint: '',
  titleMaxChars: titleLimitDefault,
  bodyMaxChars: bodyLimitDefault,
  titleCount: titleCountDefault,
  bodyCount: bodyCountDefault,
  style: 'atmospheric_seeding',
  scene: 'daily_styling',
  festival: '',
  customStyle: '',
  customScene: '',
  customFestival: '',
  copyReference: '',
})
const form = reactive(createDefaultForm())
const loadingOptions = ref(true)
const uploadingSellingPoints = ref(false)
const readingProduct = ref(false)
const generating = ref(false)
const savingEdit = ref(false)
const rewriting = ref(false)
const feedbackText = ref('')
const feedbackTarget = ref('both')
const settingsOpen = ref(false)
const resultsPanel = ref(null)
const busy = computed(() => generating.value || savingEdit.value || rewriting.value || importingToBatchExcel.value || restoringDraft.value)
const memoryRefresh = ref(0)
let disposed = false
let pendingRewrite = null
const sellingPointCatalog = ref(null)
const productReferences = ref([])
const result = ref(null)
const error = ref('')
const success = ref('')
const copiedField = ref('')
const sellingPointFileInput = ref(null)
const batchExcelFileInput = ref(null)
const importingToBatchExcel = ref(false)
const downloadBatchExcelCopy = ref(false)
const selectedTitleIndex = ref(0)
const selectedBodyIndex = ref(0)
const editingTitleIndex = ref(null)
const editingBodyIndex = ref(null)
const titleEditValue = ref('')
const bodyEditValue = ref('')
const workbenchImportOpen = ref(false)
const restoringDraft = ref(true)
let draftSaveTimer
let copyTimer
let successTimer

const productIdentifiers = computed(() => {
  const identifiers = form.productIdentifiers
    .split(/[\s,，;；]+/)
    .map((value) => value.trim())
    .filter(Boolean)
  return [...new Map(identifiers.map((value) => [value.toLocaleLowerCase(), value])).values()]
})
const manualSellingPoint = computed(() => form.manualSellingPoint.trim())
const isManualSellingPointMode = computed(() => form.sellingPointInputMode === 'manual')
const sellingPointEntryMap = computed(() => new Map(
  (sellingPointCatalog.value?.entries || []).map((entry) => [
    entry.identifier.trim().toLocaleLowerCase(),
    entry,
  ]),
))
const matchedSellingPoints = computed(() => productIdentifiers.value
  .map((identifier) => sellingPointEntryMap.value.get(identifier.toLocaleLowerCase()))
  .filter(Boolean))
const missingProductIdentifiers = computed(() => productIdentifiers.value.filter(
  (identifier) => !sellingPointEntryMap.value.has(identifier.toLocaleLowerCase()),
))
const festivalOptions = computed(() => [
  { value: '', label: '不指定节日' },
  ...options.value.festivals.map((festival) => ({ value: festival, label: festival })),
])
const customSelectionValue = '__custom__'
const hasCustomStyle = computed(() => Boolean(form.customStyle.trim()))
const selectedScene = computed({
  get: () => (form.customScene.trim() ? customSelectionValue : form.scene),
  set: (value) => {
    form.scene = value
    form.customScene = ''
  },
})
const selectedFestival = computed({
  get: () => (form.customFestival.trim() ? customSelectionValue : form.festival),
  set: (value) => {
    form.festival = value
    form.customFestival = ''
  },
})

function normalizeTitleLimit(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return null
  return Math.min(titleMax, Math.max(titleMin, Math.round(numeric)))
}
function normalizeBodyLimit(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return null
  return Math.min(bodyMax, Math.max(bodyMin, Math.round(numeric)))
}
function normalizeCandidateCount(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return null
  return Math.min(candidateCountMax, Math.max(candidateCountMin, Math.round(numeric)))
}
function pickTitleLimit(value) {
  const normalized = normalizeTitleLimit(value)
  if (normalized === null) return
  form.titleMaxChars = normalized
}
function pickBodyLimit(value) {
  const normalized = normalizeBodyLimit(value)
  if (normalized === null) return
  form.bodyMaxChars = normalized
}
function pickTitleCount(value) {
  const normalized = normalizeCandidateCount(value)
  if (normalized !== null) form.titleCount = normalized
}
function pickBodyCount(value) {
  const normalized = normalizeCandidateCount(value)
  if (normalized !== null) form.bodyCount = normalized
}
function cleanNumericInput(raw) {
  // 只允许数字字符 + 空串；输入过程中不做夹紧，让用户能自由输入中间态。
  const cleaned = String(raw ?? '').replace(/[^\d]/g, '')
  return cleaned
}
function onTitleLimitInput(event) {
  const cleaned = cleanNumericInput(event.target.value)
  if (cleaned !== event.target.value) event.target.value = cleaned
  form.titleMaxChars = cleaned === '' ? '' : Number(cleaned)
}
function onBodyLimitInput(event) {
  const cleaned = cleanNumericInput(event.target.value)
  if (cleaned !== event.target.value) event.target.value = cleaned
  form.bodyMaxChars = cleaned === '' ? '' : Number(cleaned)
}
function onTitleCountInput(event) {
  const cleaned = cleanNumericInput(event.target.value)
  if (cleaned !== event.target.value) event.target.value = cleaned
  form.titleCount = cleaned === '' ? '' : Number(cleaned)
}
function onBodyCountInput(event) {
  const cleaned = cleanNumericInput(event.target.value)
  if (cleaned !== event.target.value) event.target.value = cleaned
  form.bodyCount = cleaned === '' ? '' : Number(cleaned)
}
function onTitleLimitBlur() {
  if (form.titleMaxChars === '' || form.titleMaxChars === null) {
    // 留空 = 不覆盖，回退到初始默认值
    form.titleMaxChars = titleLimitDefault
    return
  }
  const normalized = normalizeTitleLimit(form.titleMaxChars)
  form.titleMaxChars = normalized === null ? titleLimitDefault : normalized
}
function onBodyLimitBlur() {
  if (form.bodyMaxChars === '' || form.bodyMaxChars === null) {
    form.bodyMaxChars = bodyLimitDefault
    return
  }
  const normalized = normalizeBodyLimit(form.bodyMaxChars)
  form.bodyMaxChars = normalized === null ? bodyLimitDefault : normalized
}
function onTitleCountBlur() {
  const normalized = normalizeCandidateCount(form.titleCount)
  form.titleCount = normalized === null ? titleCountDefault : normalized
}
function onBodyCountBlur() {
  const normalized = normalizeCandidateCount(form.bodyCount)
  form.bodyCount = normalized === null ? bodyCountDefault : normalized
}
// 仅在数值非空且越界时算 invalid，避免输入过程显示提示
const titleLimitValid = computed(() => {
  if (form.titleMaxChars === '' || form.titleMaxChars === null) return true
  const value = Number(form.titleMaxChars)
  return Number.isFinite(value) && value >= titleMin && value <= titleMax
})
const bodyLimitValid = computed(() => {
  if (form.bodyMaxChars === '' || form.bodyMaxChars === null) return true
  const value = Number(form.bodyMaxChars)
  return Number.isFinite(value) && value >= bodyMin && value <= bodyMax
})
const titleCountValid = computed(() => {
  if (form.titleCount === '' || form.titleCount === null) return true
  const value = Number(form.titleCount)
  return Number.isFinite(value) && value >= candidateCountMin && value <= candidateCountMax
})
const bodyCountValid = computed(() => {
  if (form.bodyCount === '' || form.bodyCount === null) return true
  const value = Number(form.bodyCount)
  return Number.isFinite(value) && value >= candidateCountMin && value <= candidateCountMax
})

const resultTitleMax = computed(() => {
  if (!result.value) return form.titleMaxChars || 30
  const fromResponse = Number(result.value.title_max_chars)
  return Number.isFinite(fromResponse) && fromResponse > 0 ? fromResponse : (form.titleMaxChars || 30)
})
const resultBodyMax = computed(() => {
  if (!result.value) return form.bodyMaxChars || 1000
  const fromResponse = Number(result.value.body_max_chars)
  return Number.isFinite(fromResponse) && fromResponse > 0 ? fromResponse : (form.bodyMaxChars || 1000)
})
const resultTitles = computed(() => {
  if (!result.value) return []
  return result.value.titles?.length ? result.value.titles : [result.value.title]
})
const resultBodies = computed(() => {
  if (!result.value) return []
  return result.value.bodies?.length ? result.value.bodies : [result.value.body]
})
const selectedTitle = computed(() => resultTitles.value[selectedTitleIndex.value] || resultTitles.value[0] || '')
const selectedBody = computed(() => resultBodies.value[selectedBodyIndex.value] || resultBodies.value[0] || '')
function countHanCharacters(text) {
  return (String(text || '').match(hanCharacterPattern) || []).length
}

function resetEditState() {
  editingTitleIndex.value = null
  editingBodyIndex.value = null
  titleEditValue.value = ''
  bodyEditValue.value = ''
}

function beginEditTitle(index) {
  selectedTitleIndex.value = index
  editingTitleIndex.value = index
  titleEditValue.value = resultTitles.value[index] || ''
}

function beginEditBody(index) {
  selectedBodyIndex.value = index
  editingBodyIndex.value = index
  bodyEditValue.value = resultBodies.value[index] || ''
}

function cancelEditTitle() {
  editingTitleIndex.value = null
  titleEditValue.value = ''
}

function cancelEditBody() {
  editingBodyIndex.value = null
  bodyEditValue.value = ''
}

async function saveEditedCandidate(kind, index, rawValue) {
  const value = rawValue.trim()
  if (!value) {
    error.value = '标题或文案不能为空'
    return false
  }
  if (busy.value) return false
  if (!result.value?.generation_id || result.value.brand_id !== props.brandId) {
    error.value = '这条草稿尚未关联当前品牌历史，请重新生成后保存修改'
    return false
  }
  const generationId = result.value.generation_id
  savingEdit.value = true
  try {
    const saved = await api.saveEdit(generationId, {
      expected_brand_id: props.brandId, version: result.value.revision,
      field: kind, index, text: value,
    })
    if (disposed || result.value?.generation_id !== generationId) return false
    Object.assign(result.value, saved)
    memoryRefresh.value += 1
    error.value = ''
    showSuccess('修改已保存；导入发布台后会自动加入品牌选用样本')
    return true
  } catch (requestError) {
    error.value = requestError.message
    return false
  } finally {
    savingEdit.value = false
  }
}

async function saveEditedTitle(index) {
  if (!await saveEditedCandidate('title', index, titleEditValue.value)) return false
  selectedTitleIndex.value = index
  cancelEditTitle()
  return true
}

async function saveEditedBody(index) {
  if (!await saveEditedCandidate('body', index, bodyEditValue.value)) return false
  selectedBodyIndex.value = index
  cancelEditBody()
  return true
}

async function saveActiveEdits() {
  if (busy.value) return false
  if (editingTitleIndex.value !== null && !await saveEditedTitle(editingTitleIndex.value)) return false
  if (editingBodyIndex.value !== null && !await saveEditedBody(editingBodyIndex.value)) return false
  return true
}

const canGenerate = computed(() => (
  (isManualSellingPointMode.value
    ? manualSellingPoint.value.length > 0
    : Boolean(sellingPointCatalog.value)
      && productIdentifiers.value.length >= 1
      && productIdentifiers.value.length <= 20
      && missingProductIdentifiers.value.length === 0)
  && titleLimitValid.value
  && bodyLimitValid.value
  && titleCountValid.value
  && bodyCountValid.value
  && !uploadingSellingPoints.value
  && !readingProduct.value
  && !generating.value
  && !busy.value
  && Boolean(props.brandId)
  && !loadingOptions.value
))

function clearFeedback() {
  error.value = ''
  success.value = ''
  copiedField.value = ''
  window.clearTimeout(successTimer)
}

function switchSellingPointInputMode(mode) {
  if (mode === form.sellingPointInputMode || generating.value || uploadingSellingPoints.value) return
  form.sellingPointInputMode = mode
  result.value = null
  resetEditState()
  clearFeedback()
}

function showSuccess(message) {
  window.clearTimeout(successTimer)
  success.value = message
  successTimer = window.setTimeout(() => { success.value = '' }, 2000)
}

function clearAll() {
  if (busy.value || readingProduct.value || uploadingSellingPoints.value) return
  const catalogId = sellingPointCatalog.value?.catalog_id
  if (catalogId) api.deleteSellingPointCatalog(catalogId).catch(() => {})
  Object.assign(form, createDefaultForm())
  sellingPointCatalog.value = null
  productReferences.value = []
  result.value = null
  resetEditState()
  error.value = ''
  copiedField.value = ''
  window.clearTimeout(copyTimer)
  window.clearTimeout(successTimer)
  if (sellingPointFileInput.value) sellingPointFileInput.value.value = ''
  clearAiCopyDraft(props.userId, props.brandId)
  clearSellingPointWorkbook(props.userId, props.brandId).catch(() => {})
}

function chooseSellingPointFile() {
  if (!uploadingSellingPoints.value) sellingPointFileInput.value?.click()
}

async function uploadSellingPointFile(file, { persist = true, preserveResult = false } = {}) {
  if (!file) return
  clearFeedback()
  uploadingSellingPoints.value = true
  try {
    const uploaded = await api.uploadSellingPoints(file)
    if (disposed) return
    const previousCatalogId = sellingPointCatalog.value?.catalog_id
    sellingPointCatalog.value = uploaded
    if (!preserveResult) {
      result.value = null
      resetEditState()
    }
    if (persist) await saveSellingPointWorkbook(file, props.userId, props.brandId)
    if (previousCatalogId && previousCatalogId !== uploaded.catalog_id) {
      api.deleteSellingPointCatalog(previousCatalogId).catch(() => {})
    }
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    uploadingSellingPoints.value = false
  }
}

async function uploadSellingPointCatalog(event) {
  try {
    await uploadSellingPointFile(event.target.files?.[0])
  } finally {
    event.target.value = ''
  }
}

function clearSellingPointCatalog() {
  if (uploadingSellingPoints.value || busy.value) return
  const catalogId = sellingPointCatalog.value?.catalog_id
  if (catalogId) api.deleteSellingPointCatalog(catalogId).catch(() => {})
  sellingPointCatalog.value = null
  result.value = null
  resetEditState()
  error.value = ''
  clearSellingPointWorkbook(props.userId, props.brandId).catch(() => {})
  if (sellingPointFileInput.value) sellingPointFileInput.value.value = ''
}

async function loadOptions() {
  loadingOptions.value = true
  try {
    options.value = await api.options()
  } catch (requestError) {
    error.value = `无法加载 AI 文案配置：${requestError.message}`
  } finally {
    loadingOptions.value = false
  }
}

async function generateCopy() {
  if (busy.value) return
  if (!await saveActiveEdits()) return
  clearFeedback()
  if (!props.brandId) {
    error.value = '请先选择文案品牌'
    return
  }
  if (isManualSellingPointMode.value) {
    if (!manualSellingPoint.value) {
      error.value = '请填写商品核心卖点'
      return
    }
  } else {
    if (!sellingPointCatalog.value) {
      error.value = '请先上传商品核心卖点 Excel'
      return
    }
    if (!productIdentifiers.value.length) {
      error.value = '请至少输入一个商品 ID 或货号'
      return
    }
    if (productIdentifiers.value.length > 20) {
      error.value = '一次最多支持 20 个商品 ID 或货号'
      return
    }
  }
  if (!isManualSellingPointMode.value && missingProductIdentifiers.value.length) {
    error.value = `Excel 中未找到：${missingProductIdentifiers.value.join('、')}`
    return
  }
  if (!titleLimitValid.value) {
    error.value = `标题参考字数必须在 ${titleMin}-${titleMax} 之间`
    return
  }
  if (!bodyLimitValid.value) {
    error.value = `文案参考字数必须在 ${bodyMin}-${bodyMax} 之间`
    return
  }
  if (!titleCountValid.value) {
    error.value = `标题生成个数必须在 ${candidateCountMin}-${candidateCountMax} 之间`
    return
  }
  if (!bodyCountValid.value) {
    error.value = `文案生成个数必须在 ${candidateCountMin}-${candidateCountMax} 之间`
    return
  }
  generating.value = true
  const titleLimit = form.titleMaxChars === '' || form.titleMaxChars === null
    ? null
    : Number(form.titleMaxChars)
  const bodyLimit = form.bodyMaxChars === '' || form.bodyMaxChars === null
    ? null
    : Number(form.bodyMaxChars)
  const titleCount = form.titleCount === '' || form.titleCount === null
    ? titleCountDefault
    : Number(form.titleCount)
  const bodyCount = form.bodyCount === '' || form.bodyCount === null
    ? bodyCountDefault
    : Number(form.bodyCount)
  try {
    const response = await api.generate({
      expected_brand_id: props.brandId,
      selling_point_input_mode: form.sellingPointInputMode,
      selling_point_catalog_id: isManualSellingPointMode.value ? null : sellingPointCatalog.value.catalog_id,
      product_identifiers: isManualSellingPointMode.value ? [] : productIdentifiers.value,
      manual_selling_point: isManualSellingPointMode.value ? manualSellingPoint.value : null,
      style: hasCustomStyle.value ? null : form.style,
      scene: form.customScene.trim() ? null : form.scene,
      festival: form.customFestival.trim() ? null : (form.festival.trim() || null),
      custom_style: form.customStyle.trim() || null,
      custom_scene: form.customScene.trim() || null,
      custom_festival: form.customFestival.trim() || null,
      copy_reference: form.copyReference.trim() || null,
      title_max_chars: titleLimit,
      body_max_chars: bodyLimit,
      title_count: titleCount,
      body_count: bodyCount,
    })
    if (disposed) return
    if (response.brand_id !== props.brandId) throw new Error('文案品牌不一致，请重新选择')
    result.value = response
    memoryRefresh.value += 1
    selectedTitleIndex.value = 0
    selectedBodyIndex.value = 0
    resetEditState()
    productReferences.value = response.product_references || []
    feedbackText.value = ''
    settingsOpen.value = false
    await revealResults()
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    generating.value = false
  }
}

async function copyText(field, value) {
  const text = String(value ?? '')
  if (!text) return
  let copied = false
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      copied = true
    }
  } catch {
    // 非安全上下文或浏览器拒绝权限时，继续尝试兼容方案。
  }
  if (!copied) {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      copied = document.execCommand('copy')
    } finally {
      document.body.removeChild(textarea)
    }
  }
  if (!copied) {
    error.value = '浏览器未授予剪贴板权限，请手动选择文字复制'
    return
  }
  copiedField.value = field
  window.clearTimeout(copyTimer)
  copyTimer = window.setTimeout(() => { copiedField.value = '' }, 1800)
}

async function importToWorkbench() {
  if (!await saveActiveEdits()) return
  if (!result.value || !selectedTitle.value || !selectedBody.value) return
  workbenchImportOpen.value = true
}

async function confirmWorkbenchImport(target) {
  if (!await saveActiveEdits()) return
  if (!result.value || !selectedTitle.value || !selectedBody.value) return
  emit('import-to-workbench', {
    title: selectedTitle.value,
    body: selectedBody.value,
    platform: target.platform,
    contentType: target.contentType,
    origin: {
      generation_id: result.value.generation_id, expected_brand_id: props.brandId,
      version: result.value.revision, title_index: selectedTitleIndex.value, body_index: selectedBodyIndex.value,
    },
  })
  workbenchImportOpen.value = false
}

async function chooseBatchExcelFile() {
  if (!await saveActiveEdits()) return
  if (!result.value) {
    error.value = '请先生成文案，再导入到批量发布 Excel'
    return
  }
  if (!outputProductIdentifiers.value.length) {
    error.value = '当前文案没有商品 ID，无法按商品 ID 导入批量发布表格'
    return
  }
  if (importingToBatchExcel.value) return
  if (downloadBatchExcelCopy.value) {
    batchExcelFileInput.value?.click()
    return
  }
  openAndImportBatchExcel()
}

// 默认路径：通过 File System Access API 将结果写回用户选择的原文件。
async function openAndImportBatchExcel() {
  let handles
  try {
    handles = await window.showOpenFilePicker({
      multiple: false,
      types: [{
        description: 'Excel 工作簿',
        accept: {
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
        },
      }],
    })
  } catch (requestError) {
    if (requestError?.name === 'AbortError') return
    error.value = `无法打开文件选择器：${requestError?.message || requestError}`
    return
  }
  const fileHandle = handles[0]
  try {
    const permission = await fileHandle.requestPermission({ mode: 'readwrite' })
    if (permission !== 'granted') {
      error.value = '需要文件读写权限才能直接修改该 Excel'
      return
    }
  } catch {
    error.value = '无法获取文件读写权限，已取消导入'
    return
  }
  if (!disposed) await importToBatchExcelByHandle(fileHandle)
}

async function importToBatchExcelByHandle(fileHandle) {
  if (!await saveActiveEdits()) return
  const file = await fileHandle.getFile()
  if (disposed) return
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    error.value = '请选择 .xlsx 格式的批量发布表格'
    return
  }
  if (!result.value || !selectedTitle.value || !selectedBody.value) return
  clearFeedback()
  importingToBatchExcel.value = true
  try {
    const response = await api.importToBatchExcel(
      file,
      selectedTitle.value,
      selectedBody.value,
      outputProductIdentifiers.value.join(','),
    )
    if (disposed) return
    const summaryText = importSummaryText(response)
    const writable = await fileHandle.createWritable()
    await writable.write(await response.arrayBuffer())
    await writable.close()
    showSuccess(`✅ 已更新原文件「${file.name}」${summaryText ? `（${summaryText}）` : ''}。若 WPS/Excel 正打开该文件，请关闭且不要保存旧窗口后重新打开。`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    importingToBatchExcel.value = false
  }
}

function importSummaryText(response) {
  const summaryHeader = response.headers.get('X-Import-Summary') || ''
  const matched = summaryHeader.match(/updated=(\d+)/)
  const created = summaryHeader.match(/created=(\d+)/)
  return matched || created
    ? `已更新 ${matched ? matched[1] : 0} 行，新建 ${created ? created[1] : 0} 行`
    : ''
}

// 可选路径：下载独立结果文件，不修改正在打开的原文件。
async function importToBatchExcel(event) {
  if (!await saveActiveEdits()) {
    event.target.value = ''
    return
  }
  const file = event.target.files?.[0]
  if (!file) return
  if (!result.value) {
    error.value = '请先生成文案，再导入到批量发布 Excel'
    return
  }
  clearFeedback()
  importingToBatchExcel.value = true
  try {
    const response = await api.importToBatchExcel(
      file,
      selectedTitle.value,
      selectedBody.value,
      outputProductIdentifiers.value.join(','),
    )
    if (disposed) return
    const summaryText = importSummaryText(response)
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `batch_imported_${file.name}`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    showSuccess(`✅ 已生成「batch_imported_${file.name}」${summaryText ? `（${summaryText}）` : ''}。原文件未被修改，可在 WPS/Excel 打开时安全下载；请打开该新文件查看结果。`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    importingToBatchExcel.value = false
    event.target.value = ''
  }
}

function restoreAiCopyDraft() {
  const draft = readAiCopyDraft(props.userId, props.brandId)
  if (!draft) return
  if (draft.form && typeof draft.form === 'object') {
    for (const key of Object.keys(createDefaultForm())) {
      if (Object.hasOwn(draft.form, key)) form[key] = draft.form[key]
    }
  }
  if (draft.result && draft.result.brand_id === props.brandId) result.value = draft.result
  if (typeof draft.feedbackText === 'string') feedbackText.value = draft.feedbackText
  if (['title', 'body', 'both'].includes(draft.feedbackTarget)) feedbackTarget.value = draft.feedbackTarget
  if (Array.isArray(draft.productReferences)) productReferences.value = draft.productReferences
  if (Number.isInteger(draft.selectedTitleIndex)) selectedTitleIndex.value = draft.selectedTitleIndex
  if (Number.isInteger(draft.selectedBodyIndex)) selectedBodyIndex.value = draft.selectedBodyIndex
}

async function restoreSellingPointWorkbook() {
  try {
    const file = await loadSellingPointWorkbook(props.userId, props.brandId)
    if (file) await uploadSellingPointFile(file, { persist: false, preserveResult: true })
  } catch (restoreError) {
    error.value = `恢复本机卖点 Excel 失败：${restoreError.message}`
  }
}

function persistAiCopyDraft() {
  if (restoringDraft.value || disposed) return
  window.clearTimeout(draftSaveTimer)
  draftSaveTimer = window.setTimeout(() => {
    saveAiCopyDraft({ version: 3, feedbackText: feedbackText.value, feedbackTarget: feedbackTarget.value, form: { ...form }, result: result.value, productReferences: productReferences.value,
      selectedTitleIndex: selectedTitleIndex.value, selectedBodyIndex: selectedBodyIndex.value, savedAt: new Date().toISOString() }, props.userId, props.brandId)
  }, 180)
}

onMounted(async () => {
  restoreAiCopyDraft()
  await loadOptions()
  await restoreSellingPointWorkbook()
  if (result.value?.generation_id && !disposed) {
    try { result.value = await api.historyDetail(result.value.generation_id) }
    catch (exc) { if (!disposed) { result.value = null; error.value = exc.message } }
  }
  if (!disposed) restoringDraft.value = false
})
watch(() => props.active, (active) => {
  if (active) loadOptions()
})
watch([form, result, productReferences, selectedTitleIndex, selectedBodyIndex, feedbackText, feedbackTarget], persistAiCopyDraft, { deep: true })
onBeforeUnmount(() => {
  persistAiCopyDraft()
  window.clearTimeout(draftSaveTimer)
  // Flush the current brand's draft before a navigation or brand switch.
  if (!restoringDraft.value) saveAiCopyDraft({
    version: 3, feedbackText: feedbackText.value, feedbackTarget: feedbackTarget.value, form: { ...form }, result: result.value, productReferences: productReferences.value,
    selectedTitleIndex: selectedTitleIndex.value, selectedBodyIndex: selectedBodyIndex.value,
  }, props.userId, props.brandId)
  disposed = true
  window.clearTimeout(copyTimer)
  window.clearTimeout(successTimer)
})

function candidateTarget(field, index) {
  return result.value?.candidate_briefs?.[`${field}:${index}`]?.[`${field}_max_chars`]
    || (field === 'title' ? resultTitleMax.value : resultBodyMax.value)
}
const outputProductIdentifiers = computed(() => result.value?.brief?.selling_point_input_mode === 'excel'
  ? (result.value.brief.product_identifiers || []) : [])

async function rewriteCandidates() {
  if (busy.value || !feedbackText.value.trim() || !await saveActiveEdits() || !result.value) return
  const record = result.value
  const message = feedbackText.value.trim()
  rewriting.value = true
  error.value = ''
  try {
    const payload = {
      expected_brand_id: props.brandId, version: record.revision,
      message, target: feedbackTarget.value,
    }
    const signature = JSON.stringify([record.generation_id, payload])
    if (pendingRewrite?.signature !== signature) pendingRewrite = { signature, requestId: crypto.randomUUID() }
    const saved = await api.rewriteBatch(record.generation_id, { ...payload, request_id: pendingRewrite.requestId })
    if (disposed || result.value?.generation_id !== record.generation_id) return
    result.value = saved
    pendingRewrite = null
    feedbackText.value = ''
    resetEditState()
    showSuccess('已批量修改候选。请选择标题和正文导入发布台，实际导入的内容会自动加入选用样本。')
    memoryRefresh.value += 1
  } catch (exc) { if (!disposed) error.value = exc.message }
  finally { rewriting.value = false }
}

async function revealResults() {
  await nextTick()
  if (!disposed) resultsPanel.value?.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start',
  })
}

async function restoreHistoryRecord(record) {
  if (busy.value || record.brand_id !== props.brandId || record.owner_id !== props.userId) return
  if (!await saveActiveEdits() || disposed) return
  result.value = record
  selectedTitleIndex.value = 0
  selectedBodyIndex.value = 0
  resetEditState()
  feedbackText.value = ''
  productReferences.value = record.product_references || []
  clearFeedback()
  emit('update:profileOpen', false)
  showSuccess('已打开历史文案；导入商品使用该记录生成时的商品 ID。')
  await revealResults()
}
</script>

<template>
  <section class="ai-copy-layout ai-copy-workspace" :class="{ 'has-results': result }">
    <form class="ai-copy-card ai-copy-composer" @submit.prevent="generateCopy">
      <fieldset class="ai-copy-controls" :disabled="busy">
      <div class="ai-copy-intro">
        <div>
          <p>生成准备</p>
          <h2>商品资料</h2>
        </div>
        <span class="ai-copy-model" :class="{ offline: !options.llm.ready }">
          {{ options.llm.ready ? `${options.llm.provider} · ${options.llm.model}` : 'LLM 待配置' }}
        </span>
      </div>

      <p v-if="!loadingOptions && !options.llm.ready" class="ai-copy-warning">
        尚未激活 LLM。页面可正常填写，生成前请前往左侧“LLM 适配器”选择模型并填写 API Key。
      </p>
      <p v-if="error && !result" class="ai-copy-error" role="alert">{{ error }}</p>

      <section class="ai-copy-selling-points">
        <div class="ai-copy-selling-point-header">
          <strong>商品核心卖点</strong>
          <div class="ai-copy-selling-point-toggle" role="group" aria-label="商品核心卖点输入方式">
            <button
              :class="{ active: !isManualSellingPointMode }"
              type="button"
              @click="switchSellingPointInputMode('excel')"
            >Excel 匹配</button>
            <button
              :class="{ active: isManualSellingPointMode }"
              type="button"
              @click="switchSellingPointInputMode('manual')"
            >直接输入</button>
          </div>
        </div>

        <label v-if="!isManualSellingPointMode" class="ai-copy-field ai-copy-identifier-field">
          <span>
            <strong>商品 ID / 货号</strong>
            <small>已输入 {{ productIdentifiers.length }} / 20</small>
          </span>
          <textarea
            v-model="form.productIdentifiers"
            rows="3"
            maxlength="2000"
            required
            placeholder="每行输入一个商品 ID 或货号"
          />
        </label>

        <label v-else class="ai-copy-field ai-copy-manual-selling-point-field">
          <span>
            <strong>直接输入核心卖点</strong>
            <small>{{ manualSellingPoint.length }} / 2000</small>
          </span>
          <textarea
            v-model="form.manualSellingPoint"
            rows="6"
            maxlength="2000"
            required
            placeholder="直接填写希望模型重点表达的商品核心卖点，可分行输入"
          />
        </label>

        <div v-if="!isManualSellingPointMode" class="ai-copy-catalog-upload">
          <input
            ref="sellingPointFileInput"
            class="ai-copy-file-input"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            @change="uploadSellingPointCatalog"
          />
          <div>
            <b>SELLING POINT LIBRARY</b>
            <strong>上传商品核心卖点 Excel</strong>
          </div>
          <button :disabled="uploadingSellingPoints" type="button" @click="chooseSellingPointFile">
            {{ uploadingSellingPoints ? '解析中…' : sellingPointCatalog ? '更换表格' : '选择 Excel' }}
          </button>
          <a
            class="ai-copy-template-link"
            :href="`${apiBase}/api/ai-copy/selling-point-template`"
            download
          >
            下载 Excel 模板
          </a>
        </div>

        <article v-if="!isManualSellingPointMode && sellingPointCatalog" class="ai-copy-catalog-status">
          <span>已读取</span>
          <div>
            <strong>{{ sellingPointCatalog.filename }}</strong>
            <small>{{ sellingPointCatalog.row_count }} 条唯一商品卖点；本机已保存副本，刷新后会自动恢复</small>
          </div>
          <button type="button" @click="clearSellingPointCatalog">移除</button>
        </article>

        <p v-if="!isManualSellingPointMode && productIdentifiers.length > 20" class="ai-copy-match-error">
          一次最多支持 20 个商品 ID 或货号。
        </p>
        <p v-else-if="!isManualSellingPointMode && sellingPointCatalog && missingProductIdentifiers.length" class="ai-copy-match-error">
          Excel 中未找到：{{ missingProductIdentifiers.join('、') }}
        </p>

        <div v-if="!isManualSellingPointMode && matchedSellingPoints.length" class="ai-copy-selling-point-preview">
          <div>
            <strong>已匹配 {{ matchedSellingPoints.length }} 条核心卖点</strong>
            <small>将作为本次标题与正文的重要参考</small>
          </div>
          <ol>
            <li v-for="entry in matchedSellingPoints" :key="entry.identifier">
              <b>{{ entry.identifier }}</b>
              <span>{{ entry.selling_point }}</span>
            </li>
          </ol>
        </div>
      </section>

      <details class="ai-copy-generation-settings" :open="settingsOpen" @toggle="settingsOpen = $event.target.open">
        <summary><strong>生成设置</strong><span>{{ form.titleCount || titleCountDefault }} 条标题 · {{ form.bodyCount || bodyCountDefault }} 条正文</span><small>字数、风格、场景与文案参考</small></summary>
        <div class="ai-copy-settings-content">
      <fieldset class="ai-copy-choice-group ai-copy-limits">
        <legend><b>参考汉字数</b></legend>
        <p class="ai-copy-length-help">参考字数允许合理浮动，优先保证表达自然、内容完整。</p>

        <div class="ai-copy-limit-row">
          <span class="ai-copy-limit-label"><b>标题字数</b></span>
          <div class="ai-copy-limit-chips">
            <button
              v-for="preset in titleLimitPresets"
              :key="`title-preset-${preset}`"
              type="button"
              :class="{ active: form.titleMaxChars === preset }"
              @click="pickTitleLimit(preset)"
            >约 {{ preset }} 字</button>
          </div>
          <label class="ai-copy-limit-custom">
            <span>自定义</span>
            <input
              type="text"
              inputmode="numeric"
              pattern="[0-9]*"
              maxlength="3"
              placeholder="自定义"
              :value="form.titleMaxChars"
              @input="onTitleLimitInput"
              @blur="onTitleLimitBlur"
            />
            <small v-if="!titleLimitValid">需为 {{ titleMin }}-{{ titleMax }} 之间的整数</small>
          </label>
        </div>

        <div class="ai-copy-limit-row">
          <span class="ai-copy-limit-label"><b>文案字数</b></span>
          <div class="ai-copy-limit-chips">
            <button
              v-for="preset in bodyLimitPresets"
              :key="`body-preset-${preset}`"
              type="button"
              :class="{ active: form.bodyMaxChars === preset }"
              @click="pickBodyLimit(preset)"
            >约 {{ preset }} 字</button>
          </div>
          <label class="ai-copy-limit-custom">
            <span>自定义</span>
            <input
              type="text"
              inputmode="numeric"
              pattern="[0-9]*"
              maxlength="4"
              placeholder="自定义"
              :value="form.bodyMaxChars"
              @input="onBodyLimitInput"
              @blur="onBodyLimitBlur"
            />
            <small v-if="!bodyLimitValid">需为 {{ bodyMin }}-{{ bodyMax }} 之间的整数</small>
          </label>
        </div>
      </fieldset>

      <fieldset class="ai-copy-choice-group ai-copy-limits ai-copy-counts">
        <legend><b>生成个数</b></legend>

        <div class="ai-copy-limit-row">
          <span class="ai-copy-limit-label"><b>标题个数</b></span>
          <div class="ai-copy-limit-chips">
            <button
              v-for="preset in titleCountPresets"
              :key="`title-count-${preset}`"
              type="button"
              :class="{ active: form.titleCount === preset }"
              @click="pickTitleCount(preset)"
            >{{ preset }} 条</button>
          </div>
          <label class="ai-copy-limit-custom">
            <span>自定义</span>
            <input
              type="text"
              inputmode="numeric"
              pattern="[0-9]*"
              maxlength="2"
              placeholder="自定义"
              :value="form.titleCount"
              @input="onTitleCountInput"
              @blur="onTitleCountBlur"
            />
            <small v-if="!titleCountValid">需为 {{ candidateCountMin }}-{{ candidateCountMax }} 之间的整数</small>
          </label>
        </div>

        <div class="ai-copy-limit-row">
          <span class="ai-copy-limit-label"><b>文案个数</b></span>
          <div class="ai-copy-limit-chips">
            <button
              v-for="preset in bodyCountPresets"
              :key="`body-count-${preset}`"
              type="button"
              :class="{ active: form.bodyCount === preset }"
              @click="pickBodyCount(preset)"
            >{{ preset }} 条</button>
          </div>
          <label class="ai-copy-limit-custom">
            <span>自定义</span>
            <input
              type="text"
              inputmode="numeric"
              pattern="[0-9]*"
              maxlength="2"
              placeholder="自定义"
              :value="form.bodyCount"
              @input="onBodyCountInput"
              @blur="onBodyCountBlur"
            />
            <small v-if="!bodyCountValid">需为 {{ candidateCountMin }}-{{ candidateCountMax }} 之间的整数</small>
          </label>
        </div>
      </fieldset>

      <fieldset class="ai-copy-choice-group">
        <legend><b>文案风格</b></legend>
        <div class="ai-copy-style-grid">
          <label
            v-for="item in options.styles"
            :key="item.value"
            :class="{ selected: !hasCustomStyle && form.style === item.value }"
          >
            <input
              :checked="!hasCustomStyle && form.style === item.value"
              type="radio"
              :value="item.value"
              @change="form.style = item.value; form.customStyle = ''"
            />
            <strong>{{ item.label }}</strong>
          </label>
        </div>
        <label class="ai-copy-field ai-copy-custom-context">
          <span><strong>自定义文案风格</strong></span>
          <input v-model="form.customStyle" maxlength="100" placeholder="请输入自定义文案风格" />
        </label>
      </fieldset>

      <div class="ai-copy-split-fields">
        <label class="ai-copy-field">
          <span><strong>内容场景</strong><small>预设或自定义</small></span>
          <AiCopyDropdown
            v-model="selectedScene"
            aria-label="内容场景"
            :options="options.scenes"
            placeholder="自定义场景已启用"
          />
          <input v-model="form.customScene" maxlength="100" placeholder="请输入自定义内容场景" />
        </label>
        <label class="ai-copy-field">
          <span><strong>节日氛围</strong><small>预设或自定义</small></span>
          <AiCopyDropdown
            v-model="selectedFestival"
            aria-label="节日氛围"
            :options="festivalOptions"
            placeholder="自定义主题已启用"
          />
          <input v-model="form.customFestival" maxlength="80" placeholder="请输入自定义节日或主题" />
        </label>
      </div>

      <section class="ai-copy-product-panel">
        <div class="ai-copy-product-heading">
          <div><p>COPY REFERENCE</p><h3>文案参考</h3></div>
          <span>{{ form.copyReference.trim() ? `${form.copyReference.trim().length} / 20000` : '可选' }}</span>
        </div>
        <p class="ai-copy-product-help">直接输入希望参考的文案内容。生成时会同时参考其内容、结构和语气，并保持与核心卖点各约一半的权重。</p>
        <div class="ai-copy-link-row">
          <textarea
            v-model="form.copyReference"
            rows="6"
            maxlength="20000"
            placeholder="直接输入文案参考，例如喜欢的标题、正文、语气或结构……"
          />
          <button
            v-if="form.copyReference.trim()"
            class="ai-copy-delete-link"
            type="button"
            @click="form.copyReference = ''; productReferences = []"
          >清空参考</button>
        </div>

        <div v-if="productReferences.length" class="ai-copy-reference-list">
          <article
            v-for="(reference, index) in productReferences"
            :key="reference.source_url"
            class="ai-copy-reference"
          >
            <span>已读取 {{ index + 1 }}</span>
            <div>
              <strong>{{ reference.title }}</strong>
              <small>{{ reference.source_url }}</small>
              <p>{{ reference.summary }}</p>
            </div>
            <dl v-if="Object.keys(reference.attributes).length">
              <template v-for="(value, key) in reference.attributes" :key="key">
                <dt>{{ key }}</dt><dd>{{ value }}</dd>
              </template>
            </dl>
          </article>
        </div>
      </section>

        </div>
      </details>
      <button class="ai-copy-generate" :disabled="!canGenerate" type="submit">
        <span>{{ generating ? '正在生成候选…' : result ? '重新生成候选' : '生成标题与文案' }}</span>
        <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h13M14 7l5 5-5 5" /></svg>
      </button>
      </fieldset>
    </form>

    <aside ref="resultsPanel" class="ai-copy-results" aria-label="文案候选与AI改稿">
      <fieldset class="ai-copy-controls" :disabled="busy">
      <div class="ai-copy-result-head">
        <div><p>挑选并导入</p><h2>候选文案</h2></div>
        <div class="ai-copy-result-actions">
          <span v-if="result" class="ai-copy-ready">{{ resultTitles.length }} 标题 · {{ resultBodies.length }} 正文</span>
          <button
            class="ai-copy-clear"
            :disabled="busy || readingProduct || uploadingSellingPoints"
            type="button"
            @click="clearAll"
          >一键清空</button>
        </div>
      </div>

      <p v-if="result && error" class="ai-copy-error" role="alert">{{ error }}</p>
      <p v-if="result && success" class="ai-copy-success" role="status">{{ success }}</p>
      <div v-if="generating" class="ai-copy-generating" aria-live="polite">
        <span></span><span></span><span></span>
        <p>正在综合原参考、核心卖点与文案参考构思文案</p>
      </div>

      <template v-else-if="result">
        <div class="ai-copy-candidate-lists" role="region" tabindex="0" aria-label="标题与正文候选">
        <section class="ai-copy-output-group">
          <div class="ai-copy-candidate-heading">
            <span>标题候选</span><small>已生成 {{ resultTitles.length }} 条；请选择 1 条用于导入</small>
          </div>
          <article
            v-for="(title, index) in resultTitles"
            :key="`title-${index}`"
            :class="['ai-copy-output', 'ai-copy-title-output', { selected: selectedTitleIndex === index }]"
          >
            <div class="ai-copy-output-label">
              <span>标题{{ resultTitles.length > 1 ? ` ${index + 1}` : '' }}</span>
              <small>{{ countHanCharacters(title) }} 汉字 · 参考约 {{ candidateTarget('title', index) }} 汉字</small>
            </div>
            <label v-if="resultTitles.length > 1" class="ai-copy-candidate-select">
              <input type="radio" :aria-label="`选用标题 ${index + 1}`" name="copy-import-title" :disabled="busy" :checked="selectedTitleIndex === index" @change="selectedTitleIndex = index" />
              <span>选用此标题</span>
            </label>
            <template v-if="editingTitleIndex === index">
              <textarea
                v-model="titleEditValue"
                class="ai-copy-edit-textarea ai-copy-title-editor"
                maxlength="200"
                rows="2"
                @keydown.meta.enter.prevent="saveEditedTitle(index)"
                @keydown.ctrl.enter.prevent="saveEditedTitle(index)"
              />
              <div class="ai-copy-edit-meta">
                <span>{{ countHanCharacters(titleEditValue) }} 汉字 · 保存后用于复制、导入工作台和 Excel</span>
              </div>
              <div class="ai-copy-output-actions">
                <button type="button" :disabled="savingEdit" @click="saveEditedTitle(index)">{{ savingEdit ? '保存中…' : '保存标题' }}</button>
                <button class="ai-copy-secondary-action" type="button" @click="cancelEditTitle">取消</button>
              </div>
            </template>
            <template v-else>
              <h3>{{ title }}</h3>
              <div class="ai-copy-output-actions">
                <button type="button" @click="copyText(`title-${index}`, title)">
                  {{ copiedField === `title-${index}` ? '已复制' : '复制标题' }}
                </button>
                <button class="ai-copy-secondary-action" :disabled="busy" type="button" @click="beginEditTitle(index)">编辑标题</button>
              </div>
            </template>
          </article>
        </section>

        <section class="ai-copy-output-group">
          <div class="ai-copy-candidate-heading">
            <span>正文文案候选</span><small>已生成 {{ resultBodies.length }} 条；请选择 1 条用于导入</small>
          </div>
          <article
            v-for="(body, index) in resultBodies"
            :key="`body-${index}`"
            :class="['ai-copy-output', 'ai-copy-body-output', { selected: selectedBodyIndex === index }]"
          >
            <div class="ai-copy-output-label">
              <span>正文文案{{ resultBodies.length > 1 ? ` ${index + 1}` : '' }}</span>
              <small>{{ countHanCharacters(body) }} 汉字 · 参考约 {{ candidateTarget('body', index) }} 汉字</small>
            </div>
            <label v-if="resultBodies.length > 1" class="ai-copy-candidate-select">
              <input type="radio" :aria-label="`选用正文 ${index + 1}`" name="copy-import-body" :disabled="busy" :checked="selectedBodyIndex === index" @change="selectedBodyIndex = index" />
              <span>选用此文案</span>
            </label>
            <template v-if="editingBodyIndex === index">
              <textarea
                v-model="bodyEditValue"
                class="ai-copy-edit-textarea ai-copy-body-editor"
                maxlength="2000"
                rows="6"
                @keydown.meta.enter.prevent="saveEditedBody(index)"
                @keydown.ctrl.enter.prevent="saveEditedBody(index)"
              />
              <div class="ai-copy-edit-meta">
                <span>{{ countHanCharacters(bodyEditValue) }} 汉字 · 保存后用于复制、导入工作台和 Excel</span>
              </div>
              <div class="ai-copy-output-actions">
                <button type="button" :disabled="savingEdit" @click="saveEditedBody(index)">{{ savingEdit ? '保存中…' : '保存文案' }}</button>
                <button class="ai-copy-secondary-action" type="button" @click="cancelEditBody">取消</button>
              </div>
            </template>
            <template v-else>
              <p>{{ body }}</p>
              <div class="ai-copy-output-actions">
                <button type="button" @click="copyText(`body-${index}`, body)">
                  {{ copiedField === `body-${index}` ? '已复制' : '复制文案' }}
                </button>
                <button class="ai-copy-secondary-action" :disabled="busy" type="button" @click="beginEditBody(index)">编辑文案</button>
              </div>
            </template>
          </article>
        </section>

        </div>

        <form class="ai-copy-rewrite-bar" aria-label="AI 改稿" @submit.prevent="rewriteCandidates">
          <div class="ai-copy-rewrite-heading">
            <strong>AI 改稿</strong>
            <label>范围 <select v-model="feedbackTarget" :disabled="busy" aria-label="改稿范围"><option value="both">全部标题和正文</option><option value="title">全部标题</option><option value="body">全部正文</option></select></label>
          </div>
          <label class="ai-copy-rewrite-input" for="copy-rewrite-request">修改要求</label>
          <textarea id="copy-rewrite-request" v-model="feedbackText" :disabled="busy" rows="2" maxlength="2000" placeholder="例如：都自然口语一点，保留每条的区别，正文缩短到五十字左右。" />
          <div class="ai-copy-rewrite-actions">
            <span aria-live="polite">{{ rewriting ? '正在修改' : '将修改' }} {{ feedbackTarget !== 'body' ? resultTitles.length : 0 }} 条标题、{{ feedbackTarget !== 'title' ? resultBodies.length : 0 }} 条正文</span>
            <button type="submit" :disabled="busy || !feedbackText.trim()">{{ rewriting ? '正在修改…' : '批量修改' }}</button>
          </div>
        </form>

        <section class="ai-copy-export" aria-label="导入所选候选">
          <div class="ai-copy-export-main">
            <p>已选：<strong>标题 {{ selectedTitleIndex + 1 }}</strong><span> · </span><strong>正文 {{ selectedBodyIndex + 1 }}</strong></p>
            <button class="ai-copy-import" :disabled="busy" type="button" @click="importToWorkbench">导入发布台 <span aria-hidden="true">→</span></button>
          </div>
          <p class="ai-copy-sample-note">导入成功后，实际导入的字段自动加入品牌选用样本。</p>
        </section>

        <WorkbenchImportDialog
          :open="workbenchImportOpen"
          @close="workbenchImportOpen = false"
          @confirm="confirmWorkbenchImport"
        />

        <!-- 隐藏的文件输入：用于选择批量发布 Excel -->
        <input
          ref="batchExcelFileInput"
          class="ai-copy-file-input"
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          @change="importToBatchExcel"
        />

        <details class="ai-copy-excel-options">
          <summary>批量表格导入</summary>
          <p>{{ !outputProductIdentifiers.length ? '当前文案没有商品 ID，不能按 ID 导入批量表格。' : downloadBatchExcelCopy ? '下载独立导入结果，不覆盖原文件。' : '直接填入原文件；请先关闭 WPS/Excel 中打开的该文件。' }}</p>
          <label class="ai-copy-download-option"><input v-model="downloadBatchExcelCopy" type="checkbox" /><span>下载为新文件（保留原文件）</span></label>
          <button class="ai-copy-import-batch" type="button" :disabled="busy || !outputProductIdentifiers.length" @click="chooseBatchExcelFile">{{ importingToBatchExcel ? '正在处理…' : '导入批量发布表格' }}</button>
        <p class="ai-copy-result-meta">
          由 {{ result.provider }} · {{ result.model }} 生成
          <span> · 已引用 {{ result.selling_point_references.length }} 条核心卖点</span>
          <span v-if="result.product_references.length"> · 已引用 {{ result.product_references.length }} 个商品资料</span>
        </p>
        </details>


      </template>

      <div v-else class="ai-copy-empty">
        <span>AI</span>
        <h3>匹配商品卖点，或直接交给 AI</h3>
        <p>可上传核心卖点 Excel 后按商品 ID 精准匹配，也可切换为直接输入核心卖点。</p>
        <ol><li>可在「参考汉字数」中预设或自定义，结果字数允许合理浮动</li><li>不虚构商品信息与促销承诺</li></ol>
      </div>
      </fieldset>
    </aside>
  </section>
  <BrandProfileDrawer :open="profileOpen" :brand-name="brandName" @close="emit('update:profileOpen', false)">
    <BrandCopyPanel :brand-id="brandId" :brand-name="brandName" :user-id="userId"
      :can-moderate="canModerate" :refresh-key="memoryRefresh" :disabled="busy"
      @restore="restoreHistoryRecord" />
  </BrandProfileDrawer>
</template>

<style src="./ai-copy.css"></style>
<style src="./ai-copy-workspace.css"></style>
