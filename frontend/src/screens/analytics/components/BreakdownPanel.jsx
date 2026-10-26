import { useEffect, useMemo, useState } from 'react'
import { Button, Icon, NoticeBox, Select } from '../../../components/ds/index.js'
import { runAnalyticsQuery } from '../../../api/analytics.js'
import { useApi } from '../../../hooks/useApi.js'
import { breakdownConfig, breakdownOptions, breakdownQuery } from '../breakdown.js'
import { formatValue } from '../pivot.js'
import { apiErrorMessage, makeLabelFor } from '../savedVisualizations.js'

const ADDITIVE = ['sum', 'count']

/**
 * Side panel breaking one pivot cell down by another dimension.
 *
 * @param cell         { metric, filters } from breakdown.cellFilters
 * @param cellSummary  [{ label, value }] describing the cell, shown as its heading
 */
export default function BreakdownPanel({
  cell, cellSummary, metric, dimensionsById, dimensionLabel, itemLabels, options, onOpenAsTable, onClose,
}) {
  const choices = useMemo(() => breakdownOptions(metric, cell.filters, dimensionsById), [metric, cell, dimensionsById])
  const [byId, setById] = useState(() => (choices.find((c) => c.id === 'product') ?? choices[0])?.id ?? null)
  const by = choices.find((c) => c.id === byId)
  const paramString = by ? breakdownQuery(cell, by).toString() : null
  const result = useApi(() => (paramString ? runAnalyticsQuery(new URLSearchParams(paramString)) : null), [paramString])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const rows = useMemo(() => {
    if (!result.data || !by) return []
    const labelFor = makeLabelFor(itemLabels, result.data)
    const index = Object.fromEntries(result.data.headers.map((h, i) => [h.name, i]))
    const list = result.data.rows.map((r) => ({ id: r[index[by.id]], label: labelFor(by.id, r[index[by.id]]), value: r[index.value] }))
    // Periods read best in time order; everything else biggest first.
    return by.id === 'pe' ? list : list.sort((a, b) => b.value - a.value)
  }, [result.data, by, itemLabels])

  const additive = ADDITIVE.includes(metric.aggregation)
  const sum = rows.reduce((s, r) => s + Math.max(r.value, 0), 0)

  let body
  if (!by) body = <p className="viz-empty-row">This number can't be broken down any further.</p>
  else if (result.loading) body = <div className="viz-center"><div className="viz-spinner" /></div>
  else if (result.error) body = <div style={{ padding: 16 }}><NoticeBox variant="error">{apiErrorMessage(result.error, 'The breakdown could not be loaded.')}</NoticeBox></div>
  else if (!rows.length) body = <p className="viz-empty-row">Nothing to break down here.</p>
  else {
    body = (
      <table className="viz-breakdown">
        <thead>
          <tr>
            <th>{dimensionLabel(by.id)}</th>
            <th className="num">{metric.label}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>
                {r.label}
                {additive && sum > 0 && (
                  <div className="viz-share" title={`${Math.round((Math.max(r.value, 0) / sum) * 100)}% of the cell`}>
                    <span style={{ width: `${(Math.max(r.value, 0) / sum) * 100}%` }} />
                  </div>
                )}
              </td>
              <td className="num">
                {formatValue(r.value, metric.unit, options.decimals)}
                {additive && sum > 0 && <div className="viz-muted">{Math.round((Math.max(r.value, 0) / sum) * 100)}%</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  return (
    <>
      <div className="viz-drawer-backdrop" onClick={onClose} />
      <aside className="viz-drawer" role="dialog" aria-modal="true" aria-labelledby="viz-breakdown-title">
        <div className="viz-drawer-head">
          <div style={{ minWidth: 0 }}>
            <h2 id="viz-breakdown-title">Break this number down</h2>
            <dl className="viz-summary">
              {cellSummary.map(({ label, value }) => (
                <div key={label} style={{ display: 'contents' }}>
                  <dt>{label}</dt>
                  <dd title={value}>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
          <button type="button" className="ds-icon-btn" onClick={onClose} aria-label="Close"><Icon name="cross" size={18} /></button>
        </div>
        {choices.length > 0 && (
          <div className="viz-drawer-tools">
            <label style={{ flex: 1 }}>
              <span className="ds-label">By</span>
              <Select value={byId ?? ''} onChange={(e) => setById(e.target.value)}
                options={choices.map((c) => ({ value: c.id, label: c.id === 'pe' ? 'Period (one level down)' : dimensionLabel(c.id) }))} />
            </label>
            <Button size="small" disabled={!by} onClick={() => onOpenAsTable(breakdownConfig(cell, by, options))}>
              <Icon name="pivot-table" size={16} /> Open as table
            </Button>
          </div>
        )}
        <div className="viz-drawer-body">{body}</div>
        {rows.length > 0 && (
          <p className="viz-drawer-foot" style={{ margin: 0 }}>
            {rows.length} {rows.length === 1 ? 'row' : 'rows'}
            {additive ? ' · shares are of the rows shown' : ''}
          </p>
        )}
      </aside>
    </>
  )
}
