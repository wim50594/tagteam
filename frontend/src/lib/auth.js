/**
 * Auth context and helpers.
 * Token and user info are persisted to localStorage.
 */
import { createContext, useContext, useState, useCallback } from 'react'
import { api } from './api'

export const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

export function useProvideAuth() {
  const stored = localStorage.getItem('mt_user')
  const [user, setUser] = useState(stored ? JSON.parse(stored) : null)

  const login = useCallback(async (username, password) => {
    const data = await api.login(username, password)
    localStorage.setItem('mt_token', data.access_token)
    localStorage.setItem('mt_user', JSON.stringify(data.user))
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('mt_token')
    localStorage.removeItem('mt_user')
    setUser(null)
  }, [])

  return { user, login, logout, isAdmin: user?.role === 'admin' }
}
