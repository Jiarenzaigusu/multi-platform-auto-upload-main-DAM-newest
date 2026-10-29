<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  brands: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  required: { type: Boolean, default: false },
  valueField: { type: String, default: 'name' },
  currentLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

function nameKey(value) {
  return value.normalize('NFKC').trim().replace(/\s+/gu, ' ').toLowerCase()
}

// Display the canonical option for existing accounts without rewriting saved names.
const selectedValue = computed({
  get() {
    if (props.valueField === 'id') return props.modelValue
    return props.brands.find((brand) => nameKey(brand.name) === nameKey(props.modelValue))?.name || props.modelValue
  },
  set(value) { emit('update:modelValue', value) },
})
const optionValue = (brand) => String(brand[props.valueField])
const missingCurrentBrand = computed(() => selectedValue.value && !props.brands.some((brand) => optionValue(brand) === selectedValue.value))
</script>

<template>
  <select v-model="selectedValue" :required="required" :disabled="loading || !brands.length">
    <option value="" :disabled="required">
      {{ loading ? '正在读取品牌…' : !brands.length ? '暂无可选品牌' : required ? '请选择所属品牌' : '未分配品牌' }}
    </option>
    <option v-if="missingCurrentBrand" :value="selectedValue" disabled>{{ currentLabel || selectedValue }}（当前不可选，保留原值）</option>
    <option v-for="brand in brands" :key="brand.id" :value="optionValue(brand)">{{ brand.name }}</option>
  </select>
</template>
