<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiFetch, apiRequest } from '../../api-client.js'

const templateFile = ref(null)
const sourceFiles = ref([])
const sheetFilling = ref(false)
const sheetStatus = ref('')
const resultUrl = ref('')
const resultFilename = ref('')
const sourceFieldOptions = ref([])
const targetFieldOptions = ref([])
const fieldMappings = ref([{ sourceIndex: '', targetIndex: '' }])
const inspectingFields = ref(false)
const tableName = ref('')
const tableNames = ref([])
const tableMenuOpen = ref(false)
const tableDeleting = ref('')
const filteredTableNames = computed(() => tableNames.value.filter((name) => name.toLocaleLowerCase().includes(tableName.value.trim().toLocaleLowerCase())))
const sourceMode = ref('upload')
const databaseSources = ref([])
const databasePeriods = ref([])
const databaseSource = ref('')
const databasePeriod = ref('all')
const databaseBrand = ref('')
const databaseError = ref('')
const sourceReady = computed(() => sourceMode.value === 'upload' ? sourceFiles.value.length > 0 : Boolean(databaseSource.value))

function appendSources(body) {
  if (sourceMode.value === 'database') {
    body.append('database_source', databaseSource.value)
    body.append('database_period', databasePeriod.value)
  } else {
    sourceFiles.value.forEach((file) => body.append('sources', file))
  }
}

function changeSourceMode(event) {
  sourceMode.value = event.target.value
  sourceFieldOptions.value = []
  targetFieldOptions.value = []
  fieldMappings.value = [{ sourceIndex: '', targetIndex: '' }]
  sheetStatus.value = ''
}

async function loadDatabaseSources() {
  try {
    const result = await apiRequest('/api/sheet-fill/database-sources')
    databaseSources.value = result.sources || []
    databasePeriods.value = result.periods || []
    databaseSource.value = databaseSources.value[0]?.key || ''
    databasePeriod.value = databasePeriods.value[0]?.key || 'all'
    databaseBrand.value = result.brand || ''
  } catch (requestError) {
    databaseError.value = requestError.message
  }
}

async function fillSheet() {
  if (!templateFile.value || !sourceReady.value) {
    sheetStatus.value = '请选择待填表格和至少一个数据源'
    return
  }
  sheetFilling.value = true
  sheetStatus.value = '正在解析并匹配字段，请稍候…'
  if (resultUrl.value) URL.revokeObjectURL(resultUrl.value)
  resultUrl.value = ''
  const body = new FormData()
  body.append('template', templateFile.value)
  appendSources(body)
  body.append('field_corrections', JSON.stringify(fieldMappings.value
    .filter((item) => item.targetIndex !== '')
    .map((item) => ({
      source: item.sourceIndex === '' ? null : sourceFieldOptions.value[Number(item.sourceIndex)],
      target: targetFieldOptions.value[Number(item.targetIndex)],
    }))))
  body.append('table_name', tableName.value)
  try {
    const response = await apiFetch('/api/sheet-fill', { method: 'POST', body })
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}))
      throw new Error(typeof errorBody.detail === 'string' ? errorBody.detail : '表格填充失败')
    }
    const url = URL.createObjectURL(await response.blob())
    const filename = `已填充-${templateFile.value.name.replace(/\.[^.]+$/, '')}.xlsx`
    resultUrl.value = url
    resultFilename.value = filename
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    if (tableName.value.trim() && !tableNames.value.includes(tableName.value.trim())) tableNames.value.push(tableName.value.trim())
    sheetStatus.value = `填充完成：${filename}（已发送到浏览器下载目录）`
  } catch (requestError) {
    sheetStatus.value = requestError.message
  } finally {
    sheetFilling.value = false
  }
}

function selectSources(event) {
  sourceFiles.value = [...event.target.files]
  sourceFieldOptions.value = []
  targetFieldOptions.value = []
  sheetStatus.value = sourceFiles.value.length ? `已选择 ${sourceFiles.value.length} 个数据源，请继续选择待填表` : ''
}

function selectTemplate(event) {
  templateFile.value = event.target.files[0] || null
  sourceFieldOptions.value = []
  targetFieldOptions.value = []
  if (templateFile.value && !tableName.value) tableName.value = templateFile.value.name.replace(/\.[^.]+$/, '').replace(/^已填充-/, '')
  sheetStatus.value = templateFile.value ? `已选择待填表：${templateFile.value.name}` : ''
}

async function loadTableNames() {
  try {
    tableNames.value = (await apiRequest('/api/sheet-fill/tables')).tables || []
  } catch { tableNames.value = [] }
}

async function loadSavedTable() {
  const name = tableName.value.trim()
  if (!name || !tableNames.value.includes(name)) return
  try {
    const record = await apiRequest(`/api/sheet-fill/table?name=${encodeURIComponent(name)}`)
    sourceFieldOptions.value = []
    targetFieldOptions.value = []
    fieldMappings.value = [{ sourceIndex: '', targetIndex: '' }]
    sheetStatus.value = `已找到“${name}”的 ${record.rule_count} 条历史映射规则；如需修正当前文件，请点击“识别表头位置”`
  } catch (requestError) {
    sheetStatus.value = requestError.message
  }
}

function selectTable(name) {
  tableName.value = name
  tableMenuOpen.value = false
  loadSavedTable()
}

async function deleteTable(name) {
  if (!window.confirm(`确定删除表格方案“${name}”吗？`)) return
  tableDeleting.value = name
  try {
    await apiRequest(`/api/sheet-fill/table?name=${encodeURIComponent(name)}`, { method: 'DELETE' })
    const names = (await apiRequest('/api/sheet-fill/tables')).tables || []
    tableNames.value = names
    if (names.includes(name)) throw new Error(`方案“${name}”仍存在，请重试`)
    if (tableName.value.trim() === name) tableName.value = ''
    tableMenuOpen.value = false
    sheetStatus.value = `已删除表格方案“${name}”`
  } catch (requestError) {
    sheetStatus.value = requestError.message
  } finally {
    tableDeleting.value = ''
  }
}

async function inspectFields() {
  if (!templateFile.value || !sourceReady.value) return
  inspectingFields.value = true
  sheetStatus.value = '正在识别各文件的 Sheet 和表头位置…'
  const body = new FormData()
  body.append('template', templateFile.value)
  appendSources(body)
  try {
    const result = await apiRequest('/api/sheet-fill/inspect', { method: 'POST', body })
    sourceFieldOptions.value = result.sources || []
    targetFieldOptions.value = result.targets || []
    fieldMappings.value = [{ sourceIndex: '', targetIndex: '' }]
    sheetStatus.value = `已识别 ${sourceFieldOptions.value.length} 个数据源字段、${targetFieldOptions.value.length} 个待填字段`
  } catch (requestError) {
    sheetStatus.value = requestError.message
  } finally {
    inspectingFields.value = false
  }
}

function addFieldMapping() { fieldMappings.value.push({ sourceIndex: '', targetIndex: '' }) }
function removeFieldMapping(index) { fieldMappings.value.splice(index, 1) }

onMounted(() => { loadTableNames(); loadDatabaseSources() })
onBeforeUnmount(() => { if (resultUrl.value) URL.revokeObjectURL(resultUrl.value) })
</script>

<template>
  <section class="smart-sheet-view">
    <div class="smart-sheet-intro"><strong>智能表格填充</strong><span>选择上传表格或当前品牌的数据库内容作为数据源，再上传需要填充的模板。</span></div>
    <section class="sheet-fill-bar" aria-labelledby="sheet-fill-title">
      <div class="sheet-fill-heading"><strong id="sheet-fill-title">选择表格与数据源</strong><span>使用当前 LLM 适配器匹配字段，已有方案可直接复用</span></div>
      <div class="table-name-picker" @focusout="tableMenuOpen = false"><label for="sheet-table-name">表格方案名</label><div class="table-name-input"><input id="sheet-table-name" v-model="tableName" maxlength="120" autocomplete="off" placeholder="输入新名称或选择已有方案" @focus="tableMenuOpen = true" @input="tableMenuOpen = true" @change="loadSavedTable" /><button type="button" aria-label="选择已有方案" @mousedown.prevent @click="tableMenuOpen = !tableMenuOpen">▾</button></div><div v-if="tableMenuOpen && filteredTableNames.length" class="table-name-menu"><div v-for="name in filteredTableNames" :key="name" class="table-name-option"><button type="button" class="table-name-choice" @mousedown.prevent @click="selectTable(name)">{{ name }}</button><button type="button" class="table-name-delete" :aria-label="`删除方案 ${name}`" :disabled="!!tableDeleting" @mousedown.prevent @click.stop="deleteTable(name)">×</button></div></div><small>{{ tableNames.includes(tableName.trim()) ? '✓ 将复用已记录 JSON' : '首次成功后自动创建' }}</small></div>
      <label class="source-select"><span>数据来源</span><select :value="sourceMode" @change="changeSourceMode"><option value="upload">上传 Excel 文件</option><option value="database">品牌数据库</option></select></label>
      <label v-if="sourceMode === 'upload'" :class="{ selected: sourceFiles.length }"><span>上传数据源</span><input type="file" multiple accept=".xlsx,.xls,.xlsm" @change="selectSources" /><small>{{ sourceFiles.length ? `✓ 已选 ${sourceFiles.length} 个文件` : '点击选择，可多选' }}</small></label>
      <label v-else class="source-select" :class="{ selected: databaseSource }"><span>数据库数据表</span><select v-model="databaseSource" :disabled="!databaseSources.length"><option value="">请选择数据表</option><option v-for="source in databaseSources" :key="source.key" :value="source.key">{{ source.label }} · {{ databaseBrand }}</option></select></label>
      <label v-if="sourceMode === 'database'" class="source-select"><span>下载周期</span><select v-model="databasePeriod"><option value="all">全部周期</option><option v-for="item in databasePeriods" :key="item.key" :value="item.key">{{ item.label }}（{{ item.count }} 条）</option></select></label>
      <label :class="{ selected: templateFile }"><span>上传待填数据</span><input type="file" accept=".xlsx,.xlsm" @change="selectTemplate" /><small>{{ templateFile ? `✓ ${templateFile.name}` : '点击选择模板' }}</small></label>
      <button type="button" :disabled="sheetFilling || !templateFile || !sourceReady" @click="fillSheet">{{ sheetFilling ? '处理中…' : '开始填充' }}</button>
      <p v-if="sourceMode === 'database' && databaseError" class="database-source-error" role="status">{{ databaseError }}</p>
      <div class="sheet-correction-grid">
        <div class="sheet-correction-head"><strong>字段映射修正</strong><button type="button" :disabled="inspectingFields || !templateFile || !sourceReady" @click="inspectFields">{{ inspectingFields ? '识别中…' : '识别表头位置' }}</button></div>
        <template v-if="sourceFieldOptions.length || targetFieldOptions.length">
          <div v-for="(mapping, index) in fieldMappings" :key="index" class="sheet-mapping-row">
            <label><span>数据源字段（可留空）</span><select v-model="mapping.sourceIndex"><option value="">留空并让模型重匹配</option><option v-for="(item, optionIndex) in sourceFieldOptions" :key="`${item.file}-${item.sheet}-${item.cell}`" :value="String(optionIndex)">{{ item.label }}</option></select></label>
            <span class="mapping-arrow">→</span>
            <label><span>待填表格字段</span><select v-model="mapping.targetIndex"><option value="">请选择目标位置</option><option v-for="(item, optionIndex) in targetFieldOptions" :key="`${item.sheet}-${item.cell}`" :value="String(optionIndex)">{{ item.label }}</option></select></label>
            <button v-if="fieldMappings.length > 1" class="mapping-remove" type="button" @click="removeFieldMapping(index)">删除</button>
          </div>
          <button class="mapping-add" type="button" @click="addFieldMapping">＋ 添加一条映射</button>
          <small>每个选项包含文件、Sheet、单元格坐标和字段名，可准确区分重名字段。只选择右侧时会定点重新匹配。</small>
        </template>
        <small v-else>需要修正时，先点击“识别表头位置”；不修正可直接开始填充。</small>
      </div>
      <p v-if="sheetStatus" role="status">{{ sheetStatus }} <a v-if="resultUrl" :href="resultUrl" :download="resultFilename">再次下载结果</a></p>
    </section>

  </section>
</template>

<style scoped>
.smart-sheet-view { display: grid; gap: 18px; }
.smart-sheet-intro { display: grid; gap: 5px; padding: 18px 20px; border: 1px solid #dce5dd; border-radius: 14px; background: #f7faf4; }
.smart-sheet-intro strong { color: #244541; font-size: 18px; }
.smart-sheet-intro span { color: #789087; font-size: 12px; }
.sheet-fill-bar { display: grid; grid-template-columns: minmax(180px, .8fr) minmax(170px, .55fr) repeat(2, minmax(180px, .65fr)) auto; gap: 12px; align-items: center; padding: 14px 16px; border: 1px solid #dce5dd; border-radius: 14px; background: rgba(255,255,255,.76); box-shadow: 0 8px 18px rgba(36,68,57,.035); }.sheet-fill-bar > div { display: grid; gap: 4px; }.sheet-fill-bar strong { color: #244541; font-size: 14px; }.sheet-fill-bar > div span, .sheet-fill-bar small { color: #8b9b94; font-size: 10px; }.sheet-fill-bar label { position: relative; display: grid; gap: 3px; min-width: 0; padding: 9px 11px; border: 1px dashed #bdcabf; border-radius: 9px; background: #f8faf6; cursor: pointer; }.sheet-fill-bar label.selected { border-style: solid; border-color: #aabd6a; background: #f4f7d8; }.sheet-fill-bar label > span { color: #496760; font-size: 11px; font-weight: 800; }.sheet-fill-bar label small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.sheet-fill-bar label.selected small { color: #557044; font-weight: 750; }.sheet-fill-bar input[type="file"] { position: absolute; width: 1px; height: 1px; opacity: 0; }.table-name-picker { border-style: solid !important; cursor: text !important; }.table-name-picker input { min-width: 0; border: 0; outline: 0; color: #294944; background: transparent; font-size: 11px; }.sheet-fill-bar button { border: 0; border-radius: 9px; padding: 12px 16px; color: #25443e; background: #e7ed91; font-weight: 800; cursor: pointer; }.sheet-fill-bar button:disabled { opacity: .45; cursor: not-allowed; }.sheet-fill-bar > p { grid-column: 1 / -1; margin: 0; color: #668078; font-size: 11px; }.sheet-fill-bar > p a { margin-left: 8px; color: #3d695c; font-weight: 800; }
.sheet-correction-grid { grid-column: 1 / -1; display: grid !important; gap: 9px !important; }.sheet-correction-head { display: flex !important; grid-template-columns: none !important; align-items: center; justify-content: space-between; }.sheet-correction-head button, .mapping-add, .mapping-remove { padding: 7px 10px; border: 1px solid #cbd8c6; border-radius: 7px; color: #45675e; background: #fff; font-size: 10px; cursor: pointer; }.sheet-mapping-row { display: grid !important; grid-template-columns: minmax(0,1fr) auto minmax(0,1fr) auto; gap: 8px !important; align-items: center; }.sheet-mapping-row label { border-style: solid; cursor: default; }.sheet-mapping-row select { min-width: 0; width: 100%; border: 0; outline: 0; color: #294944; background: transparent; font-size: 11px; }.mapping-arrow { color: #8ba07f; font-weight: 900; }.mapping-add { justify-self: start; }.mapping-remove { color: #a05d52; }
.sheet-fill-bar { grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: stretch; }
.sheet-fill-heading { grid-column: 1 / -1; }
.sheet-fill-bar > button { align-self: stretch; }
.sheet-fill-bar .source-select { border-style: solid; cursor: default; }
.source-select select { min-width: 0; width: 100%; border: 0; outline: 0; color: #294944; background: transparent; font-size: 11px; cursor: pointer; }
.database-source-error { color: #a05d52 !important; }
.sheet-fill-bar .table-name-picker { position: relative; display: grid; gap: 3px; min-width: 0; padding: 9px 11px; border: 1px solid #bdcabf; border-radius: 9px; background: #f8faf6; }
.table-name-picker > label { padding: 0; border: 0; background: transparent; color: #496760; font-size: 11px; font-weight: 800; cursor: default; }
.table-name-input { display: flex !important; align-items: center; min-width: 0; }
.table-name-input input { flex: 1; width: 0; }
.table-name-input button { padding: 0 3px; border: 0; background: transparent; font-size: 14px; }
.table-name-menu { position: absolute; z-index: 20; top: calc(100% + 3px); left: 0; width: max(100%, 260px); max-width: min(420px, 90vw); max-height: 240px; overflow-y: auto; padding: 5px; border: 1px solid #dce5dd; border-radius: 9px; background: #fff; box-shadow: 0 8px 18px rgba(36,68,57,.18); }
.table-name-option { display: flex !important; align-items: center; gap: 4px !important; }
.sheet-fill-bar .table-name-choice { flex: 1; min-width: 0; padding: 8px; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; background: transparent; font-size: 11px; }
.sheet-fill-bar .table-name-choice:hover { background: #f4f7d8; }
.sheet-fill-bar .table-name-delete { flex: none; padding: 4px 8px; color: #a05d52; background: transparent; font-size: 18px; line-height: 1; }
.sheet-fill-bar .table-name-delete:hover { background: #fbeae7; }
@media (max-width: 900px) { .sheet-fill-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .sheet-fill-bar { grid-template-columns: 1fr; }.sheet-mapping-row { grid-template-columns: 1fr; }.mapping-arrow { display: none; } }
</style>
