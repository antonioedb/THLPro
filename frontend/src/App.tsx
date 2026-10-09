import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './store/auth'
import LoginPage from './pages/Login'
import { AppShell } from './components/layout/AppShell'
import MainPage from './pages/Main'
import AdminLayout from './pages/admin/AdminLayout'
import UsersPage from './pages/admin/Users'
import AssetsPage from './pages/admin/Assets'
import ClientsPage from './pages/admin/Clients'
import LogsPage from './pages/admin/Logs'
import SyncPage from './pages/admin/Sync'

function Protected() {
  const { user, loading } = useAuth()
  if (loading) return <div className="center-screen">Carregando...</div>
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}

function AdminOnly() {
  const { user } = useAuth()
  if (user?.role !== 'admin') return <Navigate to="/" replace />
  return <Outlet />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<MainPage />} />
          <Route path="/admin" element={<AdminOnly />}>
            <Route element={<AdminLayout />}>
              <Route path="users" element={<UsersPage />} />
              <Route path="assets" element={<AssetsPage />} />
              <Route path="clients" element={<ClientsPage />} />
              <Route path="logs" element={<LogsPage />} />
              <Route path="sync" element={<SyncPage />} />
            </Route>
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
