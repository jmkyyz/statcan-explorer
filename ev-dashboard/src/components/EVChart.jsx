import { useState } from 'react'
import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { useChartData } from '../hooks/useEVData'

const PALETTE = [
  '#3b82f6', // blue-500
  '#10b981', // emerald-500
  '#f59e0b', // amber-500
  '#ef4444', // red-500
  '#8b5cf6', // violet-500
  '#64748b', // slate-500 — "Other"
]

function SkeletonChart() {
  return (
    <div className="h-80 bg-slate-100 dark:bg-slate-800 rounded-xl animate-pulse flex items-end gap-2 px-4 pb-4 overflow-hidden">
      {[40, 65, 50, 80, 55, 70, 90, 60, 75, 85, 45, 95].map((h, i) => (
        <div
          key={i}
          className="flex-1 bg-slate-200 dark:bg-slate-700 rounded-t"
          style={{ height: `${h}%` }}
        />
      ))}
    </div>
  )
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, p) => s + (p.value || 0), 0)
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg p-3 text-sm min-w-40">
      <p className="font-semibold text-slate-700 dark:text-slate-200 mb-2">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: p.color }} />
            <span className="text-slate-600 dark:text-slate-400 truncate max-w-32">{p.name}</span>
          </span>
          <span className="font-mono font-semibold text-slate-800 dark:text-slate-100">
            {p.value?.toLocaleString()}
          </span>
        </div>
      ))}
      {payload.length > 1 && (
        <div className="border-t border-slate-100 dark:border-slate-700 mt-2 pt-2 flex justify-between font-semibold">
          <span className="text-slate-500">Total</span>
          <span className="font-mono text-slate-800 dark:text-slate-100">{total.toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}

export default function EVChart({ filters }) {
  const [chartType, setChartType] = useState('bar')
  const { data, isLoading, isFetching, isError, error } = useChartData(filters)

  const loading = isLoading && !data

  const { chartRows = [], keys = [] } = data ?? {}

  const ChartComponent = chartType === 'bar' ? BarChart : LineChart

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-800 dark:text-slate-100">
            Incentive Requests by Month
          </h3>
          {isFetching && !loading && (
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">Refreshing…</p>
          )}
        </div>
        <div className="flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden text-sm">
          <button
            onClick={() => setChartType('bar')}
            className={`px-3 py-1.5 transition-colors ${chartType === 'bar'
              ? 'bg-blue-500 text-white'
              : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700'
            }`}
          >
            Bar
          </button>
          <button
            onClick={() => setChartType('line')}
            className={`px-3 py-1.5 transition-colors border-l border-slate-200 dark:border-slate-700 ${chartType === 'line'
              ? 'bg-blue-500 text-white'
              : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700'
            }`}
          >
            Line
          </button>
        </div>
      </div>

      {loading ? (
        <SkeletonChart />
      ) : isError && !data ? (
        <div className="h-80 flex flex-col items-center justify-center gap-2 text-center px-4">
          <p className="text-red-500 dark:text-red-400 font-medium text-sm">Failed to load chart data</p>
          <p className="text-slate-400 dark:text-slate-600 text-xs max-w-md">{error?.message}</p>
        </div>
      ) : chartRows.length === 0 ? (
        <div className="h-80 flex flex-col items-center justify-center gap-1">
          <p className="text-slate-400 dark:text-slate-600">No data for the selected date range</p>
          <p className="text-xs text-slate-300 dark:text-slate-700">
            The dataset may not yet include data for the period you selected — try widening the date range
          </p>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <ChartComponent data={chartRows} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-slate-100 dark:text-slate-800" />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: 'currentColor' }}
              className="text-slate-500"
              interval="preserveStartEnd"
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: 'currentColor' }}
              className="text-slate-500"
              tickLine={false}
              axisLine={false}
              tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v}
              width={40}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: 12, paddingTop: 12 }}
              iconType="square"
            />
            {keys.map((key, i) =>
              chartType === 'bar' ? (
                <Bar key={key} dataKey={key} stackId="a" fill={PALETTE[i % PALETTE.length]} />
              ) : (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              )
            )}
          </ChartComponent>
        </ResponsiveContainer>
      )}
    </div>
  )
}
