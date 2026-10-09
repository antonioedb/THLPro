import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useState } from 'react'
import type { AdminLog } from '../../types/api'

export default function LogsPage() {
  const [eventType, setEventType] = useState('')
  const logs = useQuery({
    queryKey: ['logs', eventType],
    queryFn: async () => (await api.get<AdminLog[]>('/admin/logs', { params: { event_type: eventType || undefined, limit: 200 } })).data,
  })

  return (
    <div className="panel space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-lg font-semibold">Logs</h3>
        <input className="input max-w-xs" placeholder="Filtrar por event_type" value={eventType} onChange={(e) => setEventType(e.target.value)} />
      </div>
      <table className="table">
        <thead><tr><th>Data</th><th>Tipo</th><th>Mensagem</th><th>Resumo</th></tr></thead>
        <tbody>
          {logs.data?.map((l) => (
            <tr key={l.id}><td>{new Date(l.created_at).toLocaleString('pt-BR')}</td><td>{l.event_type}</td><td>{l.message}</td><td>{l.payload_summary || '—'}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
