import { useMemo, useState } from 'react'
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'


import { api } from '../../lib/api'
import type { Asset } from '../../types/api'



type StatusFilter = 'all' | 'enabled' | 'disabled'


type AssetUpdatePayload = {
  enabled?: boolean
  lower_range_percent?: number
  upper_range_percent?: number
}


type UpdateVariables = {
  id: Asset['id']
  symbol: string
  action: 'toggle' | 'range'
  payload: AssetUpdatePayload
}



function getErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null) {
    const apiError = error as {
      response?: {
        data?: {
          detail?: unknown
        }
      }
    }


    const detail = apiError.response?.data?.detail


    if (typeof detail === 'string') {
      return detail
    }


    if (Array.isArray(detail)) {
      const messages = detail
        .map((item: unknown) => {
          if (
            typeof item === 'object'
            && item !== null
            && 'msg' in item
            && typeof item.msg === 'string'
          ) {
            return item.msg
          }


          return null
        })
        .filter((message): message is string => message !== null)


      if (messages.length) {
        return messages.join(' ')
      }
    }
  }


  return 'Não foi possível concluir a operação. Tente novamente.'
}



function normalizePercent(value: string): number | null {
  const normalized = value.trim().replace(',', '.')


  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) {
    return null
  }


  const number = Number(normalized)


  if (!Number.isFinite(number) || number < 0) {
    return null
  }


  return Number(number.toFixed(2))
}



export default function AssetsPage() {
  const queryClient = useQueryClient()


  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] =
    useState<StatusFilter>('all')


  const [editingId, setEditingId] =
    useState<Asset['id'] | null>(null)


  const [lowerRange, setLowerRange] = useState('')
  const [upperRange, setUpperRange] = useState('')


  const [successMessage, setSuccessMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')


  const assets = useQuery({
    queryKey: ['assets-admin'],
    queryFn: async () =>
      (await api.get<Asset[]>('/assets')).data,
  })


  const updateMutation = useMutation({
    mutationFn: async ({
      id,
      payload,
    }: UpdateVariables) => {
      await api.put(`/assets/${id}`, payload)
    },


    onMutate: () => {
      setSuccessMessage('')
      setErrorMessage('')
    },


    onSuccess: async (_data, variables) => {
      if (variables.action === 'range') {
        setEditingId(null)
        setSuccessMessage(
          `Faixa de ${variables.symbol} salva com sucesso.`,
        )
      } else {
        setSuccessMessage(
          `${variables.symbol} ${
            variables.payload.enabled
              ? 'habilitado'
              : 'desabilitado'
          } com sucesso.`,
        )
      }


      await queryClient.invalidateQueries({
        queryKey: ['assets-admin'],
      })
    },


    onError: (error: unknown) => {
      setErrorMessage(getErrorMessage(error))
    },
  })


  const filteredAssets = useMemo(() => {
    const term = search.trim().toLocaleLowerCase()


    return [...(assets.data ?? [])]
      .filter((asset) => {
        const matchesSearch =
          !term
          || asset.symbol.toLocaleLowerCase().includes(term)
          || (asset.name ?? '')
            .toLocaleLowerCase()
            .includes(term)


        const matchesStatus =
          statusFilter === 'all'
          || (
            statusFilter === 'enabled'
            && asset.enabled
          )
          || (
            statusFilter === 'disabled'
            && !asset.enabled
          )


        return matchesSearch && matchesStatus
      })
      .sort((a, b) => a.symbol.localeCompare(b.symbol))
  }, [assets.data, search, statusFilter])


  const enabledCount = (assets.data ?? []).filter(
    (asset) => asset.enabled,
  ).length


  const disabledCount =
    (assets.data?.length ?? 0) - enabledCount


  function startEditing(asset: Asset) {
    setEditingId(asset.id)


    setLowerRange(
      String(asset.lower_range_percent ?? ''),
    )


    setUpperRange(
      String(asset.upper_range_percent ?? ''),
    )


    setErrorMessage('')
    setSuccessMessage('')
  }


  function cancelEditing() {
    setEditingId(null)
    setLowerRange('')
    setUpperRange('')
    setErrorMessage('')
  }


  function saveRange(asset: Asset) {
    const lower = normalizePercent(lowerRange)
    const upper = normalizePercent(upperRange)


    if (lower === null || upper === null) {
      setErrorMessage(
        'Informe as duas faixas com valores não negativos '
        + 'e no máximo duas casas decimais. Exemplo: 10,00.',
      )
      return
    }


    updateMutation.mutate({
      id: asset.id,
      symbol: asset.symbol,
      action: 'range',
      payload: {
        lower_range_percent: lower,
        upper_range_percent: upper,
      },
    })
  }


  function toggleEnabled(asset: Asset) {
    updateMutation.mutate({
      id: asset.id,
      symbol: asset.symbol,
      action: 'toggle',
      payload: {
        enabled: !asset.enabled,
      },
    })
  }


  return (
    <div className="panel space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">
            Ativos
          </h3>


          <p className="text-sm text-slate-500">
            Gerencie a habilitação dos ativos e suas faixas
            inferior e superior.
          </p>
        </div>


        <div className="text-sm text-slate-500">
          {enabledCount} habilitados
          {' • '}
          {disabledCount} desabilitados
        </div>
      </div>


      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="field">
          <span>Buscar ativo</span>


          <input
            className="input"
            type="search"
            placeholder="Símbolo ou nome. Ex.: PETR4"
            value={search}
            onChange={(event) =>
              setSearch(event.target.value)
            }
          />
        </label>


        <label className="field">
          <span>Status</span>


          <select
            className="input"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(
                event.target.value as StatusFilter,
              )
            }
          >
            <option value="all">Todos</option>
            <option value="enabled">Habilitados</option>
            <option value="disabled">
              Desabilitados
            </option>
          </select>
        </label>
      </div>


      {successMessage && (
        <p
          role="status"
          className="text-sm text-emerald-600 dark:text-emerald-400"
        >
          {successMessage}
        </p>
      )}


      {errorMessage && (
        <p
          role="alert"
          className="text-sm text-rose-600 dark:text-rose-400"
        >
          {errorMessage}
        </p>
      )}


      {assets.isError && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3"
        >
          <p className="text-sm text-rose-600 dark:text-rose-400">
            Falha ao carregar os ativos.{' '}
            {getErrorMessage(assets.error)}
          </p>


          <button
            type="button"
            className="btn-secondary"
            onClick={() => void assets.refetch()}
            disabled={assets.isFetching}
          >
            Tentar novamente
          </button>
        </div>
      )}


      <div className="overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Símbolo</th>
              <th>Nome</th>
              <th>Tick</th>
              <th>Faixa % — inferior / superior</th>
              <th>Status</th>
              <th>Ações</th>
            </tr>
          </thead>


          <tbody>
            {assets.isPending && (
              <tr>
                <td
                  colSpan={6}
                  className="text-center text-slate-500"
                >
                  Carregando ativos…
                </td>
              </tr>
            )}


            {filteredAssets.map((asset) => {
              const isEditing = editingId === asset.id


              const isUpdatingThisAsset =
                updateMutation.isPending
                && updateMutation.variables?.id === asset.id


              const isSavingRange =
                isUpdatingThisAsset
                && updateMutation.variables?.action === 'range'


              const isToggling =
                isUpdatingThisAsset
                && updateMutation.variables?.action === 'toggle'


              return (
                <tr key={asset.id}>
                  <td className="font-medium">
                    {asset.symbol}
                  </td>


                  <td>{asset.name}</td>


                  <td>{asset.tick_min}</td>


                  <td>
                    {isEditing ? (
                      <div className="flex items-end gap-2">
                        <label className="field">
                          <span className="text-xs">
                            Inferior %
                          </span>


                          <input
                            className="input w-28"
                            type="text"
                            inputMode="decimal"
                            aria-label={
                              `Faixa inferior de ${asset.symbol}`
                            }
                            value={lowerRange}
                            disabled={updateMutation.isPending}
                            onChange={(event) =>
                              setLowerRange(event.target.value)
                            }
                          />
                        </label>


                        <label className="field">
                          <span className="text-xs">
                            Superior %
                          </span>


                          <input
                            className="input w-28"
                            type="text"
                            inputMode="decimal"
                            aria-label={
                              `Faixa superior de ${asset.symbol}`
                            }
                            value={upperRange}
                            disabled={updateMutation.isPending}
                            onChange={(event) =>
                              setUpperRange(event.target.value)
                            }
                          />
                        </label>
                      </div>
                    ) : (
                      <>
                        {asset.lower_range_percent}
                        {' / '}
                        {asset.upper_range_percent}
                      </>
                    )}
                  </td>


                  <td>
                    <span
                      className={
                        asset.enabled
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-slate-500'
                      }
                    >
                      {asset.enabled
                        ? 'Habilitado'
                        : 'Desabilitado'}
                    </span>
                  </td>


                  <td>
                    <div className="flex flex-wrap gap-2">
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            className="btn-primary"
                            disabled={updateMutation.isPending}
                            onClick={() => saveRange(asset)}
                          >
                            {isSavingRange
                              ? 'Salvando…'
                              : 'Salvar faixa'}
                          </button>


                          <button
                            type="button"
                            className="btn-secondary"
                            disabled={updateMutation.isPending}
                            onClick={cancelEditing}
                          >
                            Cancelar
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="btn-secondary"
                            disabled={
                              updateMutation.isPending
                              || editingId !== null
                            }
                            onClick={() =>
                              startEditing(asset)
                            }
                          >
                            Editar faixa
                          </button>


                          <button
                            type="button"
                            className={
                              asset.enabled
                                ? 'btn-secondary'
                                : 'btn-primary'
                            }
                            disabled={
                              updateMutation.isPending
                              || editingId !== null
                            }
                            onClick={() =>
                              toggleEnabled(asset)
                            }
                          >
                            {isToggling
                              ? 'Salvando…'
                              : asset.enabled
                                ? 'Desabilitar'
                                : 'Habilitar'}
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}


            {assets.isSuccess
              && filteredAssets.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="text-center text-slate-500"
                  >
                    Nenhum ativo encontrado com os filtros
                    atuais.
                  </td>
                </tr>
              )}
          </tbody>
        </table>
      </div>


      {assets.isSuccess && (
        <p className="text-xs text-slate-500">
          Exibindo {filteredAssets.length} de{' '}
          {assets.data.length} ativos.
          As faixas inferior e superior podem ter valores
          diferentes.
        </p>
      )}
    </div>
  )
}