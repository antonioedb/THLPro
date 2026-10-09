import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface Item {
  vencimento: string
  call?: number | null
  put?: number | null
}

export function PremiumChart({ data }: { data: Item[] }) {
  return (
    <div className="panel h-72">
      <h3 className="mb-3 text-sm font-semibold">Prêmio por vencimento</h3>
      <ResponsiveContainer>
        <LineChart data={data}>
          <XAxis dataKey="vencimento" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" />
          <Tooltip />
          <Line type="monotone" dataKey="call" stroke="#0ea5e9" name="CALL" strokeWidth={2} />
          <Line type="monotone" dataKey="put" stroke="#f97316" name="PUT" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
