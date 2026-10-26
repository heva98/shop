import { useMemo } from 'react'
import { formatValue, headerSpans } from '../pivot.js'

// Every header row is 34px tall (analytics.css), so each sticks below the last.
const ROW_HEIGHT = 34

// `canDrill(colCombo, rowCombo)` says whether a cell can be broken down when
// clicked; `onDrill(colCombo, rowCombo)` opens that breakdown.
export default function PivotTable({ pivot, options, dimensionLabel, canDrill, onDrill }) {
  const { colDims, rowDims, colCombos, rowCombos, cell, label, isPlaceholder, isTotal } = pivot
  const showLabels = options.showDimensionLabels
  const labelRow = showLabels && !rowDims.every(isPlaceholder)

  const rowSpanStarts = useMemo(
    () => rowDims.map((_, level) => new Map(headerSpans(rowCombos, level).map((s) => [s.start, s.span]))),
    [rowDims, rowCombos],
  )

  return (
    <div className="viz-pivot">
      <table>
        <thead>
          {colDims.map((dim, level) => (
            <tr key={dim}>
              <th colSpan={rowDims.length} className="dim right" style={{ top: level * ROW_HEIGHT }}>
                {showLabels && !isPlaceholder(dim) ? dimensionLabel(dim) : ''}
              </th>
              {headerSpans(colCombos, level).map((s) => (
                <th key={s.start} colSpan={s.span} style={{ top: level * ROW_HEIGHT }}
                  className={isTotal(colCombos[s.start].slice(0, level + 1)) ? 'total' : undefined}>
                  {label(dim, s.id)}
                </th>
              ))}
            </tr>
          ))}
          {labelRow && (
            <tr>
              {rowDims.map((dim) => (
                <th key={dim} className="dim left" style={{ top: colDims.length * ROW_HEIGHT }}>
                  {isPlaceholder(dim) ? '' : dimensionLabel(dim)}
                </th>
              ))}
              <th colSpan={colCombos.length} className="dim" style={{ top: colDims.length * ROW_HEIGHT }} />
            </tr>
          )}
        </thead>
        <tbody>
          {rowCombos.map((rowCombo, ri) => {
            const totalRow = isTotal(rowCombo)
            return (
              <tr key={rowCombo.join('|')}>
                {rowDims.map((dim, level) => {
                  const span = rowSpanStarts[level].get(ri)
                  if (span === undefined) return null
                  return (
                    <th key={dim} rowSpan={span} scope="row" className={totalRow ? 'total' : undefined}>
                      {label(dim, rowCombo[level])}
                    </th>
                  )
                })}
                {colCombos.map((colCombo) => {
                  const c = cell(colCombo, rowCombo)
                  const drillable = Boolean(c && canDrill?.(colCombo, rowCombo))
                  const text = c ? formatValue(c.value, c.unit, options.decimals) : ''
                  return (
                    <td key={colCombo.join('|')} className={totalRow || isTotal(colCombo) ? 'total' : undefined}>
                      {drillable ? (
                        <button type="button" className="viz-cell-btn" onClick={() => onDrill(colCombo, rowCombo)}
                          title="Break this number down">
                          {text}
                        </button>
                      ) : text}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
