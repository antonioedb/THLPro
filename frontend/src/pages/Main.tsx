import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateMonth, fmtNumber, fmtTime } from '../lib/format'
import { useAuth } from '../store/auth'
import { defaultPreferences, usePreferences } from '../store/preferences'
import type {
  Asset,
  ByStrikeResponse,
  QuoteLatestResponse,
  SpotResponse,
  StrikeListResponse,
  SystemSetting,
} from '../types/api'
import { Badge } from '../components/ui/Badge'
import { PremiumChart } from '../components/charts/PremiumChart'
import { MarketWsClient } from '../lib/ws'


type Side = 'CALL' | 'PUT'


interface OptionRow {
  expiration_date: string
  option_symbol: string | null
  matched_strike: string | null
  requested_strike: string
  side: Side
  quote?: QuoteLatestResponse
}


function hasPositiveQuoteValue(value?: string | null): boolean {
  if (value === undefined || value === null || value === '') {
    return false
  }


  const numeric = Number(value)


  return Number.isFinite(numeric) && numeric > 0
}


function formatBookValue(value?: string | null): string {
  return hasPositiveQuoteValue(value) ? fmtNumber(value) : 'N/D'
}


function formatStrike(
  strike: string | null | undefined,
  assetSymbol: string,
): string {
  if (!strike) {
    return '—'
  }


  const numeric = Number(strike)


  if (!Number.isFinite(numeric)) {
    return strike
  }


  if (assetSymbol.toUpperCase().startsWith('BOVA')) {
    return numeric.toFixed(0)
  }


  return numeric.toFixed(2)
}


export default function MainPage() {
  const { user, token } = useAuth()
  const { prefs, setPrefs } = usePreferences()
  const queryClient = useQueryClient()


  const [wsStatus, setWsStatus] = useState<
    'connecting' | 'connected' | 'disconnected'
  >('disconnected')


  const [wsQuoteMap, setWsQuoteMap] = useState<
    Record<string, QuoteLatestResponse>
  >({})


  const [showSettings, setShowSettings] = useState(false)


  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])


  const assetsQuery = useQuery({
    queryKey: ['assets'],
    queryFn: async () =>
      (
        await api.get<Asset[]>('/assets', {
          params: { enabled: true },
        })
      ).data,
  })


  useEffect(() => {
    if (!assetsQuery.data?.length) {
      return
    }


    const selectedAssetExists = assetsQuery.data.some(
      (asset) => asset.symbol === prefs.selected_asset,
    )


    if (selectedAssetExists) {
      return
    }


    setPrefs((old) => ({
      ...old,
      selected_asset:
        assetsQuery.data?.[0].symbol
        ?? defaultPreferences.selected_asset,
    }))
  }, [
    assetsQuery.data,
    prefs.selected_asset,
    setPrefs,
  ])


  const strikesQuery = useQuery({
    queryKey: ['strikes', prefs.selected_asset],
    enabled: !!prefs.selected_asset,
    queryFn: async () =>
      (
        await api.get<StrikeListResponse>(
          `/assets/${prefs.selected_asset}/strikes`,
        )
      ).data,
  })


  const sortedStrikes = useMemo(() => {
    const strikes = strikesQuery.data?.strikes ?? []


    return [...strikes].sort((a, b) => Number(a) - Number(b))
  }, [strikesQuery.data?.strikes])


  useEffect(() => {
    const strikes = strikesQuery.data?.strikes ?? []


    if (!strikes.length) {
      return
    }


    if (strikes.includes(prefs.selected_strike)) {
      return
    }


    const fallbackStrike =
      strikesQuery.data?.recommended_strike
      ?? strikes[0]
      ?? defaultPreferences.selected_strike


    setPrefs((old) => ({
      ...old,
      selected_strike: fallbackStrike,
    }))
  }, [
    strikesQuery.data,
    prefs.selected_strike,
    setPrefs,
  ])


  const spotQuery = useQuery({
    queryKey: ['spot', prefs.selected_asset],
    enabled: !!prefs.selected_asset,
    queryFn: async () =>
      (
        await api.get<SpotResponse>(
          `/assets/${prefs.selected_asset}/spot`,
        )
      ).data,
  })


  const optionTypeParam = (
    `${prefs.show_calls ? 'CALL,' : ''}${
      prefs.show_puts ? 'PUT' : ''
    }`
  ).replace(/,$/, '') || 'CALL,PUT'


  const byStrikeQuery = useQuery({
    queryKey: [
      'by-strike',
      prefs.selected_asset,
      prefs.selected_strike,
      prefs.expiration_count,
      optionTypeParam,
    ],
    enabled: !!prefs.selected_asset && !!prefs.selected_strike,
    queryFn: async () =>
      (
        await api.get<ByStrikeResponse>('/options/by-strike', {
          params: {
            asset: prefs.selected_asset,
            strike: prefs.selected_strike,
            expiration_count: prefs.expiration_count,
            types: optionTypeParam,
          },
        })
      ).data,
  })


  const settingsQuery = useQuery({
    queryKey: ['admin-settings', user?.role],
    enabled: user?.role === 'admin',
    queryFn: async () =>
      (await api.get<SystemSetting[]>('/admin/settings')).data,
  })


  const quoteSymbols = useMemo(
    () =>
      (byStrikeQuery.data?.items ?? [])
        .map((item) => item.option_symbol)
        .filter((symbol): symbol is string => !!symbol),
    [byStrikeQuery.data],
  )


  const quotesQuery = useQuery({
    queryKey: [
      'latest-quotes',
      prefs.selected_asset,
      quoteSymbols,
    ],
    enabled: quoteSymbols.length > 0,
    queryFn: async () => {
      const rows = await Promise.all(
        quoteSymbols.map(async (symbol) => {
          const { data } = await api.get<QuoteLatestResponse>(
            '/quotes/latest',
            {
              params: {
                asset: prefs.selected_asset,
                option_symbol: symbol,
              },
            },
          )


          return [symbol, data] as const
        }),
      )


      return Object.fromEntries(rows)
    },
  })


  useEffect(() => {
    if (!prefs.auto_refresh) {
      return
    }


    const timer = window.setInterval(() => {
      queryClient.invalidateQueries({
        queryKey: ['spot', prefs.selected_asset],
      })


      queryClient.invalidateQueries({
        queryKey: ['latest-quotes', prefs.selected_asset],
      })


      queryClient.invalidateQueries({
        queryKey: ['strikes', prefs.selected_asset],
      })
    }, prefs.refresh_interval * 1000)


    return () => window.clearInterval(timer)
  }, [
    prefs.auto_refresh,
    prefs.refresh_interval,
    prefs.selected_asset,
    queryClient,
  ])


  useEffect(() => {
    if (!token) {
      return
    }


    const ws = new MarketWsClient({
      token,
      onStatus: setWsStatus,
      onMessage: (event) => {
        if (event.type === 'snapshot' && Array.isArray(event.data)) {
          const map: Record<string, QuoteLatestResponse> = {}


          event.data.forEach((item: any) => {
            if (!item.option_symbol) {
              return
            }


            map[item.option_symbol] = {
              asset: item.asset,
              option_symbol: item.option_symbol,
              last_price: item.last_price?.toString(),
              bid: item.bid?.toString(),
              ask: item.ask?.toString(),
              premium: item.premium?.toString(),
              quote_timestamp: item.quote_timestamp,
            }
          })


          setWsQuoteMap((old) => ({
            ...old,
            ...map,
          }))
        }


        if (
          event.type === 'quote'
          && event.data
          && !Array.isArray(event.data)
        ) {
          const data: any = event.data


          if (!data.option_symbol) {
            return
          }


          setWsQuoteMap((old) => ({
            ...old,
            [data.option_symbol]: {
              asset: data.asset,
              option_symbol: data.option_symbol,
              last_price: data.last_price?.toString(),
              bid: data.bid?.toString(),
              ask: data.ask?.toString(),
              premium: data.premium?.toString(),
              quote_timestamp: data.quote_timestamp,
            },
          }))
        }
      },
    })


    ws.connect()


    return () => ws.stop()
  }, [token])


  const quoteMap = useMemo(
    () => ({
      ...(quotesQuery.data ?? {}),
      ...wsQuoteMap,
    }),
    [quotesQuery.data, wsQuoteMap],
  )


  const rows = useMemo<OptionRow[]>(() => {
    return (byStrikeQuery.data?.items ?? []).map((item) => ({
      expiration_date: item.expiration_date,
      option_symbol: item.option_symbol,
      matched_strike: item.matched_strike,
      requested_strike: item.requested_strike,
      side: item.option_type,
      quote: item.option_symbol
        ? quoteMap[item.option_symbol]
        : undefined,
    }))
  }, [byStrikeQuery.data, quoteMap])


  const callRows = rows.filter((row) => row.side === 'CALL')
  const putRows = rows.filter((row) => row.side === 'PUT')


  const simulationMode = useMemo(() => {
    const setting = settingsQuery.data?.find(
      (item) => item.key === 'simulation_mode',
    )


    return Boolean(setting?.value?.value)
  }, [settingsQuery.data])


  const chartData = useMemo(() => {
    const byExpiration: Record<string, any> = {}


    const assetRoot = prefs.selected_asset.replace(/[0-9]+$/, '')


    const getShortSymbol = (symbol?: string | null) => {
      if (!symbol) {
        return null
      }


      if (symbol.startsWith(assetRoot)) {
        return symbol.slice(assetRoot.length)
      }


      return symbol
    }


    rows.forEach((row) => {
      const key = fmtDateMonth(row.expiration_date)


      byExpiration[key] ??= {
        vencimento: key,
      }


      const premium = row.quote?.premium ?? row.quote?.last_price


      if (row.side === 'CALL') {
        byExpiration[key].call = hasPositiveQuoteValue(premium)
          ? Number(premium)
          : null


        byExpiration[key].call_symbol = row.option_symbol
        byExpiration[key].call_symbol_short = getShortSymbol(
          row.option_symbol,
        )


        byExpiration[key].call_bid = hasPositiveQuoteValue(
          row.quote?.bid,
        )
          ? Number(row.quote?.bid)
          : null


        byExpiration[key].call_ask = hasPositiveQuoteValue(
          row.quote?.ask,
        )
          ? Number(row.quote?.ask)
          : null
      } else {
        byExpiration[key].put = hasPositiveQuoteValue(premium)
          ? Number(premium)
          : null


        byExpiration[key].put_symbol = row.option_symbol
        byExpiration[key].put_symbol_short = getShortSymbol(
          row.option_symbol,
        )


        byExpiration[key].put_bid = hasPositiveQuoteValue(
          row.quote?.bid,
        )
          ? Number(row.quote?.bid)
          : null


        byExpiration[key].put_ask = hasPositiveQuoteValue(
          row.quote?.ask,
        )
          ? Number(row.quote?.ask)
          : null
      }
    })


    return Object.values(byExpiration)
  }, [rows, prefs.selected_asset])


  const toggleSymbol = (symbol: string) => {
    setSelectedSymbols((old) => {
      if (old.includes(symbol)) {
        return old.filter((item) => item !== symbol)
      }


      return [...old, symbol]
    })
  }


  const statusColor =
    wsStatus === 'connected'
      ? 'green'
      : wsStatus === 'connecting'
        ? 'yellow'
        : 'red'


  return (
    <div className="space-y-4">
      <section className="panel flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge color={spotQuery.isError ? 'red' : 'green'}>
            Servidor {spotQuery.isError ? 'offline' : 'online'}
          </Badge>


          <Badge color={statusColor}>
            WS {wsStatus}
          </Badge>


          <Badge
            color={spotQuery.data?.spot_price ? 'green' : 'yellow'}
          >
            {spotQuery.data?.spot_price
              ? 'Profit/RTD com dados'
              : 'Aguardando dados do Profit…'}
          </Badge>


          {simulationMode && (
            <Badge color="blue">
              Dados simulados de teste
            </Badge>
          )}


          <span>
            Última atualização global:{' '}
            {fmtTime(spotQuery.data?.quote_timestamp)}
          </span>
        </div>


        <div className="flex flex-wrap gap-2">
          <button
            className="btn-secondary"
            onClick={() => queryClient.invalidateQueries()}
          >
            Atualizar
          </button>


          <button
            className="btn-secondary"
            onClick={() => setShowSettings((value) => !value)}
          >
            Configurações
          </button>
        </div>
      </section>


      {showSettings && (
        <section className="panel grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="field">
            <span>Tema</span>


            <select
              className="input"
              value={prefs.theme}
              onChange={(event) =>
                setPrefs((old) => ({
                  ...old,
                  theme: event.target.value as 'light' | 'dark',
                }))
              }
            >
              <option value="dark">Escuro</option>
              <option value="light">Claro</option>
            </select>
          </label>


          <label className="field">
            <span>Vencimentos</span>


            <input
              className="input"
              type="number"
              min={1}
              max={12}
              value={prefs.expiration_count}
              onChange={(event) =>
                setPrefs((old) => ({
                  ...old,
                  expiration_count: Number(event.target.value),
                }))
              }
            />
          </label>


          <label className="field">
            <span>Tolerância atual</span>
            <input
              className="input"
              value="Definida pelo backend"
              disabled
            />
          </label>


          <label className="field">
            <span>Atualização automática</span>


            <select
              className="input"
              value={prefs.auto_refresh ? 'on' : 'off'}
              onChange={(event) =>
                setPrefs((old) => ({
                  ...old,
                  auto_refresh: event.target.value === 'on',
                }))
              }
            >
              <option value="on">Ligada</option>
              <option value="off">Desligada</option>
            </select>
          </label>
        </section>
      )}


      <section className="panel grid grid-cols-1 gap-3 lg:grid-cols-6">
        <label className="field lg:col-span-1">
          <span>Ativo</span>


          <select
            className="input"
            value={prefs.selected_asset}
            onChange={(event) =>
              setPrefs((old) => ({
                ...old,
                selected_asset: event.target.value,
              }))
            }
          >
            {assetsQuery.data?.map((asset) => (
              <option key={asset.id} value={asset.symbol}>
                {asset.symbol}
              </option>
            ))}
          </select>
        </label>


        <label className="field lg:col-span-2">
          <span>Strike</span>


          <select
            className="input"
            value={prefs.selected_strike}
            onChange={(event) =>
              setPrefs((old) => ({
                ...old,
                selected_strike: event.target.value,
              }))
            }
          >
            {sortedStrikes.map((strike) => (
              <option key={strike} value={strike}>
                {formatStrike(strike, prefs.selected_asset)}
              </option>
            ))}
          </select>
        </label>


        <label className="field lg:col-span-1">
          <span>Qtd. vencimentos</span>


          <input
            className="input"
            type="number"
            min={1}
            max={12}
            value={prefs.expiration_count}
            onChange={(event) =>
              setPrefs((old) => ({
                ...old,
                expiration_count: Number(event.target.value),
              }))
            }
          />
        </label>


        <label className="field lg:col-span-1">
          <span>Lados</span>


          <select
            className="input"
            value={`${prefs.show_calls ? '1' : '0'}${
              prefs.show_puts ? '1' : '0'
            }`}
            onChange={(event) => {
              const value = event.target.value


              setPrefs((old) => ({
                ...old,
                show_calls: value[0] === '1',
                show_puts: value[1] === '1',
              }))
            }}
          >
            <option value="11">CALL + PUT</option>
            <option value="10">Somente CALL</option>
            <option value="01">Somente PUT</option>
          </select>
        </label>


        <label className="field lg:col-span-1">
          <span>Intervalo refresh (s)</span>


          <input
            className="input"
            type="number"
            min={1}
            max={60}
            value={prefs.refresh_interval}
            onChange={(event) =>
              setPrefs((old) => ({
                ...old,
                refresh_interval: Number(event.target.value),
              }))
            }
          />
        </label>
      </section>


      <section className="panel grid grid-cols-1 gap-2 text-sm md:grid-cols-2 lg:grid-cols-4">
        <div>
          <h4 className="font-semibold">Ativo</h4>
          <p>{prefs.selected_asset}</p>
        </div>


        <div>
          <h4 className="font-semibold">Último preço</h4>
          <p>{fmtNumber(spotQuery.data?.spot_price)}</p>
        </div>


        <div>
          <h4 className="font-semibold">Horário da atualização</h4>
          <p>{fmtTime(spotQuery.data?.quote_timestamp)}</p>
        </div>


        <div>
          <h4 className="font-semibold">Faixa de strikes</h4>
          <p>
            {formatStrike(strikesQuery.data?.range_low, prefs.selected_asset)}
            {' – '}
            {formatStrike(strikesQuery.data?.range_high, prefs.selected_asset)}
          </p>
        </div>


        {strikesQuery.data?.warning && (
          <p className="text-amber-500 md:col-span-2 lg:col-span-4">
            {strikesQuery.data.warning}
          </p>
        )}
      </section>


      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {prefs.show_calls && (
          <OptionTable
            title="CALL"
            rows={callRows}
            requestedStrike={prefs.selected_strike}
            assetSymbol={prefs.selected_asset}
            selectedSymbols={selectedSymbols}
            onToggleSymbol={toggleSymbol}
          />
        )}


        {prefs.show_puts && (
          <OptionTable
            title="PUT"
            rows={putRows}
            requestedStrike={prefs.selected_strike}
            assetSymbol={prefs.selected_asset}
            selectedSymbols={selectedSymbols}
            onToggleSymbol={toggleSymbol}
          />
        )}
      </section>


      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {prefs.show_calls && (
          <PremiumChart
            data={chartData}
            side="CALL"
            selectedSymbols={selectedSymbols}
          />
        )}


        {prefs.show_puts && (
          <PremiumChart
            data={chartData}
            side="PUT"
            selectedSymbols={selectedSymbols}
          />
        )}
      </section>
    </div>
  )
}




function OptionTable({
  title,
  rows,
  requestedStrike,
  assetSymbol,
  selectedSymbols,
  onToggleSymbol,
}: {
  title: Side
  rows: OptionRow[]
  requestedStrike: string
  assetSymbol: string
  selectedSymbols: string[]
  onToggleSymbol: (symbol: string) => void
}) {
  return (
    <div className="panel overflow-auto">
      <h3
        className={`mb-3 text-sm font-semibold ${
          title === 'CALL'
            ? 'text-sky-500'
            : 'text-orange-400'
        }`}
      >
        {title}
      </h3>


      <table className="table text-sm">
        <thead>
          <tr>
            <th className="w-10"></th>
            <th>Venc.</th>
            <th>Código</th>
            <th>Strike usado</th>
            <th>BID</th>
            <th>ASK</th>
            <th>Último</th>
            <th>Atualização</th>
          </tr>
        </thead>


        <tbody>
          {rows.map((row, index) => {
            const noData = (
              !row.option_symbol
              || row.quote?.message === 'N/D'
            )


            const usedStrike = (
              row.matched_strike
              ?? row.requested_strike
            )


            const adjustedStrike = (
              !!row.matched_strike
              && row.matched_strike !== requestedStrike
            )


            const isSelected = (
              !!row.option_symbol
              && selectedSymbols.includes(row.option_symbol)
            )


            return (
              <tr
                key={
                  `${title}-${row.expiration_date}-`
                  + `${row.option_symbol ?? 'na'}`
                }
                className={
                  isSelected
                    ? 'bg-green-100 dark:bg-green-900/40'
                    : index % 2 === 1
                      ? 'bg-slate-50 dark:bg-slate-800/40'
                      : ''
                }
              >
                <td>
                  {row.option_symbol && (
                    <input
                      type="checkbox"
                      className="cursor-pointer accent-green-600"
                      checked={isSelected}
                      onChange={() =>
                        onToggleSymbol(row.option_symbol!)
                      }
                    />
                  )}
                </td>


                <td>{fmtDateMonth(row.expiration_date)}</td>


                <td>
                  {row.option_symbol ?? '— sem opção —'}
                </td>


                <td
                  title={
                    adjustedStrike
                      ? (
                          `Strike solicitado: ${
                            formatStrike(
                              requestedStrike,
                              assetSymbol,
                            )
                          }; `
                          + `strike encontrado: ${
                            formatStrike(
                              row.matched_strike,
                              assetSymbol,
                            )
                          }`
                        )
                      : `Strike solicitado: ${
                          formatStrike(
                            requestedStrike,
                            assetSymbol,
                          )
                        }`
                  }
                >
                  {formatStrike(usedStrike, assetSymbol)}
                  {adjustedStrike && (
                    <span className="text-amber-500"> ★</span>
                  )}
                </td>


                <td>
                  {noData
                    ? 'N/D'
                    : formatBookValue(row.quote?.bid)}
                </td>


                <td>
                  {noData
                    ? 'N/D'
                    : formatBookValue(row.quote?.ask)}
                </td>


                <td>
                  {noData
                    ? 'N/D'
                    : formatBookValue(row.quote?.last_price)}
                </td>


                <td>{fmtTime(row.quote?.quote_timestamp)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}