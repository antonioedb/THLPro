import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { UserOut } from '../../types/api'
import { useState } from 'react'

export default function UsersPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('user')

  const users = useQuery({
    queryKey: ['users'],
    queryFn: async () => (await api.get<UserOut[]>('/users')).data,
  })

  return (
    <div className="panel space-y-4">
      <h3 className="text-lg font-semibold">Usuários</h3>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-5">
        <input className="input" placeholder="Nome" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input" placeholder="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="input" type="password" placeholder="Senha" value={password} onChange={(e) => setPassword(e.target.value)} />
        <select className="input" value={role} onChange={(e) => setRole(e.target.value)}><option value="user">Usuário</option><option value="admin">Admin</option></select>
        <button className="btn-primary" onClick={async () => {
          await api.post('/users', { name, email, password, role })
          setName(''); setEmail(''); setPassword(''); setRole('user')
          queryClient.invalidateQueries({ queryKey: ['users'] })
        }}>Criar usuário</button>
      </div>
      <table className="table">
        <thead><tr><th>ID</th><th>Nome</th><th>E-mail</th><th>Perfil</th><th>Status</th><th>Ações</th></tr></thead>
        <tbody>
          {users.data?.map((u) => (
            <tr key={u.id}>
              <td>{u.id}</td><td>{u.name}</td><td>{u.email}</td><td>{u.role}</td><td>{u.active ? 'Ativo' : 'Inativo'}</td>
              <td className="space-x-2">
                <button className="btn-secondary" onClick={async () => { await api.put(`/users/${u.id}`, { active: !u.active }); queryClient.invalidateQueries({ queryKey: ['users'] }) }}>{u.active ? 'Desativar' : 'Ativar'}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
