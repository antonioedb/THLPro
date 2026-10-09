import { LineSeries, createChart, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts'
import { useEffect, useRef } from 'react'

interface Point { time: UTCTimestamp; value: number }

export function LiveWsChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, {
      layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
      width: ref.current.clientWidth,
      height: 260,
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    })
    const series = chart.addSeries(LineSeries, { color: '#0ea5e9', lineWidth: 2 })
    seriesRef.current = series
    const resize = () => chart.applyOptions({ width: ref.current?.clientWidth ?? 600 })
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.remove()
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current) return
    seriesRef.current.setData(points)
  }, [points])

  return (
    <div className="panel">
      <h3 className="mb-3 text-sm font-semibold">Fluxo em tempo real (WebSocket)</h3>
      <div ref={ref} />
    </div>
  )
}
