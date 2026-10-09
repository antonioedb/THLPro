import { useState } from 'react'
import { api } from '../../lib/api'
import type { SyncSummary } from '../../types/api'

export default function SyncPage() {
  const [result, setResult] = useState<SyncSummary | null>(null)
  const [asset, setAsset] = useState('BOVA11')
  const [error, setError] = useState('')

  const run = async (source: 'b3' | 'upload') => {
    setError('')
    try {
      const { data } = await api.post<SyncSummary>('/options/synchronize', { source })
      setResult(data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Falha ao sincronizar')
    }
  }

  return (
    <div className="space-y-4">
      <div className="panel space-y-3">
        <h3 className="text-lg font-semibold">Sincronização de séries B3</h3>
        <p className="text-sm text-slate-500">No backend atual, "upload" usa fonte local no servidor (fixture), sem endpoint multipart.</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" onClick={() => run('b3')}>Sincronizar via B3</button>
          <button className="btn-secondary" onClick={() => run('upload')}>Sincronizar via upload/local</button>
        </div>
        {error && <p className="text-sm text-rose-500">{error}</p>}
        {result && (
          <div className="rounded border border-slate-200 p-3 text-sm dark:border-slate-700">
            <p>Criadas: {result.created}</p>
            <p>Atualizadas: {result.updated}</p>
            <p>Desativadas: {result.deactivated}</p>
            <p>Erros: {result.errors.length ? result.errors.join(', ') : 'Nenhum'}</p>
          </div>
        )}
      </div>
      <div className="panel space-y-3">
        <h3 className="text-lg font-semibold">Gerar dados simulados (teste)</h3>
        <div className="flex gap-2">
          <input className="input max-w-xs" value={asset} onChange={(e) => setAsset(e.target.value.toUpperCase())} />
          <button className="btn-secondary" onClick={async () => {
            await api.post('/admin/simulation/generate', null, { params: { asset } })
            alert('Dados simulados gerados com sucesso.')
          }}>Gerar</button>
        </div>
      </div>
    </div>
  )
}
