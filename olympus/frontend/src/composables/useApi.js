/**
 * useApi — fetch wrapper with automatic 401 → /auth/refresh retry.
 *
 * Usage:
 *   const { apiFetch } = useApi()
 *   const data = await apiFetch('/api/conversations', { method: 'GET' })
 */
import { useAuthStore } from '../stores/auth'
import router from '../router/index'

let _refreshPromise = null  // deduplicate concurrent refresh calls

export function useApi() {
  async function apiFetch(url, options = {}) {
    const authStore = useAuthStore()
    const { _noContentType, ...fetchOptions } = options

    const headers = {
      ...(_noContentType ? {} : { 'Content-Type': 'application/json' }),
      ...(fetchOptions.headers || {}),
    }
    if (authStore.accessToken) {
      headers['Authorization'] = `Bearer ${authStore.accessToken}`
    }

    let res = await fetch(url, {
      ...fetchOptions,
      credentials: 'include',
      headers,
    })

    if (res.status === 401 && !fetchOptions._retry) {
      // Deduplicate: if a refresh is already in flight, wait for it
      if (!_refreshPromise) {
        _refreshPromise = authStore.refresh().finally(() => {
          _refreshPromise = null
        })
      }
      const ok = await _refreshPromise

      if (!ok) {
        authStore.accessToken = null
        authStore.user = null
        router.push('/login')
        throw new Error('Session expired')
      }

      // Retry once with the new token
      const retryHeaders = {
        ...headers,
        Authorization: `Bearer ${authStore.accessToken}`,
      }
      res = await fetch(url, {
        ...fetchOptions,
        _retry: true,
        credentials: 'include',
        headers: retryHeaders,
      })
    }

    return res
  }

  return { apiFetch }
}
