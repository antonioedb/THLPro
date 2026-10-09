import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { Asset } from '../../types/api'

export default function AssetsPage() {
  const queryClient = useQueryClient()
  const assets = useQuery({
    queryKey: ['assets-admin'],
    queryFn: async () => (await api.get<Asset[]>('/assets')).data,
  })

  return (
    <div className="panel space-y-4">
      <h3 className="text-lg font-semibold">Ativos</h3>
      <table className="table">
        <thead><tr><th>Símbolo</th><th>Nome</th><th>Tick</th><th>Faixa %</th><th>Status</th><th>Ações</th></tr></thead>
        <tbody>
          {assets.data?.map((a) => (
            <tr key={a.id}>
              <td>{a.symbol}</td><td>{a.name}</td><td>{a.tick_min}</td><td>{a.lower_range_percent} / {a.upper_range_percent}</td>
              <td>{a.enabled ? 'Habilitado' : 'Desabilitado'}</td>
              <td><button className="btn-secondary" onClick={async () => { await api.put(`/assets/${a.id}`, { enabled: !a.enabled }); queryClient.invalidateQueries({ queryKey: ['assets-admin'] }) }}>{a.enabled ? 'Desabilitar' : 'Habilitar'}</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
