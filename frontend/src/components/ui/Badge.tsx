interface Props {
  color?: 'green' | 'red' | 'yellow' | 'blue' | 'gray'
  children: React.ReactNode
}

const colorMap = {
  green: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
  red: 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300',
  yellow: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  blue: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300',
  gray: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
}

export function Badge({ color = 'gray', children }: Props) {
  return <span className={`rounded px-2 py-1 text-xs font-semibold ${colorMap[color]}`}>{children}</span>
}
