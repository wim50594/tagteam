import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { APP_NAME } from '../lib/constants'

export default function LoginPage() {
  const { login, user } = useAuth()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [hasUsers, setHasUsers] = useState(true)

  useEffect(() => {
    if (user) { navigate('/'); return }
    api.get('/api/auth/check-setup').then(r => {
      if (!r.has_users) navigate('/register')
      setHasUsers(r.has_users)
    }).catch(() => {
      setError('')
    })
  }, [user])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username.trim(), password)
      navigate('/')
    } catch (err) {
      setError(err.message || t('auth.loginButton'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-100 to-indigo-50 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <span className="text-5xl">🏷️</span>
          <h1 className="text-2xl font-black text-indigo-600 mt-2">{APP_NAME}</h1>
          <p className="text-sm text-slate-500 mt-1">{t('auth.login')}</p>
        </div>

        <form onSubmit={handleSubmit} className="card space-y-4">
          <div>
            <label className="block text-xs font-bold text-slate-600 mb-1 uppercase tracking-wide">
              {t('auth.username')}
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
              className="input-base"
            />
          </div>
          <div>
            <label className="block text-xs font-bold text-slate-600 mb-1 uppercase tracking-wide">
              {t('auth.password')}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="input-base"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700 font-medium">
              ⚠ {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="btn-primary w-full justify-center py-2.5"
          >
            {loading ? '…' : t('auth.loginButton')}
          </button>
        </form>

        {hasUsers && (
          <p className="text-center text-xs text-slate-400 mt-4">
            {t('auth.needsInvite')}
          </p>
        )}
      </div>
    </div>
  )
}
