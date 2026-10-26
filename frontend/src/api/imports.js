import { client, getToken } from './client.js'

export const listImportKinds = () => client.get('/api/imports/')

/** Preview (commit=false) or run an import. Returns the server's result. */
export function runImport(kind, { file, store, commit }) {
  const body = new FormData()
  body.append('file', file)
  if (store) body.append('store', store)
  body.append('commit', commit ? 'true' : 'false')
  return client.post(`/api/imports/${kind}/`, body)
}

/** Downloads the CSV template for an import kind (needs the auth header, so not a plain link). */
export async function downloadImportTemplate(kind) {
  const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  const response = await fetch(`${base.replace(/\/$/, '')}/api/imports/${kind}/template/`, {
    headers: { Authorization: `Token ${getToken()}` },
  })
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${kind}-template.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
