import { useFreshness } from '../hooks/useEVData'
import { format, parseISO } from 'date-fns'

export default function FreshnessBanner() {
  const { meta, latestMonthYear, isLoading, metaError, latestError } = useFreshness()

  if (isLoading) {
    return (
      <div className="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-2 text-xs text-slate-500 dark:text-slate-400 text-center animate-pulse">
        Loading dataset info…
      </div>
    )
  }

  // Show API error prominently if freshness queries failed — helps diagnose connectivity issues
  if (metaError && latestError) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800 px-4 py-2 text-xs text-red-600 dark:text-red-400 text-center">
        <span className="font-semibold">API error:</span> {metaError} — check browser console for details
      </div>
    )
  }

  const lastModified = meta?.last_modified
    ? format(parseISO(meta.last_modified), 'MMM d, yyyy')
    : '—'

  return (
    <div className="bg-slate-100 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 px-4 py-2 text-xs text-slate-500 dark:text-slate-400 text-center">
      <span className="font-medium text-slate-700 dark:text-slate-300">
        Data current through:
      </span>{' '}
      {latestMonthYear ?? '—'}
      <span className="mx-3 text-slate-300 dark:text-slate-600">·</span>
      <span className="font-medium text-slate-700 dark:text-slate-300">
        Last updated:
      </span>{' '}
      {lastModified}
    </div>
  )
}
