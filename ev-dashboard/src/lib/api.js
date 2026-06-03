// All requests proxy through Vite at /ckan → https://open.canada.ca/data/en/api/3/action
// datastore_search_sql is disabled on this CKAN instance — we use datastore_search + client-side aggregation.
const BASE = '/ckan'
const RESOURCE_ID = '4252857a-9e5f-47f9-98b1-1291e8f9f692'

// Fields to fetch — excludes "Battery, Plug in Hybrid, or Fuel Cell EV" because its commas break
// the fields= comma-separated list. EV type is handled via separate limit=0 requests.
const RECORD_FIELDS = [
  'Month and Year',
  'Vehicle Make',
  'Vehicle Model',
  'Vehicle Year',
  'Dealership Province/Territory',
].map(f => encodeURIComponent(f)).join(',')

async function parseResponse(res) {
  const text = await res.text()
  let json
  try { json = JSON.parse(text) } catch {
    throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`)
  }
  if (!json.success) {
    throw new Error(json.error?.message ?? JSON.stringify(json.error) ?? 'API success=false')
  }
  return json.result
}

async function fetchJSON(url) {
  return parseResponse(await fetch(url))
}

// Build CKAN filters= JSON object from active non-EV-type filters
function buildFilters(filters, evTypeOverride) {
  const obj = {}
  if (filters.make)        obj['Vehicle Make']                    = filters.make
  if (filters.model)       obj['Vehicle Model']                   = filters.model
  if (filters.vehicleYear) obj['Vehicle Year']                    = filters.vehicleYear
  if (filters.province)    obj['Dealership Province/Territory']   = filters.province
  if (evTypeOverride)      obj['Battery, Plug in Hybrid, or Fuel Cell EV'] = evTypeOverride
  return Object.keys(obj).length ? `&filters=${encodeURIComponent(JSON.stringify(obj))}` : ''
}

// Fetch all matching records with the 5 key fields.
// EV type filter (single value) goes into the CKAN filters= param.
// Multiple EV types: parallel requests merged client-side.
export async function fetchAllRecords(filters) {
  const evTypes = filters.evTypes ?? ['BEV', 'PHEV', 'FCEV']
  const allSelected = evTypes.length === 3
  const base = `${BASE}/datastore_search?resource_id=${RESOURCE_ID}&limit=32767&fields=${RECORD_FIELDS}`

  if (allSelected || evTypes.length === 0) {
    const result = await fetchJSON(base + buildFilters(filters, null))
    return result.records
  }
  if (evTypes.length === 1) {
    const result = await fetchJSON(base + buildFilters(filters, evTypes[0]))
    return result.records
  }
  // 2 EV types: two parallel requests merged
  const results = await Promise.all(
    evTypes.map(t => fetchJSON(base + buildFilters(filters, t)).then(r => r.records))
  )
  return results.flat()
}

// BEV / PHEV / FCEV counts via limit=0 requests (no record download)
export async function fetchEVTypeCounts(filters) {
  const nonEvFilters = buildFilters({ ...filters, evTypes: [] }, null)
  const base = `${BASE}/datastore_search?resource_id=${RESOURCE_ID}&limit=0`
  const types = ['BEV', 'PHEV', 'FCEV']
  const counts = await Promise.all(
    types.map(t =>
      fetchJSON(base + buildFilters({ ...filters, evTypes: [] }, t))
        .then(r => ({ type: t, total: r.total }))
        .catch(() => ({ type: t, total: 0 }))
    )
  )
  const result = {}
  counts.forEach(c => { result[c.type] = c.total })
  return result
}

export async function fetchResourceMeta() {
  return fetchJSON(`${BASE}/resource_show?id=${RESOURCE_ID}`)
}

// Latest Month and Year: distinct values sorted client-side (avoids ORDER BY _id which WAF may block)
export async function fetchLatestMonthYear() {
  const result = await fetchJSON(
    `${BASE}/datastore_search?resource_id=${RESOURCE_ID}&fields=Month%20and%20Year&distinct=true&limit=500`
  )
  const months = result.records.map(r => r['Month and Year']).filter(Boolean)
  if (!months.length) return null
  const MO = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
  const ts = m => {
    const match = m.trim().match(/^([A-Za-z]+),?\s*(\d+)$/)
    if (!match) return 0
    const yr = parseInt(match[2], 10) + (parseInt(match[2], 10) < 50 ? 2000 : 1900)
    return yr * 12 + MO.indexOf(match[1].toLowerCase().slice(0, 3))
  }
  return months.sort((a, b) => ts(a) - ts(b)).at(-1) ?? null
}

export async function fetchDistinct(field) {
  const result = await fetchJSON(
    `${BASE}/datastore_search?resource_id=${RESOURCE_ID}&fields=${encodeURIComponent(field)}&distinct=true&limit=500`
  )
  return result.records.map(r => r[field]).filter(Boolean).sort()
}

// Uses datastore_search filters param (JSON key) — handles commas in field names correctly
export async function fetchDistinctModels(make) {
  const filters = encodeURIComponent(JSON.stringify({ 'Vehicle Make': make }))
  const result = await fetchJSON(
    `${BASE}/datastore_search?resource_id=${RESOURCE_ID}&fields=Vehicle%20Model&distinct=true&limit=500&filters=${filters}`
  )
  return result.records.map(r => r['Vehicle Model']).filter(Boolean).sort()
}
