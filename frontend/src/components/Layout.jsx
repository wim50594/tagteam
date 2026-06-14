import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { formatVersionBadge, useVersion } from '../lib/version';

import { useAuth } from '../lib/auth';

const ROLE_BADGE = {
  admin: 'bg-violet-100 text-violet-800 border-violet-200',
  annotator: 'bg-teal-100 text-teal-800 border-teal-200',
}

export default function Layout() {
  const { user, isAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const version = useVersion()

  const handleLogout = () => { logout(); navigate('/login') }

  const navLink = (to, label) => (
    <Link
      to={to}
      className={`px-3 py-1.5 rounded-lg text-sm font-semibold transition
        ${location.pathname === to
          ? 'bg-indigo-600 text-white'
          : 'text-slate-500 hover:bg-slate-100'
        }`}
    >
      {label}
    </Link>
  )

  return (
    <div className="min-h-screen flex flex-col">
      {/* ── Navigation bar ── */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-40 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition">
            <span className="text-xl">🏷️</span>
            <span className="font-black text-indigo-600 tracking-tight text-lg">{APP_NAME}</span>
            <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-full font-semibold">
              {formatVersionBadge(version)}
            </span>
          </Link>

          {/* Nav links */}
          <nav className="flex items-center gap-1">
            {navLink('/', 'Projects')}
            {isAdmin && navLink('/users', 'Users')}
          </nav>

          {/* User badge + logout */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-bold text-slate-800 leading-none">
                  {user?.display_name}
                </p>
                <p className="text-xs text-slate-400 leading-none mt-0.5">@{user?.username}</p>
              </div>
              <span
                className={`text-xs font-bold px-2 py-0.5 rounded-full border ${ROLE_BADGE[user?.role] ?? ''}`}
              >
                {user?.role}
              </span>
            </div>
            <button
              onClick={handleLogout}
              className="btn-secondary !px-3 !py-1.5 !text-xs"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* ── Page content ── */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}