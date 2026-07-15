export type JsonRecord = Record<string, any>

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const text = await response.text()
  let payload: any = text
  try { payload = text ? JSON.parse(text) : null } catch { /* keep text */ }
  if (!response.ok) {
    const detail = payload?.detail?.message || payload?.detail || payload?.message || text
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return payload as T
}

export const api = {
  get<T = JsonRecord>(url: string) { return request<T>(url) },
  post<T = JsonRecord>(url: string, body?: unknown) {
    return request<T>(url, {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  put<T = JsonRecord>(url: string, body: unknown) {
    return request<T>(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
  upload<T = JsonRecord>(url: string, field: string, file: File) {
    const data = new FormData()
    data.append(field, file)
    return request<T>(url, { method: 'POST', body: data })
  },
}

export const pretty = (value: unknown) => JSON.stringify(value, null, 2)
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error)
export const tone = (status?: string | boolean) => {
  if (status === true || ['ok', 'success', 'ready', 'indexed'].includes(String(status))) return 'ok'
  if (['warning', 'warn', 'pending', 'running'].includes(String(status))) return 'warn'
  if (status === false || ['failed', 'error', 'bad'].includes(String(status))) return 'bad'
  return 'neutral'
}
