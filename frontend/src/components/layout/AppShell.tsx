import { Link, NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../store/auth'

export function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <Link to="/" className="text-xl font-bold text-sky-600 dark:text-sky-400">THLPro</Link>
            <nav className="hidden gap-3 md:flex">
              <NavLink to="/" className="nav-link">Painel</NavLink>
              {user?.role === 'admin' && <NavLink to="/admin/users" className="nav-link">Admin</NavLink>}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span>{user?.name}</span>
            <button onClick={() => logout()} className="btn-secondary">Sair</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] p-4">
        <Outlet />
      </main>
    </div>
  )
}
