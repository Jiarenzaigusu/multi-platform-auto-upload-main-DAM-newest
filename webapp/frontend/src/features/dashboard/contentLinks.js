export function contentDetailUrl(contentId, contentType = 'image') {
  const type = contentType === 'image' ? 'article' : 'video'
  return 'https://creator.guanghe.taobao.com/page/unify/contentDetail?contentId='
    + encodeURIComponent(contentId) + '&tab=1&mode=0&contentType=' + type + '&source=guanghe'
}

export function linkWorkNames(text, evidence, contentType) {
  const works = new Map()
  for (const entry of evidence || []) {
    if (!['rank_contents', 'get_content_references'].includes(entry.tool) || !Array.isArray(entry.result)) continue
    for (const work of entry.result) {
      const title = String(work.label || work.title || '').trim()
      if (!title || !work.content_id) continue
      const url = contentDetailUrl(work.content_id, contentType)
      works.set(title, works.has(title) && works.get(title) !== url ? null : url)
    }
  }
  const names = [...works.keys()].filter(name => works.get(name)).sort((a, b) => b.length - a.length)
  if (!names.length) return [{ text }]
  const pattern = new RegExp(names.map(name => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g')
  const parts = []
  let start = 0
  for (const match of text.matchAll(pattern)) {
    if (match.index > start) parts.push({ text: text.slice(start, match.index) })
    parts.push({ text: match[0], href: works.get(match[0]) })
    start = match.index + match[0].length
  }
  if (start < text.length) parts.push({ text: text.slice(start) })
  return parts
}
