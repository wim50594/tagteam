/**
 * Auth context and helpers.
 * Access token + user info are persisted to localStorage; the refresh
 * token lives in an httpOnly cookie set by the backend (never touched
 * here directly - the browser sends it automatically, see lib/api.js).
 */
import { createContext, useContext, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'

export const AuthContext = createContext(null)

export function useAuth() {
  return useContext(AuthContext)
}

export function useProvideAuth() {
  const stored = localStorage.getItem('tt_user')
  const [user, setUser] = useState(stored ? JSON.parse(stored) : null)
  const { i18n } = useTranslation()

  const login = useCallback(async (username, password) => {
    const data = await api.login(username, password)
    localStorage.setItem('tt_token', data.access_token)
    localStorage.setItem('tt_user', JSON.stringify(data.user))
    setUser(data.user)
    i18n.changeLanguage(data.user.language || 'en')
    return data.user
  }, [i18n])

  const logout = useCallback(() => {
    api.logout().catch(() => {})
    localStorage.removeItem('tt_token')
    localStorage.removeItem('tt_user')
    setUser(null)
  }, [])

  const updateUser = useCallback((updated) => {
    localStorage.setItem('tt_user', JSON.stringify(updated))
    setUser(updated)
    if (updated.language) i18n.changeLanguage(updated.language)
  }, [i18n])

  const setLanguage = useCallback(async (lang) => {
    await api.put('/api/auth/language', { body: { language: lang } })
    const updated = { ...user, language: lang }
    localStorage.setItem('tt_user', JSON.stringify(updated))
    setUser(updated)
    i18n.changeLanguage(lang)
  }, [user, i18n])

  const setAuth = useCallback((token, userData) => {
    localStorage.setItem('tt_token', token)
    localStorage.setItem('tt_user', JSON.stringify(userData))
    setUser(userData)
    i18n.changeLanguage(userData.language || 'en')
  }, [i18n])

  return { user, login, logout, updateUser, setLanguage, setAuth, isAdmin: user?.role === 'admin' }
}