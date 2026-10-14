import { computed, onMounted, ref } from 'vue'

import { apiRequest } from './api-client.js'

/** Load one catalog per form, shared by all account rows on that form. */
export function useBrandOptions() {
  const brands = ref([])
  const loading = ref(true)
  const configured = ref(false)
  const error = ref('')
  const message = computed(() => {
    if (loading.value) return '正在读取品牌列表…'
    if (error.value) return `品牌列表读取失败：${error.value}`
    if (!configured.value) return '尚未配置品牌数据库，请先配置 MySQL。'
    if (!brands.value.length) return '暂无可选品牌，请先添加品牌或修正重复品牌名。'
    return ''
  })

  async function reload() {
    loading.value = true
    error.value = ''
    try {
      const result = await apiRequest('/api/auth/brands')
      brands.value = result.brands
      configured.value = result.configured
    } catch (requestError) {
      brands.value = []
      error.value = requestError.message
    } finally {
      loading.value = false
    }
  }

  onMounted(reload)
  return { brands, loading, message, reload }
}
