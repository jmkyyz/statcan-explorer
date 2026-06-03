import { useState, useCallback, useEffect } from 'react'
import { subMonths, format } from 'date-fns'

function defaultStartMonth() {
  return format(subMonths(new Date(), 12), 'yyyy-MM')
}

function defaultEndMonth() {
  return format(new Date(), 'yyyy-MM')
}

function readFiltersFromURL() {
  const p = new URLSearchParams(window.location.search)
  return {
    startMonth: p.get('startMonth') ?? defaultStartMonth(),
    endMonth: p.get('endMonth') ?? defaultEndMonth(),
    make: p.get('make') ?? '',
    model: p.get('model') ?? '',
    vehicleYear: p.get('vehicleYear') ?? '',
    province: p.get('province') ?? '',
    evTypes: (p.get('evTypes') ?? 'BEV,PHEV,FCEV').split(',').filter(Boolean),
  }
}

export function useFilterState() {
  const [filters, setFiltersState] = useState(readFiltersFromURL)

  useEffect(() => {
    const handler = () => setFiltersState(readFiltersFromURL())
    window.addEventListener('filterchange', handler)
    return () => window.removeEventListener('filterchange', handler)
  }, [])

  const setFilters = useCallback((updates) => {
    const next = new URLSearchParams(window.location.search)
    const currentMake = new URLSearchParams(window.location.search).get('make') ?? ''

    for (const [key, value] of Object.entries(updates)) {
      if (value === '' || value === null || value === undefined) {
        next.delete(key)
      } else if (Array.isArray(value)) {
        next.set(key, value.join(','))
      } else {
        next.set(key, String(value))
      }
    }

    // Cascading: clear model when make changes
    if ('make' in updates && updates.make !== currentMake) {
      next.delete('model')
    }

    const search = next.toString()
    window.history.replaceState(null, '', search ? `?${search}` : window.location.pathname)
    window.dispatchEvent(new Event('filterchange'))
  }, [])

  return { filters, setFilters }
}
