// Give older single-paragraph answers spacing without changing their wording.
export function formatAssistantAnswer(text) {
  if (text.length < 160 || /\n|\*\*|^#{1,3}\s/.test(text)) return text
  const sentences = text.match(/[^。！？]+[。！？]?/g) || []
  if (sentences.length < 3) return text
  const [conclusion, ...rest] = sentences
  const scope = rest.filter(sentence => /^\s*口径/.test(sentence))
  const evidence = rest.filter(sentence => !/^\s*口径/.test(sentence))
  return [
    `**${conclusion.startsWith('结论') ? '' : '结论：'}${conclusion.trim()}**`,
    evidence.length ? `依据：\n${evidence.map(sentence => '- ' + sentence.trim()).join('\n')}` : '',
    ...scope.map(sentence => sentence.trim()),
  ].filter(Boolean).join('\n\n')
}
