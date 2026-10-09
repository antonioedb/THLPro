import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { fmtTime } from '../../lib/format'
import type { ClientStatusItem } from '../../types/api'

export default function ClientsPage() {
  const queryClient = useQueryClient()
  const clients = useQuery({ queryKey: ['clients-status'], queryFn: async () => (await api.get<ClientStatusItem[]>('/clients/status')).data })

  return (
    <div className="panel space-y-4">
      <h3 className="text-lg font-semibold">Clientes e diagnóstico</h3>
      <table className="table">
        <thead><tr><th>ID</th><th>Cliente</th><th>Computador</th><th>Conectado</th><th>Último heartbeat</th><th>Erro</th><th>Ações</th></tr></thead>
        <tbody>
          {clients.data?.map((c) => (
            <tr key={c.id}>
              <td>{c.id}</td><td>{c.client_name}</td><td>{c.computer_name}</td><td>{c.connected ? 'Sim' : 'Não'}</td><td>{fmtTime(c.last_seen_at)}</td><td>{c.last_error || '—'}</td>
              <td className="space-x-2">
                <button className="btn-secondary" onClick={async () => { await api.post(`/clients/${c.id}/disconnect`); queryClient.invalidateQueries({ queryKey: ['clients-status'] }) }}>Desconectar</button>
                <button className="btn-secondary" onClick={async () => { await api.post(`/clients/${c.id}/reconnect`); queryClient.invalidateQueries({ queryKey: ['clients-status'] }) }}>Reconectar</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
