/**
 * auth store — JWT access token (memory only) + user state.
 * Refresh token lives in an httpOnly cookie, never touched by JS.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(null)   // stored in memory ONLY — never localStorage
  const user = ref(null)          // { id, username, email, is_admin, ... }
  const loading = ref(false)

  const isAuthenticated = computed(() => !!accessToken.value)
  const isAdmin = computed(() => !!user.value?.is_admin)

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  async function login(username, password) {
    loading.value = true
    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Login failed')
      }
      const data = await res.json()
      accessToken.value = data.access_token
      await fetchMe()
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      await fetch('/auth/logout', {
        method: 'POST',
        credentials: 'include',
        headers: accessToken.value
          ? { Authorization: `Bearer ${accessToken.value}` }
          : {},
      })
    } catch {
      // best-effort
    } finally {
      accessToken.value = null
      user.value = null
    }
  }

  async function refresh() {
    try {
      const res = await fetch('/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        accessToken.value = null
        user.value = null
        return false
      }
      const data = await res.json()
      accessToken.value = data.access_token
      await fetchMe()
      return true
    } catch {
      accessToken.value = null
      user.value = null
      return false
    }
  }

  async function fetchMe() {
    if (!accessToken.value) return
    try {
      const res = await fetch('/auth/me', {
        headers: { Authorization: `Bearer ${accessToken.value}` },
        credentials: 'include',
      })
      if (res.ok) {
        user.value = await res.json()
      }
    } catch {
      // non-fatal
    }
  }

  return {
    accessToken,
    user,
    loading,
    isAuthenticated,
    isAdmin,
    login,
    logout,
    refresh,
    fetchMe,
  }
})
