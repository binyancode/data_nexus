function displayScalar(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'number') {
    return Number.isFinite(value)
      ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(value)
      : String(value)
  }
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}

function markdownCell(value: unknown): string {
  return displayScalar(value)
    .replace(/\\/g, '\\\\')
    .replace(/\|/g, '\\|')
    .replace(/\r?\n/g, '<br>')
}

function markdownTable(rows: Record<string, unknown>[]): string {
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))]
  if (!headers.length) return '—'
  const head = `| ${headers.map(markdownCell).join(' | ')} |`
  const divider = `| ${headers.map(() => '---').join(' | ')} |`
  const body = rows.map((row) => `| ${headers.map((header) => markdownCell(row[header])).join(' | ')} |`)
  return [head, divider, ...body].join('\n')
}

export function formatLineageValue(value: unknown): string {
  if (value == null) return '—'
  if (Array.isArray(value)) {
    if (!value.length) return '—'
    if (value.every((item) => item != null && typeof item === 'object' && !Array.isArray(item))) {
      return markdownTable(value as Record<string, unknown>[])
    }
    return value.map(displayScalar).join('、')
  }
  if (typeof value === 'object') {
    const row = value as Record<string, unknown>
    const keys = Object.keys(row)
    if (keys.length === 1 && keys[0] === 'value') return formatLineageValue(row.value)
    return markdownTable([row])
  }
  return displayScalar(value)
}

export function isUrlValue(value: unknown): boolean {
  return typeof value === 'string' && /^https?:\/\//i.test(value)
}

export function hasMarkdown(value: string): boolean {
  return /(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|\|.+\||```)|\*\*[^*]+\*\*|__[^_]+__/m.test(value || '')
}
