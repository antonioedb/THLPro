import dayjs from 'dayjs'


export const brNumber = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})


export function fmtNumber(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return 'N/D'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return 'N/D'
  return brNumber.format(n)
}


export function fmtPercent(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return 'N/D'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return 'N/D'
  return `${brNumber.format(n)}%`
}


export function fmtTime(v?: string | null): string {
  if (!v) return 'N/D'
  const d = dayjs(v)
  return d.isValid() ? d.format('HH:mm:ss') : 'N/D'
}


export function fmtDateMonth(v?: string | null): string {
  if (!v) return 'N/D'
  const d = dayjs(v)
  return d.isValid() ? d.format('MM/YY') : 'N/D'
}


export function fmtDateTime(v?: string | null): string {
  if (!v) return 'N/D'

  const d = dayjs(v)

  return d.isValid()
    ? d.format('DD/MM/YYYY HH:mm:ss')
    : 'N/D'
}


export function isStale(v?: string | null, maxAgeSeconds = 60): boolean {
  if (!v) return false
  const now = dayjs()
  return now.diff(dayjs(v), 'second') > maxAgeSeconds
}