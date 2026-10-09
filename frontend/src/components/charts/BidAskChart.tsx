import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface Item {
  vencimento: string
  bid?: number | null
  ask?: number | null
  last?: number | null
}

export function BidAskChart({ data }: { data: Item[] }) {
  return (
    <div className="panel h-72">
      <h3 className="mb-3 text-sm font-semibold">BID × ASK × Último</h3>
      <ResponsiveContainer>
        <BarChart data={data}>
          <XAxis dataKey="vencimento" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" />
          <Tooltip />
          <Bar dataKey="bid" fill="#22c55e" name="BID" />
          <Bar dataKey="ask" fill="#ef4444" name="ASK" />
          <Bar dataKey="last" fill="#a855f7" name="Último" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
