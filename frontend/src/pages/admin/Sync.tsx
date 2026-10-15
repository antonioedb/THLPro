import { useState } from 'react'
import { api } from '../../lib/api'
import type { SyncSummary } from '../../types/api'


export default function SyncPage() {
  const [result, setResult] = useState<SyncSummary | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)


  const run = async (source: 'b3' | 'upload') => {
    setError('')
    setLoading(true)

    try {
      const { data } = await api.post<SyncSummary>('/options/synchronize', { source })
      setResult(data)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Falha ao sincronizar')
    } finally {
      setLoading(false)
    }
  }


  return (
    <div className="space-y-4">
      <div className="panel space-y-3">
        <h3 className="text-lg font-semibold">Sincronização de séries B3</h3>
        <p className="text-sm text-slate-500">
          A sincronização automática ocorre todos os dias às 10:00.
        </p>


        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary"
            onClick={() => run('b3')}
            disabled={loading}
          >
            {loading ? 'Sincronizando…' : 'Sincronizar agora via B3'}
          </button>
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
    </div>
  )
}