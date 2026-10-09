import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtDateMonth, fmtNumber, fmtTime, isStale } from '../lib/format'
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
import { BidAskChart } from '../components/charts/BidAskChart'
import { MarketWsClient } from '../lib/ws'
import { LiveWsChart } from '../components/charts/LiveWsChart'

type Side = 'CALL' | 'PUT'

interface OptionRow {
  expiration_date: string
  option_symbol: string | null
  matched_strike: string | null
  requested_strike: string
  side: Side
  quote?: QuoteLatestResponse
}

export default function MainPage() {
  const { user, token } = useAuth()
  const { prefs, setPrefs } = usePreferences()
  const queryClient = useQueryClient()
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected')
  const [wsQuoteMap, setWsQuoteMap] = useState<Record<string, QuoteLatestResponse>>({})
  const [wsLive, setWsLive] = useState<{ time: number; value: number }[]>([])
  const [showSettings, setShowSettings] = useState(false)

  const assetsQuery = useQuery({
    queryKey: ['assets'],
    queryFn: async () => (await api.get<Asset[]>('/assets', { params: { enabled: true } })).data,
  })

  useEffect(() => {
    if (!assetsQuery.data?.length) return
    if (!assetsQuery.data.find((a) => a.symbol === prefs.selected_asset)) {
      setPrefs((old) => ({ ...old, selected_asset: assetsQuery.data?.[0].symbol ?? defaultPreferences.selected_asset }))
    }
  }, [assetsQuery.data, prefs.selected_asset, setPrefs])

  const strikesQuery = useQuery({
    queryKey: ['strikes', prefs.selected_asset],
    enabled: !!prefs.selected_asset,
    queryFn: async () => (await api.get<StrikeListResponse>(`/assets/${prefs.selected_asset}/strikes`)).data,
  })

  useEffect(() => {
    if (!strikesQuery.data?.strikes?.length) return
    if (!strikesQuery.data.strikes.includes(prefs.selected_strike)) {
      setPrefs((old) => ({ ...old, selected_strike: strikesQuery.data?.strikes?.[0] ?? old.selected_strike }))
    }
  }, [strikesQuery.data, prefs.selected_strike, setPrefs])

  const spotQuery = useQuery({
    queryKey: ['spot', prefs.selected_asset],
    enabled: !!prefs.selected_asset,
    queryFn: async () => (await api.get<SpotResponse>(`/assets/${prefs.selected_asset}/spot`)).data,
  })

  const optionTypeParam = `${prefs.show_calls ? 'CALL,' : ''}${prefs.show_puts ? 'PUT' : ''}`.replace(/,$/, '') || 'CALL,PUT'

  const byStrikeQuery = useQuery({
    queryKey: ['by-strike', prefs.selected_asset, prefs.selected_strike, prefs.expiration_count, optionTypeParam],
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
    queryFn: async () => (await api.get<SystemSetting[]>('/admin/settings')).data,
  })

  const quoteSymbols = useMemo(
    () =>
      (byStrikeQuery.data?.items ?? [])
        .map((x) => x.option_symbol)
        .filter((x): x is string => !!x),
    [byStrikeQuery.data],
  )

  const quotesQuery = useQuery({
    queryKey: ['latest-quotes', prefs.selected_asset, quoteSymbols],
    enabled: quoteSymbols.length > 0,
    queryFn: async () => {
      const rows = await Promise.all(
        quoteSymbols.map(async (symbol) => {
          const { data } = await api.get<QuoteLatestResponse>('/quotes/latest', { params: { asset: prefs.selected_asset, option_symbol: symbol } })
          return [symbol, data] as const
        }),
      )
      return Object.fromEntries(rows)
    },
  })

  useEffect(() => {
    if (prefs.auto_refresh) {
      const t = window.setInterval(() => {
        queryClient.invalidateQueries({ queryKey: ['spot', prefs.selected_asset] })
        queryClient.invalidateQueries({ queryKey: ['latest-quotes', prefs.selected_asset] })
      }, prefs.refresh_interval * 1000)
      return () => window.clearInterval(t)
    }
  }, [prefs.auto_refresh, prefs.refresh_interval, prefs.selected_asset, queryClient])

  useEffect(() => {
    if (!token) return
    const ws = new MarketWsClient({
      token,
      onStatus: setWsStatus,
      onMessage: (evt) => {
        if (evt.type === 'snapshot' && Array.isArray(evt.data)) {
          const map: Record<string, QuoteLatestResponse> = {}
          evt.data.forEach((item: any) => {
            if (item.option_symbol) {
              map[item.option_symbol] = {
                asset: item.asset,
                option_symbol: item.option_symbol,
                last_price: item.last_price?.toString(),
                bid: item.bid?.toString(),
                ask: item.ask?.toString(),
                quote_timestamp: item.quote_timestamp,
              }
            }
          })
          setWsQuoteMap((old) => ({ ...old, ...map }))
        }
        if (evt.type === 'quote' && evt.data && !Array.isArray(evt.data)) {
          const d: any = evt.data
          if (d.option_symbol) {
            setWsQuoteMap((old) => ({
              ...old,
              [d.option_symbol]: {
                asset: d.asset,
                option_symbol: d.option_symbol,
                last_price: d.last_price?.toString(),
                bid: d.bid?.toString(),
                ask: d.ask?.toString(),
                quote_timestamp: d.quote_timestamp,
              },
            }))
            if (d.last_price) {
              setWsLive((old) => {
                const n = [...old, { time: Math.floor(Date.now() / 1000), value: Number(d.last_price) }]
                return n.slice(-80)
              })
            }
          }
        }
      },
    })
    ws.connect()
    return () => ws.stop()
  }, [token])

  const quoteMap = useMemo(() => ({ ...(quotesQuery.data ?? {}), ...wsQuoteMap }), [quotesQuery.data, wsQuoteMap])

  const rows = useMemo<OptionRow[]>(() => {
    return (byStrikeQuery.data?.items ?? []).map((item) => ({
      expiration_date: item.expiration_date,
      option_symbol: item.option_symbol,
      matched_strike: item.matched_strike,
      requested_strike: item.requested_strike,
      side: item.option_type,
      quote: item.option_symbol ? quoteMap[item.option_symbol] : undefined,
    }))
  }, [byStrikeQuery.data, quoteMap])

  const callRows = rows.filter((r) => r.side === 'CALL')
  const putRows = rows.filter((r) => r.side === 'PUT')

  const maxAge = useMemo(() => {
    const setting = settingsQuery.data?.find((x) => x.key === 'data_max_age')
    return Number((setting?.value?.value as number | string) ?? 60)
  }, [settingsQuery.data])

  const simulationMode = useMemo(() => {
    const setting = settingsQuery.data?.find((x) => x.key === 'simulation_mode')
    return Boolean(setting?.value?.value)
  }, [settingsQuery.data])

  const chartData = useMemo(() => {
    const byExp: Record<string, any> = {}
    rows.forEach((row) => {
      const k = fmtDateMonth(row.expiration_date)
      byExp[k] ??= { vencimento: k }
      const p = row.quote?.premium ?? row.quote?.last_price
      if (row.side === 'CALL') {
        byExp[k].call = p ? Number(p) : null
        byExp[k].bid = row.quote?.bid ? Number(row.quote.bid) : null
        byExp[k].ask = row.quote?.ask ? Number(row.quote.ask) : null
        byExp[k].last = row.quote?.last_price ? Number(row.quote.last_price) : null
      } else {
        byExp[k].put = p ? Number(p) : null
      }
    })
    return Object.values(byExp)
  }, [rows])

  const statusColor = wsStatus === 'connected' ? 'green' : wsStatus === 'connecting' ? 'yellow' : 'red'

  return (
    <div className="space-y-4">
      <section className="panel flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge color={spotQuery.isError ? 'red' : 'green'}>Servidor {spotQuery.isError ? 'offline' : 'online'}</Badge>
          <Badge color={statusColor}>WS {wsStatus}</Badge>
          <Badge color={spotQuery.data?.spot_price ? 'green' : 'yellow'}>
            {spotQuery.data?.spot_price ? 'Profit/RTD com dados' : 'Aguardando dados do Profit…'}
          </Badge>
          {simulationMode && <Badge color="blue">Dados simulados de teste</Badge>}
          <span>Última atualização global: {fmtTime(spotQuery.data?.quote_timestamp)}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-secondary" onClick={() => queryClient.invalidateQueries()}>Atualizar</button>
          <button className="btn-secondary" onClick={() => setShowSettings((v) => !v)}>Configurações</button>
        </div>
      </section>

      {showSettings && (
        <section className="panel grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          <label className="field"><span>Tema</span>
            <select className="input" value={prefs.theme} onChange={(e) => setPrefs((old) => ({ ...old, theme: e.target.value as 'light' | 'dark' }))}>
              <option value="dark">Escuro</option><option value="light">Claro</option>
            </select>
          </label>
          <label className="field"><span>Vencimentos</span>
            <input className="input" type="number" min={1} max={12} value={prefs.expiration_count} onChange={(e) => setPrefs((old) => ({ ...old, expiration_count: Number(e.target.value) }))} />
          </label>
          <label className="field"><span>Tolerância atual</span>
            <input className="input" value="0,50 (backend)" disabled />
          </label>
          <label className="field"><span>Atualização automática</span>
            <select className="input" value={prefs.auto_refresh ? 'on' : 'off'} onChange={(e) => setPrefs((old) => ({ ...old, auto_refresh: e.target.value === 'on' }))}>
              <option value="on">Ligada</option><option value="off">Desligada</option>
            </select>
          </label>
        </section>
      )}

      <section className="panel grid grid-cols-1 gap-3 lg:grid-cols-6">
        <label className="field lg:col-span-1"><span>Ativo</span>
          <select className="input" value={prefs.selected_asset} onChange={(e) => setPrefs((old) => ({ ...old, selected_asset: e.target.value }))}>
            {assetsQuery.data?.map((a) => <option key={a.id} value={a.symbol}>{a.symbol}</option>)}
          </select>
        </label>
        <label className="field lg:col-span-2"><span>Strike (grade completa ±10%)</span>
          <select className="input" value={prefs.selected_strike} onChange={(e) => setPrefs((old) => ({ ...old, selected_strike: e.target.value }))}>
            {strikesQuery.data?.strikes?.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="field lg:col-span-1"><span>Qtd. vencimentos</span>
          <input className="input" type="number" min={1} max={12} value={prefs.expiration_count} onChange={(e) => setPrefs((old) => ({ ...old, expiration_count: Number(e.target.value) }))} />
        </label>
        <label className="field lg:col-span-1"><span>Lados</span>
          <select className="input" value={`${prefs.show_calls ? '1' : '0'}${prefs.show_puts ? '1' : '0'}`} onChange={(e) => {
            const v = e.target.value
            setPrefs((old) => ({ ...old, show_calls: v[0] === '1', show_puts: v[1] === '1' }))
          }}>
            <option value="11">CALL + PUT</option>
            <option value="10">Somente CALL</option>
            <option value="01">Somente PUT</option>
          </select>
        </label>
        <label className="field lg:col-span-1"><span>Intervalo refresh (s)</span>
          <input className="input" type="number" min={1} max={60} value={prefs.refresh_interval} onChange={(e) => setPrefs((old) => ({ ...old, refresh_interval: Number(e.target.value) }))} />
        </label>
      </section>

      <section className="panel grid grid-cols-1 gap-2 text-sm md:grid-cols-2 lg:grid-cols-4">
        <div><h4 className="font-semibold">Ativo</h4><p>{prefs.selected_asset}</p></div>
        <div><h4 className="font-semibold">Último preço</h4><p>{fmtNumber(spotQuery.data?.spot_price)}</p></div>
        <div><h4 className="font-semibold">Horário da atualização</h4><p>{fmtTime(spotQuery.data?.quote_timestamp)}</p></div>
        <div><h4 className="font-semibold">Faixa de strikes</h4><p>{fmtNumber(strikesQuery.data?.range_low)} – {fmtNumber(strikesQuery.data?.range_high)}</p></div>
        {strikesQuery.data?.warning && <p className="text-amber-500 md:col-span-2 lg:col-span-4">{strikesQuery.data.warning}</p>}
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {prefs.show_calls && <OptionTable title="CALL" rows={callRows} maxAge={maxAge} requestedStrike={prefs.selected_strike} />}
        {prefs.show_puts && <OptionTable title="PUT" rows={putRows} maxAge={maxAge} requestedStrike={prefs.selected_strike} />}
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <PremiumChart data={chartData} />
        <BidAskChart data={chartData} />
      </section>
      <LiveWsChart points={wsLive.map((x) => ({ time: x.time as any, value: x.value }))} />
    </div>
  )
}

function OptionTable({
  title,
  rows,
  maxAge,
  requestedStrike,
}: {
  title: Side
  rows: OptionRow[]
  maxAge: number
  requestedStrike: string
}) {
  return (
    <div className="panel overflow-auto">
      <h3 className={`mb-3 text-sm font-semibold ${title === 'CALL' ? 'text-sky-500' : 'text-orange-400'}`}>{title}</h3>
      <table className="table text-xs">
        <thead>
          <tr>
            <th>Venc.</th><th>Código</th><th>Strike</th><th>Prêmio</th><th>BID</th><th>ASK</th><th>Último</th><th>Atualização</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const stale = isStale(r.quote?.quote_timestamp, maxAge)
            const noData = !r.option_symbol || r.quote?.message === 'N/D'
            const strikeInfo = r.matched_strike && r.matched_strike !== requestedStrike
              ? `${r.matched_strike}★`
              : r.matched_strike ?? requestedStrike
            return (
              <tr key={`${title}-${r.expiration_date}-${r.option_symbol ?? 'na'}`} className={stale ? 'bg-amber-50 dark:bg-amber-950/30' : ''}>
                <td>{fmtDateMonth(r.expiration_date)}</td>
                <td>{r.option_symbol ?? '— sem opção —'}</td>
                <td title={r.matched_strike !== requestedStrike ? `Strike próximo ${r.matched_strike}` : ''}>{strikeInfo}</td>
                <td>{noData ? 'N/D' : fmtNumber(r.quote?.premium ?? r.quote?.last_price)}</td>
                <td>{noData ? 'N/D' : fmtNumber(r.quote?.bid)}</td>
                <td>{noData ? 'N/D' : fmtNumber(r.quote?.ask)}</td>
                <td>{noData ? 'N/D' : fmtNumber(r.quote?.last_price)}</td>
                <td>{fmtTime(r.quote?.quote_timestamp)} {stale && <span className="text-amber-500">(atrasado)</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
