// api.js：AI 文案模块的 HTTP 客户端工厂。
//
// 封装 /api/ai-copy 下的所有接口调用与错误解析：
// - options(): 获取风格/场景/节日/LLM 状态
// - uploadSellingPoints(file): 上传卖点 Excel
// - deleteSellingPointCatalog(id): 删除卖点目录
// - inspectProducts(payload): 读取商品链接资料
// - generate(payload): 生成文案
// - importToBatchExcel(file, title, body, productIdentifiers): 将文案按 ID 组写入批量发布表
//
import { apiFetch, apiRequest } from '../../api-client.js'

function errorMessage(body) {
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return body.detail.map((item) => item.msg || '输入内容不符合要求').join('；')
  }
  return 'AI 文案服务请求失败，请稍后重试'
}

export function createAiCopyApi(brandId = '') {
  const path = (suffix) => `/api/ai-copy${suffix}`
  const scopeHeaders = () => {
    const id = typeof brandId === 'function' ? brandId() : brandId
    return id ? { 'X-Copy-Brand': id } : {}
  }
  const request = (suffix, options = {}) => apiRequest(path(suffix), {
    ...options, headers: { ...scopeHeaders(), ...options.headers },
  })
  const json = (method, payload) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })

  return {
    options: () => request('/options'),
    uploadSellingPoints: (file) => {
      const body = new FormData()
      body.append('file', file)
      return request('/selling-point-catalog', { method: 'POST', body })
    },
    deleteSellingPointCatalog: (catalogId) => request(
      `/selling-point-catalog/${encodeURIComponent(catalogId)}`,
      { method: 'DELETE' },
    ),
    inspectProducts: (payload) => request('/product-references', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    generate: (payload) => request('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    profile: () => request('/profile'),
    history: () => request('/history'),
    historyDetail: (id) => request(`/history/${encodeURIComponent(id)}`),
    saveEdit: (id, payload) => request(`/history/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
    brands: () => request('/brands'),
    saveBrand: (id, payload) => request(id ? `/brands/${encodeURIComponent(id)}` : '/brands', json(id ? 'PATCH' : 'POST', payload)),
    rewrite: (id, payload) => request(`/history/${encodeURIComponent(id)}/rewrite`, json('POST', payload)),
    rewriteBatch: (id, payload) => request(`/history/${encodeURIComponent(id)}/rewrite-batch`, json('POST', payload)),
    recordImport: (id, payload) => request(`/history/${encodeURIComponent(id)}/imports`, json('POST', payload)),
    adopt: (id, payload) => request(`/history/${encodeURIComponent(id)}/adopt`, json('POST', payload)),
    analyze: (id) => request(`/adoptions/${encodeURIComponent(id)}/analyze`, { method: 'POST' }),
    preference: (id, payload) => request(`/preferences/${encodeURIComponent(id)}`, json('PATCH', payload)),
    sample: (id, payload) => request(`/adoptions/${encodeURIComponent(id)}`, json('PATCH', payload)),
    /**
     * 将生成的文案（标题+正文）导入批量发布 Excel 表格。
     *
     * 后端将当前输入的商品 ID/货号视为一个完整组：仅匹配 ID 集合完全相同的行。
     * 未匹配则新增一行，仅填写商品 ID/货号与表中实际存在的「标题」「文案」列。
     *
     * @param {File} file - 用户选择的批量发布 Excel 文件（.xlsx）
     * @param {string} title - AI 生成的文案标题
     * @param {string} body - AI 生成的文案正文
     * @param {string} productIdentifiers - 商品 ID/货号（逗号、分号或换行分隔）
     * @returns {Promise<Response>} 原始 fetch Response（用于读取字节写回原文件或下载）
     */
    importToBatchExcel: (file, title, body, productIdentifiers) => {
      const form = new FormData()
      form.append('file', file)
      form.append('title', title)
      form.append('body', body)
      form.append('product_identifiers', productIdentifiers)
      // 返回原始 response 以便前端读取 blob 下载文件
      return apiFetch(path('/import-to-batch-excel'), {
        method: 'POST',
        headers: scopeHeaders(),
        body: form,
      }).then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(errorMessage(err))
          })
        }
        return response
      })
    },
  }
}
