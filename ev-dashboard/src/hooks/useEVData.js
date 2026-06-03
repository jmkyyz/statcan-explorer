import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { parse, isAfter, isBefore } from 'date-fns'
import {
  fetchResourceMeta, fetchLatestMonthYear,
  fetchDistinct, fetchDistinctModels,
  fetchAllRecords, fetchEVTypeCounts,
} from '../lib/api'

// "Apr, 26" → Date
function parseMonthYear(str) {
  if (!str) return null
  try { return parse(str.trim(), 'MMM, yy', new Date()) } catch { return null }
}

// "yyyy-MM" → Date
function parseFilterMonth(str) {
  if (!str) return null
  try { return parse(str, 'yyyy-MM', new Date()) } catch { return null }
}

function filtersKey(f) { return JSON.stringify(f) }

// Cache key excludes date range — date filtering is client-side, no re-fetch needed
function apiFiltersKey(f) {
  return JSON.stringify({ make: f.make, model: f.model, vehicleYear: f.vehicleYear, province: f.province, evTypes: f.evTypes })
}

export function useFreshness() {
  const meta = useQuery({ queryKey: ['resource-meta'], queryFn: fetchResourceMeta, staleTime: 3_600_000, retry: 1 })
  const latest = useQuery({ queryKey: ['latest-month-year'], queryFn: fetchLatestMonthYear, staleTime: 3_600_000, retry: 1 })
  return {
    meta: meta.data, latestMonthYear: latest.data,
    isLoading: meta.isLoading || latest.isLoading,
    metaError: meta.error?.message ?? null,
    latestError: latest.error?.message ?? null,
  }
}

export function useMakes() {
  return useQuery({ queryKey: ['makes'], queryFn: () => fetchDistinct('Vehicle Make'), staleTime: 3_600_000 })
}

export function useModels(make) {
  return useQuery({ queryKey: ['models', make], queryFn: () => fetchDistinctModels(make), enabled: !!make, staleTime: 3_600_000 })
}

export function useVehicleYears() {
  return useQuery({ queryKey: ['vehicle-years'], queryFn: () => fetchDistinct('Vehicle Year'), staleTime: 3_600_000 })
}

export function useProvinces() {
  return useQuery({ queryKey: ['provinces'], queryFn: () => fetchDistinct('Dealership Province/Territory'), staleTime: 3_600_000 })
}

// Single source of truth: all records matching the API-level filters (make/model/year/province/evType).
// Date range is applied client-side — changes don't trigger a re-fetch.
function useRecords(filters) {
  return useQuery({
    queryKey: ['records', apiFiltersKey(filters)],
    queryFn: () => fetchAllRecords(filters),
    staleTime: 3_600_000,
    gcTime: 7_200_000,
    placeholderData: (prev) => prev,
  })
}

// EV type breakdown counts (BEV/PHEV/FCEV) via separate limit=0 requests
export function useEVTypeCounts(filters) {
  return useQuery({
    queryKey: ['ev-type-counts', apiFiltersKey(filters)],
    queryFn: () => fetchEVTypeCounts(filters),
    staleTime: 3_600_000,
    placeholderData: (prev) => prev,
  })
}

// Derived chart data: filter by date range client-side, then group and aggregate
export function useChartData(filters) {
  const { data: rawRecords, isLoading, isFetching, isError, error } = useRecords(filters)

  const data = useMemo(() => {
    if (!rawRecords) return null

    const startDate = parseFilterMonth(filters.startMonth)
    const endDate   = parseFilterMonth(filters.endMonth)

    // 1. Date-range filter (client-side)
    const filtered = rawRecords.filter(r => {
      const d = parseMonthYear(r['Month and Year'])
      if (!d) return true
      if (startDate && isBefore(d, startDate)) return false
      if (endDate   && isAfter(d, endDate))    return false
      return true
    })

    // 2. Sorted unique months (chronological)
    const monthSet = new Set(filtered.map(r => r['Month and Year']))
    const months = Array.from(monthSet).sort((a, b) => {
      const da = parseMonthYear(a), db = parseMonthYear(b)
      return da && db ? da - db : 0
    })

    // 3. Group by make or model
    const groupKey = filters.make ? 'Vehicle Model' : 'Vehicle Make'
    const tally = {}, grandTotal = {}
    filtered.forEach(r => {
      const grp = r[groupKey] || 'Unknown'
      const mo  = r['Month and Year']
      if (!tally[grp]) tally[grp] = {}
      tally[grp][mo] = (tally[grp][mo] || 0) + 1
      grandTotal[grp] = (grandTotal[grp] || 0) + 1
    })

    // 4. Top 5 + Other (when no make filter)
    let keys
    if (filters.make) {
      keys = Object.keys(grandTotal).sort((a, b) => grandTotal[b] - grandTotal[a])
    } else {
      const sorted = Object.keys(grandTotal).sort((a, b) => grandTotal[b] - grandTotal[a])
      const top5 = sorted.slice(0, 5), rest = sorted.slice(5)
      keys = rest.length ? [...top5, 'Other'] : top5
      if (rest.length) {
        tally['Other'] = {}
        rest.forEach(g => months.forEach(mo => {
          tally['Other'][mo] = (tally['Other'][mo] || 0) + (tally[g]?.[mo] || 0)
        }))
      }
    }

    // 5. Recharts rows
    const chartRows = months.map(mo => {
      const row = { month: mo }
      keys.forEach(k => { row[k] = tally[k]?.[mo] || 0 })
      return row
    })

    return { chartRows, keys, months, filtered, groupKey }
  }, [rawRecords, filters])

  return { data, isLoading, isFetching, isError, error }
}

// Derived stats from the same records cache
export function useStatsData(filters) {
  const { data: rawRecords, isLoading, isFetching, isError, error } = useRecords(filters)
  const evCounts = useEVTypeCounts(filters)

  const stats = useMemo(() => {
    if (!rawRecords) return null

    const startDate = parseFilterMonth(filters.startMonth)
    const endDate   = parseFilterMonth(filters.endMonth)

    const filtered = rawRecords.filter(r => {
      const d = parseMonthYear(r['Month and Year'])
      if (!d) return true
      if (startDate && isBefore(d, startDate)) return false
      if (endDate   && isAfter(d, endDate))    return false
      return true
    })

    const makeCounts = {}, modelCounts = {}
    filtered.forEach(r => {
      const make  = r['Vehicle Make']  || ''
      const model = r['Vehicle Model'] || ''
      makeCounts[make]   = (makeCounts[make]   || 0) + 1
      modelCounts[model] = (modelCounts[model] || 0) + 1
    })

    return {
      total:    filtered.length,
      topMake:  Object.entries(makeCounts) .sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—',
      topModel: Object.entries(modelCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—',
    }
  }, [rawRecords, filters])

  return {
    data: stats ? { ...stats, evTypeCounts: evCounts.data } : null,
    isLoading: isLoading || evCounts.isLoading,
    isFetching: isFetching || evCounts.isFetching,
    isError,
    error,
  }
}
