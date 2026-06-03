import { useMakes, useModels, useVehicleYears, useProvinces } from '../hooks/useEVData'

const EV_TYPES = ['BEV', 'PHEV', 'FCEV']

function Select({ label, value, onChange, options, placeholder = 'All', disabled }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
        {label}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-40"
      >
        <option value="">{placeholder}</option>
        {options?.map(opt => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    </div>
  )
}

function MonthInput({ label, value, onChange }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
        {label}
      </label>
      <input
        type="month"
        value={value}
        onChange={e => onChange(e.target.value)}
        className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  )
}

export default function FilterPanel({ filters, setFilters }) {
  const { data: makes } = useMakes()
  const { data: models } = useModels(filters.make)
  const { data: vehicleYears } = useVehicleYears()
  const { data: provinces } = useProvinces()

  function toggleEvType(type) {
    const current = filters.evTypes
    const next = current.includes(type)
      ? current.filter(t => t !== type)
      : [...current, type]
    // Don't allow deselecting all
    if (next.length === 0) return
    setFilters({ evTypes: next })
  }

  function resetAll() {
    window.history.replaceState(null, '', window.location.pathname)
    window.dispatchEvent(new Event('filterchange'))
  }

  return (
    <aside className="w-full lg:w-64 shrink-0 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-slate-700 dark:text-slate-200 uppercase tracking-widest">
          Filters
        </h2>
        <button
          onClick={resetAll}
          className="text-xs text-blue-500 hover:text-blue-700 dark:hover:text-blue-300 transition-colors"
        >
          Reset all
        </button>
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 p-4 flex flex-col gap-4">
        <MonthInput
          label="From"
          value={filters.startMonth}
          onChange={v => setFilters({ startMonth: v })}
        />
        <MonthInput
          label="To"
          value={filters.endMonth}
          onChange={v => setFilters({ endMonth: v })}
        />
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 p-4 flex flex-col gap-4">
        <Select
          label="Vehicle Make"
          value={filters.make}
          onChange={v => setFilters({ make: v })}
          options={makes}
        />
        <Select
          label="Vehicle Model"
          value={filters.model}
          onChange={v => setFilters({ model: v })}
          options={models}
          placeholder={filters.make ? 'All models' : 'Select a make first'}
          disabled={!filters.make}
        />
        <Select
          label="Vehicle Year"
          value={filters.vehicleYear}
          onChange={v => setFilters({ vehicleYear: v })}
          options={vehicleYears?.slice().reverse()}
        />
        <Select
          label="Province / Territory"
          value={filters.province}
          onChange={v => setFilters({ province: v })}
          options={provinces}
        />
      </div>

      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-3">
          EV Type
        </p>
        <div className="flex flex-col gap-2">
          {EV_TYPES.map(type => (
            <label key={type} className="flex items-center gap-3 cursor-pointer group">
              <input
                type="checkbox"
                checked={filters.evTypes.includes(type)}
                onChange={() => toggleEvType(type)}
                className="w-4 h-4 rounded accent-blue-500"
              />
              <span className="text-sm text-slate-700 dark:text-slate-300 group-hover:text-blue-500 transition-colors">
                {type === 'BEV' ? 'Battery EV (BEV)' : type === 'PHEV' ? 'Plug-in Hybrid (PHEV)' : 'Fuel Cell (FCEV)'}
              </span>
            </label>
          ))}
        </div>
      </div>
    </aside>
  )
}
