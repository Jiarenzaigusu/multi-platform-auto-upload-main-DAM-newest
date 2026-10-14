const search = document.querySelector('#manual-search')
const sections = [...document.querySelectorAll('.manual-section')]
const links = [...document.querySelectorAll('nav a')]
const chapterNav = document.querySelector('nav[aria-label="手册章节"]')
const toc = document.querySelector('#manual-toc')
const groups = [...chapterNav.querySelectorAll('.toc-group')]
const linksById = new Map(links.map(link => [link.hash.slice(1), link]))
const status = document.querySelector('#search-status')
const noResults = document.querySelector('#no-results')
const searchable = sections.map((section) => {
  const link = linksById.get(section.id)
  return `${section.textContent} ${link.closest('.toc-group')?.dataset.label || link.dataset.label}`.toLocaleLowerCase()
})
let savedGroupState = null
let currentSectionId = null
let scrollFrame = null
if (window.matchMedia('(max-width: 850px)').matches) {
  toc.open = false
}

function filterSections() {
  const query = search.value.trim().toLocaleLowerCase()
  const words = query.split(/\s+/).filter(Boolean)
  if (query && !savedGroupState) savedGroupState = new Map(groups.map(group => [group, group.open]))
  let count = 0
  sections.forEach((section, index) => {
    const visible = words.every((word) => searchable[index].includes(word))
    section.hidden = !visible
    linksById.get(section.id).hidden = !visible
    if (visible) count += 1
  })
  groups.forEach((group) => {
    group.hidden = [...group.querySelectorAll('a')].every(link => link.hidden)
    if (query && !group.hidden) group.open = true
    if (!query && savedGroupState) group.open = savedGroupState.get(group)
  })
  if (!query) savedGroupState = null
  const divider = chapterNav.querySelector('.toc-divider')
  if (divider) divider.hidden = ![...chapterNav.querySelectorAll('[data-chapter="A"], [data-chapter="B"], [data-chapter="C"]')].some(entry => !entry.hidden)
  if (query) toc.open = true
  noResults.hidden = count > 0
  status.textContent = query ? `找到 ${count} 项说明。清空关键词可查看全部。` : '输入关键词查找相关操作。'
  scheduleCurrentChapter()
}

function setCurrentChapter(id, reveal = false) {
  const currentLink = linksById.get(id)
  if (!currentLink) return
  const changed = currentSectionId !== id
  if (!changed && !reveal) return
  links.forEach(link => link.removeAttribute('aria-current'))
  currentLink.setAttribute('aria-current', 'location')
  currentSectionId = id
  const currentGroup = currentLink.closest('.toc-group')
  groups.forEach(group => group.classList.toggle('is-current', group === currentGroup))
  if (currentGroup && (changed || reveal)) currentGroup.open = true
  if (!toc.open || currentLink.hidden) return
  const linkBox = currentLink.getBoundingClientRect()
  const navBox = chapterNav.getBoundingClientRect()
  if (linkBox.top < navBox.top) chapterNav.scrollTop += linkBox.top - navBox.top - 8
  else if (linkBox.bottom > navBox.bottom) chapterNav.scrollTop += linkBox.bottom - navBox.bottom + 8
}

function updateCurrentChapterFromScroll() {
  if (window.matchMedia('(min-width: 851px)').matches && toc.open) {
    const space = Math.max(96, window.innerHeight - chapterNav.getBoundingClientRect().top - 40)
    chapterNav.style.maxHeight = `${space}px`
  }
  const visible = sections.filter(section => !section.hidden)
  if (!visible.length) return
  let current = visible[0]
  for (const section of visible) {
    if (section.getBoundingClientRect().top <= 150) current = section
    else break
  }
  if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) current = visible.at(-1)
  setCurrentChapter(current.id)
}

function scheduleCurrentChapter() {
  if (scrollFrame !== null) return
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = null
    updateCurrentChapterFromScroll()
  })
}

function revealHashChapter() {
  const target = document.getElementById(window.location.hash.slice(1))
  if (!target?.classList.contains('manual-section')) return
  if (target.hidden) {
    search.value = ''
    filterSections()
    target.scrollIntoView()
  }
  setCurrentChapter(target.id, true)
}

// Links inside tables may refer to a chapter outside the current search results.
document.addEventListener('click', (event) => {
  const link = event.target.closest('a[href^="#"]')
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const target = document.getElementById(link.hash.slice(1))
  if (target?.hidden) {
    search.value = ''
    filterSections()
  }
  if (target?.classList.contains('manual-section')) setCurrentChapter(target.id, true)
})
search.addEventListener('input', filterSections)
document.querySelectorAll('[data-toc-action]').forEach(button => {
  button.addEventListener('click', () => {
    groups.filter(group => !group.hidden).forEach(group => { group.open = button.dataset.tocAction === 'expand' })
  })
})
window.addEventListener('hashchange', revealHashChapter)
window.addEventListener('scroll', scheduleCurrentChapter, { passive: true })
window.addEventListener('resize', scheduleCurrentChapter)
window.addEventListener('load', scheduleCurrentChapter)
toc.addEventListener('toggle', scheduleCurrentChapter)
revealHashChapter()
scheduleCurrentChapter()

const viewer = document.querySelector('#image-viewer')
const viewerImage = document.querySelector('#image-viewer-image')
const viewerTitle = document.querySelector('#image-viewer-title')
const viewport = document.querySelector('.image-viewer-viewport')
const zoomLabel = document.querySelector('#image-zoom')
const zoomIn = viewer.querySelector('[data-image-action="in"]')
const zoomOut = viewer.querySelector('[data-image-action="out"]')
let imageWidth = 0
let imageHeight = 0
let zoom = 1
let fitMode = true
let imageTrigger = null

function setZoom(value) {
  const previousWidth = viewerImage.width
  const centerX = viewport.scrollLeft + viewport.clientWidth / 2
  const centerY = viewport.scrollTop + viewport.clientHeight / 2
  zoom = Math.min(3, Math.max(0.05, value))
  viewerImage.style.width = `${imageWidth * zoom}px`
  viewerImage.style.height = `${imageHeight * zoom}px`
  zoomLabel.value = `${Math.round(zoom * 100)}%`
  zoomIn.disabled = zoom >= 3
  zoomOut.disabled = zoom <= 0.05
  if (previousWidth) {
    const scale = viewerImage.width / previousWidth
    viewport.scrollLeft = centerX * scale - viewport.clientWidth / 2
    viewport.scrollTop = centerY * scale - viewport.clientHeight / 2
  }
}

function fitImage() {
  const padding = parseFloat(getComputedStyle(viewport.firstElementChild).paddingLeft) * 2
  setZoom(Math.min(1, (viewport.clientWidth - padding) / imageWidth, (viewport.clientHeight - padding) / imageHeight))
  viewport.scrollLeft = 0
  viewport.scrollTop = 0
}

document.addEventListener('click', (event) => {
  const trigger = event.target.closest('.screenshot-link')
  if (!trigger || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  if (typeof viewer.showModal !== 'function') return
  event.preventDefault()
  imageTrigger = trigger
  const image = trigger.querySelector('img')
  imageWidth = Number(image.getAttribute('width'))
  imageHeight = Number(image.getAttribute('height'))
  viewerImage.src = image.src
  viewerImage.alt = image.alt
  const figure = trigger.closest('.figure')
  const caption = figure?.nextElementSibling
  const heading = trigger.closest('.manual-section')?.querySelector('h2')
  viewerTitle.textContent = caption?.classList.contains('caption') ? caption.textContent : heading?.textContent || '查看截图'
  fitMode = true
  viewer.showModal()
  fitImage()
})

viewer.addEventListener('click', (event) => {
  const action = event.target.closest('[data-image-action]')?.dataset.imageAction
  if (action === 'close') viewer.close()
  else if (action === 'fit') { fitMode = true; fitImage() }
  else if (action) {
    fitMode = false
    if (action === 'original') setZoom(1)
    if (action === 'in') setZoom(zoom * 1.25)
    if (action === 'out') setZoom(zoom / 1.25)
  }
  if (event.target === viewer) {
    const box = viewer.getBoundingClientRect()
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) viewer.close()
  }
})
viewer.addEventListener('close', () => imageTrigger?.focus({ preventScroll: true }))
window.addEventListener('resize', () => { if (viewer.open && fitMode) fitImage() })
