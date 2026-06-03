import { useEffect, useState } from 'react'
import { useFilterState } from './hooks/useFilterState'
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

export default function App() {
  const { filters, setFilters } = useFilterState()
  const debouncedFilters = useDebounced(filters, 300)

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
