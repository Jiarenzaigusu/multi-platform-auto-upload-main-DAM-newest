<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({ open: Boolean, brandName: { type: String, default: '' } })
const emit = defineEmits(['close'])
const closeButton = ref(null)
const drawer = ref(null)
let returnFocus = null

watch(() => props.open, async (open) => {
  if (open) {
    returnFocus = document.activeElement
    await nextTick()
    closeButton.value?.focus({ preventScroll: true })
  } else if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
}, { immediate: true, flush: 'post' })

function handleKeydown(event) {
  if (!props.open || event.isComposing) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
  } else if (event.key === 'Tab') {
    const controls = [...(drawer.value?.querySelectorAll('button,input,select,textarea,summary,a[href],[tabindex="0"]') || [])]
      .filter(element => {
        if (element.disabled || element.tabIndex < 0 || !element.getClientRects().length) return false
        // Closed details can report boxes for descendants that cannot receive focus.
        for (let parent = element.parentElement; parent && parent !== drawer.value; parent = parent.parentElement) {
          if (parent.matches('details:not([open])') && !parent.querySelector(':scope > summary')?.contains(element)) return false
        }
        return true
      })
    const first = controls[0], last = controls.at(-1)
    if (!drawer.value?.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
      event.preventDefault()
      const next = event.shiftKey ? last : first
      next?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }
}
window.addEventListener('keydown', handleKeydown)
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <Teleport to="body">
    <template v-if="open">
      <div class="copy-profile-backdrop" aria-hidden="true" @click="emit('close')" @wheel.prevent></div>
      <aside id="copy-brand-profile" ref="drawer" class="copy-profile-drawer" role="dialog" aria-modal="true" aria-labelledby="copy-brand-profile-title">
        <header>
          <div><small>品牌表达与选用样本</small><h2 id="copy-brand-profile-title">品牌画像</h2></div>
          <button ref="closeButton" type="button" aria-label="关闭品牌画像" @click="emit('close')">×</button>
        </header>
        <section class="copy-profile-content" :aria-label="`${brandName}的品牌画像`"><slot /></section>
      </aside>
    </template>
  </Teleport>
</template>

<style scoped>
.copy-profile-backdrop { position:fixed; inset:0; z-index:79; background:rgba(22,46,38,.25); touch-action:none; }
.copy-profile-drawer { position:fixed; z-index:80; inset:0 0 0 auto; display:flex; flex-direction:column; width:min(480px,100vw); height:100dvh; box-sizing:border-box; border-left:1px solid #dce6d9; background:#fbfcf7; color:#294c42; box-shadow:-14px 0 38px rgba(25,52,42,.14); }
header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:20px 24px; border-bottom:1px solid #e2e9dc; }
header small { color:#718073; font-size:12px; }
h2 { margin:6px 0 0; font-size:22px; }
header button { border:0; background:transparent; color:#567166; font-size:28px; cursor:pointer; }
.copy-profile-content { flex:1; min-height:0; overflow-y:auto; overscroll-behavior:contain; padding:22px; }
.copy-profile-content :deep(.brand-copy-panel) { margin:0; padding:0; border:0; border-radius:0; background:transparent; }
.copy-profile-content :deep(.brand-copy-panel > summary) { font-size:14px; }
button:focus-visible { outline:2px solid #567166; outline-offset:3px; }
@media (max-width:600px) { header { padding:16px; } .copy-profile-content { padding:16px; } }
</style>
