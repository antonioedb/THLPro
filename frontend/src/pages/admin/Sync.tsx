import { useState } from 'react'
import { api } from '../../lib/api'
import type { SyncSummary } from '../../types/api'



export default function SyncPage() {
  const [b3Url, setB3Url] = useState('')
  const [result, setResult] = useState<SyncSummary | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)



  const run = async (source: 'b3' | 'upload') => {
    setError('')
    setLoading(true)


    try {
      const payload =
        source === 'b3'
          ? {
              source,
              b3_url: b3Url.trim() || null,
            }
          : {
              source,
            }


      const { data } = await api.post<SyncSummary>(
        '/options/synchronize',
        payload,
      )


      setResult(data)
    } catch (err: any) {
      setError(
        err?.response?.data?.detail
        || 'Falha ao sincronizar',
      )
    } finally {
      setLoading(false)
    }
  }



  return (
    <div className="space-y-4">
      <div className="panel space-y-3">
        <h3 className="text-lg font-semibold">
          Sincronização de séries B3
        </h3>


        <p className="text-sm text-slate-500">
          Cole o link atual do arquivo de séries autorizadas da B3
          antes de sincronizar. O link pode mudar conforme a data ou
          a atualização do arquivo.
        </p>


        <div className="rounded border border-sky-300 bg-sky-50 p-3 text-sm text-sky-800 dark:border-sky-700 dark:bg-sky-900/30 dark:text-sky-200">
          <p className="font-semibold">
            Onde pegar o link correto
          </p>


          <p>
            Abra a página de Séries Autorizadas da B3, clique com o botão direito em
            <strong> Lista Completa de Séries Autorizadas</strong>, copie o link e cole abaixo.
          </p>


          <a
            className="mt-2 inline-block break-all font-medium text-sky-700 underline dark:text-sky-300"
            href="https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/market-data/consultas/mercado-a-vista/opcoes/series-autorizadas/"
            target="_blank"
            rel="noreferrer"
          >
            Abrir página de Séries Autorizadas da B3
          </a>
        </div>



        <label className="field">
          <span>Link do arquivo de séries B3</span>


          <input
            className="input"
            type="url"
            placeholder="https://www.b3.com.br/lumis/portal/file/fileDownload.jsp?fileId=..."
            value={b3Url}
            onChange={(event) => setB3Url(event.target.value)}
            disabled={loading}
          />
        </label>



        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary"
            onClick={() => run('b3')}
            disabled={loading || !b3Url.trim()}
          >
            {loading
              ? 'Sincronizando…'
              : 'Sincronizar agora via B3'}
          </button>
        </div>



        {error && (
          <p className="text-sm text-rose-500">
            {error}
          </p>
        )}



        {result && (
          <div className="rounded border border-slate-200 p-3 text-sm dark:border-slate-700">
            <p>
              Criadas: {result.created}
            </p>


            <p>
              Atualizadas: {result.updated}
            </p>


            <p>
              Desativadas: {result.deactivated}
            </p>


            {result.warnings?.length ? (
              <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-amber-800 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
                <p className="font-semibold">
                  Atenção
                </p>


                {result.warnings.map((warning, index) => (
                  <p key={index}>
                    {warning}
                  </p>
                ))}
              </div>
            ) : null}


            {result.errors?.length ? (
              <div className="mt-3 rounded border border-rose-300 bg-rose-50 p-3 text-rose-700 dark:border-rose-700 dark:bg-rose-900/30 dark:text-rose-200">
                <p className="font-semibold">
                  Erros
                </p>


                {result.errors.map((item, index) => (
                  <p key={index}>
                    {item}
                  </p>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-emerald-600 dark:text-emerald-400">
                Nenhum erro.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}