/**
 * Auth context and helpers.
 * Access token + user info are persisted to localStorage; the refresh
 * token lives in an httpOnly cookie set by the backend (never touched
 * here directly - the browser sends it automatically, see lib/api.js).
 */
import { createContext, useContext, useState, useCallback } from 'react'
import { api } from './api'

export const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

export function useProvideAuth() {
  const stored = localStorage.getItem('tt_user')
  const [user, setUser] = useState(stored ? JSON.parse(stored) : null)

  const login = useCallback(async (username, password) => {
    const data = await api.login(username, password)
    localStorage.setItem('tt_token', data.access_token)
    localStorage.setItem('tt_user', JSON.stringify(data.user))
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(() => {
    // Best-effort: clear the refresh cookie server-side too. We don't
    // await/block on this - local state is cleared regardless, and a
    // failed request here (e.g. already offline) shouldn't prevent logout.
    api.logout().catch(() => {})
    localStorage.removeItem('tt_token')
    localStorage.removeItem('tt_user')
    setUser(null)
  }, [])

  return { user, login, logout, isAdmin: user?.role === 'admin' }
}