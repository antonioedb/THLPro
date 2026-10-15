import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { SyncSummary } from '../../types/api'


export default function SeriesB3Page() {
  const [result, setResult] = useState<SyncSummary | null>(null)
  const [error, setError] = useState('')


  const syncMutation = useMutation({
    mutationFn: async () =>
      (
        await api.post<SyncSummary>('/options/synchronize', {
          source: 'b3',
        })
      ).data,
    onSuccess: (data) => {
      setResult(data)
      setError('')
    },
    onError: (err: any) => {
      setError(
        err?.response?.data?.detail
          ?? 'Falha ao sincronizar as séries da B3.',
      )
      setResult(null)
    },
  })


  return (
    <div className="space-y-4">
      <section className="panel space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold">Séries autorizadas B3</h3>
            <p className="text-sm text-slate-500">
              Baixa o arquivo oficial da B3, importa as séries no banco e
              desativa as opções vencidas.
            </p>
          </div>


          <button
            className="btn-primary"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            {syncMutation.isPending
              ? 'Sincronizando…'
              : 'Sincronizar agora'}
          </button>
        </div>


        {error && (
          <p className="text-sm text-rose-500">{error}</p>
        )}


        {result && (
          <div className="rounded border border-slate-200 p-3 text-sm dark:border-slate-700">
            <p>
              Criadas: <strong>{result.created}</strong>
            </p>
            <p>
              Atualizadas: <strong>{result.updated}</strong>
            </p>
            <p>
              Desativadas: <strong>{result.deactivated}</strong>
            </p>
            <p>
              Erros:{' '}
              <strong>
                {result.errors.length
                  ? result.errors.join(', ')
                  : 'Nenhum'}
              </strong>
            </p>
          </div>
        )}
      </section>
    </div>
  )
}