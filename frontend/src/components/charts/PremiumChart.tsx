import {
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

interface Item {
  vencimento: string
  call?: number | null
  put?: number | null
  call_bid?: number | null
  call_ask?: number | null
  put_bid?: number | null
  put_ask?: number | null
  call_symbol?: string | null
  put_symbol?: string | null
  call_symbol_short?: string | null
  put_symbol_short?: string | null
}

interface PremiumChartProps {
  data: Item[]
  side: 'CALL' | 'PUT'
  selectedSymbols?: string[]
}

interface TooltipPayloadItem {
  payload: Item
}

function CustomTooltip({
  active,
  payload,
  side,
}: {
  active?: boolean
  payload?: TooltipPayloadItem[]
  side: 'CALL' | 'PUT'
}) {
  if (!active || !payload?.length) {
    return null
  }

  const item = payload[0].payload

  const premium = side === 'CALL' ? item.call : item.put
  const bid = side === 'CALL' ? item.call_bid : item.put_bid
  const ask = side === 'CALL' ? item.call_ask : item.put_ask
  const symbol =
    side === 'CALL' ? item.call_symbol_short : item.put_symbol_short

  const formatValue = (value?: number | null) =>
    typeof value === 'number' && Number.isFinite(value)
      ? value.toFixed(2).replace('.', ',')
      : 'N/D'

  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <div className="mb-1 font-semibold">
        {side} {symbol ? `— ${symbol}` : ''}
      </div>

      <div className="text-green-600 dark:text-green-400">
        ASK: {formatValue(ask)}
      </div>

      <div className="font-semibold">
        Prêmio: {formatValue(premium)}
      </div>

      <div className="text-red-600 dark:text-red-400">
        BID: {formatValue(bid)}
      </div>
    </div>
  )
}

export function PremiumChart({
  data,
  side,
  selectedSymbols = [],
}: PremiumChartProps) {
  const dataKey = side === 'CALL' ? 'call' : 'put'
  const symbolKey =
    side === 'CALL' ? 'call_symbol_short' : 'put_symbol_short'
  const fullSymbolKey =
    side === 'CALL' ? 'call_symbol' : 'put_symbol'

  const color = side === 'CALL' ? '#0ea5e9' : '#f97316'

  const renderDot = (props: any) => {
    const { cx, cy, payload } = props

    const value = payload?.[dataKey]

    if (
      value === null ||
      value === undefined ||
      cx === undefined ||
      cy === undefined
    ) {
      return null
    }

    const symbol = payload?.[fullSymbolKey]
    const isSelected = !!symbol && selectedSymbols.includes(symbol)

    if (!isSelected) {
      return (
        <circle
          cx={cx}
          cy={cy}
          r={3}
          fill={color}
          stroke="none"
        />
      )
    }

    return (
      <g>
        <circle
          cx={cx}
          cy={cy}
          r={7}
          fill="rgba(34, 197, 94, 0.25)"
          stroke="#22c55e"
          strokeWidth={2}
        />

        <circle
          cx={cx}
          cy={cy}
          r={3}
          fill="#22c55e"
        />
      </g>
    )
  }

  return (
    <div className="panel h-96 overflow-hidden">
      <h3 className="mb-3 text-sm font-semibold">
        Prêmio por vencimento — {side}
      </h3>

      <ResponsiveContainer
        width="100%"
        height="100%"
        className="focus:outline-none"
        tabIndex={-1}
      >
        <LineChart
          data={data}
          margin={{
            top: 20,
            right: 45,
            bottom: 30,
            left: 30,
          }}
        >
          <XAxis
            dataKey="vencimento"
            stroke="#94a3b8"
            padding={{
              left: 60,
              right: 30,
            }}
            tickMargin={10}
          />

          <YAxis stroke="#94a3b8" width={50} />

          <Tooltip
            content={
              <CustomTooltip side={side} />
            }
          />

          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            name={side}
            strokeWidth={2}
            dot={renderDot}
            activeDot={false}
            connectNulls={false}
          >
            <LabelList
              dataKey={symbolKey}
              position="top"
              fontSize={13}
              fill={color}
            />
          </Line>
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}