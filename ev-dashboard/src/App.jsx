import { useEffect, useState } from 'react'
import { useFilterState } from './hooks/useFilterState'
import { useFreshness } from './hooks/useEVData'
import FreshnessBanner from './components/FreshnessBanner'
import FilterPanel from './components/FilterPanel'
import StatsCards from './components/StatsCards'
import EVChart from './components/EVChart'
import SummaryTable from './components/SummaryTable'

function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

// "Apr, 26" → "2026-04"
function parseLatestToYYYYMM(str) {
  if (!str) return null
  const match = str.trim().match(/^([A-Za-z]+),?\s*(\d+)$/)
  if (!match) return null
  const yr = parseInt(match[2]) + (parseInt(match[2]) < 50 ? 2000 : 1900)
  const mo = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
    .indexOf(match[1].toLowerCase().slice(0, 3)) + 1
  if (mo === 0) return null
  return `${yr}-${String(mo).padStart(2, '0')}`
}

export default function App() {
  const { filters, setFilters } = useFilterState()
  const debouncedFilters = useDebounced(filters, 300)
  const { latestMonthYear } = useFreshness()

  // Auto-set endMonth to the API's latest available month, but only if the
  // user hasn't explicitly set it via the URL (i.e. it's not in the query string)
  useEffect(() => {
    const parsed = parseLatestToYYYYMM(latestMonthYear)
    if (!parsed) return
    const urlHasEndMonth = new URLSearchParams(window.location.search).has('endMonth')
    if (!urlHasEndMonth) setFilters({ endMonth: parsed })
  }, [latestMonthYear])

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="max-w-screen-xl mx-auto px-4 py-4 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center text-white font-bold text-sm shrink-0">
            EV
          </div>
          <div>
            <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 leading-tight">
              EV Affordability Dashboard
            </h1>
            <p className="text-xs text-slate-400 dark:text-slate-500">
              Canada's Electric Vehicle Affordability Program
            </p>
          </div>
        </div>
        <FreshnessBanner />
      </header>

      <div className="max-w-screen-xl mx-auto px-4 py-6">
        <div className="flex flex-col lg:flex-row gap-6">
          <FilterPanel filters={filters} setFilters={setFilters} />

          <main className="flex-1 min-w-0 flex flex-col gap-6">
            <StatsCards filters={debouncedFilters} />
            <EVChart filters={debouncedFilters} />
            <SummaryTable filters={debouncedFilters} />
          </main>
        </div>
      </div>
    </div>
  )
}
