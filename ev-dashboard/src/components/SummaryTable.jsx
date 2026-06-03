import { useState, useMemo } from 'react'
import { useChartData } from '../hooks/useEVData'

const COLS = [
  { key: 'month', label: 'Period' },
  { key: 'make', label: 'Make' },
  { key: 'model', label: 'Model' },
  { key: 'count', label: 'Count', numeric: true },
]

function SortIcon({ dir }) {
  if (!dir) return <span className="text-slate-300 dark:text-slate-600 ml-1">↕</span>
  return <span className="text-blue-500 ml-1">{dir === 'asc' ? '↑' : '↓'}</span>
}

function SkeletonRows() {
  return Array.from({ length: 8 }, (_, i) => (
    <tr key={i}>
      {COLS.map(col => (
        <td key={col.key} className="px-4 py-2.5">
          <div className="h-4 bg-slate-100 dark:bg-slate-800 rounded animate-pulse" style={{ width: col.numeric ? '40%' : '70%' }} />
        </td>
      ))}
    </tr>
  ))
}

export default function SummaryTable({ filters }) {
  const [sortKey, setSortKey] = useState('count')
  const [sortDir, setSortDir] = useState('desc')
  const { data, isLoading } = useChartData(filters)

  const loading = isLoading && !data

  // data.filtered is the date-filtered raw records array (one row per incentive).
  // Aggregate them into month+make+model groups for the table.
  const rows = useMemo(() => {
    if (!data?.filtered) return []
    const tally = {}
    data.filtered.forEach(r => {
      const key = `${r['Month and Year']}||${r['Vehicle Make']}||${r['Vehicle Model']}`
      if (!tally[key]) tally[key] = { month: r['Month and Year'] ?? '', make: r['Vehicle Make'] ?? '', model: r['Vehicle Model'] ?? '', count: 0 }
      tally[key].count++
    })
    return Object.values(tally)
  }, [data])

  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      const cmp = typeof av === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv))
      return sortDir === 'asc' ? cmp : -cmp
    })
    return copy
  }, [rows, sortKey, sortDir])

  const total = useMemo(() => rows.reduce((s, r) => s + r.count, 0), [rows])

  function handleSort(key) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir(key === 'count' ? 'desc' : 'asc')
    }
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800">
        <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
          Detail Table
        </h3>
        {!loading && (
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
            {rows.length.toLocaleString()} rows · {total.toLocaleString()} total incentives
          </p>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50">
              {COLS.map(col => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className={`px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide cursor-pointer select-none hover:text-slate-700 dark:hover:text-slate-200 transition-colors ${col.numeric ? 'text-right' : ''}`}
                >
                  <span className={col.numeric ? 'flex justify-end items-center' : 'flex items-center'}>
                    {col.label}
                    <SortIcon dir={sortKey === col.key ? sortDir : null} />
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50 dark:divide-slate-800">
            {loading ? (
              <SkeletonRows />
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center text-slate-400 dark:text-slate-600">
                  No data for selected filters
                </td>
              </tr>
            ) : (
              <>
                {sorted.map((row, i) => (
                  <tr
                    key={i}
                    className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400 font-mono text-xs">{row.month}</td>
                    <td className="px-4 py-2.5 text-slate-800 dark:text-slate-200 font-medium">{row.make}</td>
                    <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400">{row.model}</td>
                    <td className="px-4 py-2.5 text-right font-mono font-semibold text-slate-800 dark:text-slate-100">
                      {row.count.toLocaleString()}
                    </td>
                  </tr>
                ))}
                <tr className="bg-slate-50 dark:bg-slate-800/50 border-t-2 border-slate-200 dark:border-slate-700 font-semibold">
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400" colSpan={3}>Total</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-800 dark:text-slate-100">
                    {total.toLocaleString()}
                  </td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
