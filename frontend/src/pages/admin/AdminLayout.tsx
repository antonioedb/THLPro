import { NavLink, Outlet } from 'react-router-dom'

const links = [
  { to: '/admin/users', label: 'Usuários' },
  { to: '/admin/assets', label: 'Ativos' },
  { to: '/admin/clients', label: 'Clientes/Diagnóstico' },
  { to: '/admin/logs', label: 'Logs' },
  { to: '/admin/sync', label: 'Sincronização B3' },
]

export default function AdminLayout() {
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Administração</h2>
      <div className="flex flex-wrap gap-2">
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} className="btn-secondary">
            {l.label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  )
}
