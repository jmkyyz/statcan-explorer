import { useStatsData } from '../hooks/useEVData'

function Card({ label, value, sub, loading, error }) {
  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 p-5 flex flex-col gap-1">
      <p className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wide">{label}</p>
      {loading ? (
        <div className="h-8 bg-slate-100 dark:bg-slate-800 rounded animate-pulse w-3/4 mt-1" />
      ) : error ? (
        <p className="text-sm text-red-500 dark:text-red-400 break-all">{error}</p>
      ) : (
        <p className="text-2xl font-bold text-slate-800 dark:text-slate-100 tabular-nums">{value}</p>
      )}
      {sub && !loading && !error && (
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">{sub}</p>
      )}
    </div>
  )
}

export default function StatsCards({ filters }) {
  const { data, isLoading, isFetching, isError, error } = useStatsData(filters)
  const loading  = isLoading && !data
  const errorMsg = isError && !data ? (error?.message ?? 'Failed to load') : null

  const total    = data?.total    ?? 0
  const topMake  = data?.topMake  ?? '—'
  const topModel = data?.topModel ?? '—'

  const ev  = data?.evTypeCounts ?? {}
  const bev = ev.BEV  ?? 0
  const phev = ev.PHEV ?? 0
  const fcev = ev.FCEV ?? 0
  const evTotal = bev + phev + fcev
  const bevPct  = evTotal ? ((bev  / evTotal) * 100).toFixed(1) : '—'
  const phevPct = evTotal ? ((phev / evTotal) * 100).toFixed(1) : '—'

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Card
        label="Total Incentives"
        value={loading ? null : total.toLocaleString()}
        loading={loading}
        error={errorMsg}
        sub={isFetching && !loading && !errorMsg ? 'Refreshing…' : null}
      />
      <Card label="Top Make"  value={topMake}  loading={loading} />
      <Card label="Top Model" value={topModel} loading={loading} />
      <Card
        label="BEV vs PHEV"
        value={loading ? null : `${bevPct}% / ${phevPct}%`}
        sub={loading ? null : `${bev.toLocaleString()} BEV · ${phev.toLocaleString()} PHEV${fcev ? ` · ${fcev.toLocaleString()} FCEV` : ''}`}
        loading={loading}
      />
    </div>
  )
}
