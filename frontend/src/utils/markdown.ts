const escapeHtml = (value: string) =>
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')

function renderInline(value: string): string {
  const codeSpans: string[] = []
  let rendered = escapeHtml(value).replace(/`([^`\n]+)`/g, (_, code: string) => {
    const index = codeSpans.push(`<code>${code}</code>`) - 1
    return `\u0000CODE${index}\u0000`
  })
  rendered = rendered
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[\s（(])\*([^*\n]+)\*(?=$|[\s，。；：、）)])/g, '$1<em>$2</em>')
    .replace(/\u0000CODE(\d+)\u0000/g, (_, index: string) => codeSpans[Number(index)] ?? '')
  return rendered
}

function tableCells(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function isTableDivider(line: string): boolean {
  const cells = tableCells(line)
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function isBlockStart(lines: string[], index: number): boolean {
  const line = lines[index] ?? ''
  return (
    !line.trim()
    || /^#{1,6}\s+/.test(line)
    || /^```/.test(line.trim())
    || /^>\s?/.test(line)
    || /^[-*+]\s+/.test(line)
    || /^\d+[.)]\s+/.test(line)
    || (line.includes('|') && isTableDivider(lines[index + 1] ?? ''))
  )
}

/** Render the small, presentation-focused Markdown subset returned by the Agent. */
export function renderMarkdown(source: string): string {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const output: string[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index] ?? ''
    if (!line.trim()) {
      index += 1
      continue
    }

    const fence = line.trim().match(/^```([\w-]*)$/)
    if (fence) {
      const code: string[] = []
      index += 1
      while (index < lines.length && !/^```/.test((lines[index] ?? '').trim())) {
        code.push(lines[index] ?? '')
        index += 1
      }
      index += 1
      output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/)
    if (heading) {
      const level = heading[1]?.length ?? 2
      output.push(`<h${level}>${renderInline(heading[2] ?? '')}</h${level}>`)
      index += 1
      continue
    }

    if (line.includes('|') && isTableDivider(lines[index + 1] ?? '')) {
      const headers = tableCells(line)
      index += 2
      const rows: string[][] = []
      while (index < lines.length && (lines[index] ?? '').includes('|') && (lines[index] ?? '').trim()) {
        rows.push(tableCells(lines[index] ?? ''))
        index += 1
      }
      output.push(
        `<div class="markdown-table-wrap"><table><thead><tr>${headers
          .map((cell) => `<th>${renderInline(cell)}</th>`)
          .join('')}</tr></thead><tbody>${rows
          .map(
            (row) =>
              `<tr>${headers
                .map((_, cellIndex) => `<td>${renderInline(row[cellIndex] ?? '')}</td>`)
                .join('')}</tr>`,
          )
          .join('')}</tbody></table></div>`,
      )
      continue
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/)
    const ordered = line.match(/^\d+[.)]\s+(.+)$/)
    if (unordered || ordered) {
      const tag = ordered ? 'ol' : 'ul'
      const items: string[] = []
      const pattern = ordered ? /^\d+[.)]\s+(.+)$/ : /^[-*+]\s+(.+)$/
      while (index < lines.length) {
        const item = (lines[index] ?? '').match(pattern)
        if (!item) break
        items.push(`<li>${renderInline(item[1] ?? '')}</li>`)
        index += 1
      }
      output.push(`<${tag}>${items.join('')}</${tag}>`)
      continue
    }

    if (/^>\s?/.test(line)) {
      const quote: string[] = []
      while (index < lines.length && /^>\s?/.test(lines[index] ?? '')) {
        quote.push((lines[index] ?? '').replace(/^>\s?/, ''))
        index += 1
      }
      output.push(`<blockquote>${renderInline(quote.join(' '))}</blockquote>`)
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length && !isBlockStart(lines, index)) {
      paragraph.push(lines[index]?.trim() ?? '')
      index += 1
    }
    if (paragraph.length) {
      output.push(`<p>${paragraph.map(renderInline).join('<br>')}</p>`)
    }
  }

  return output.join('')
}
