import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react'
import Button from './Button.jsx'
import EmptyState from './EmptyState.jsx'
import Icon from './Icon.jsx'
import NoticeBox from './NoticeBox.jsx'
import Skeleton from './Skeleton.jsx'
import { useDelayedFlag } from './useDelayedFlag.js'
import { ariaSort, nextSort, rowKeyOf, sortRows } from './dataTable.js'
import { apiErrorText } from '../../lib/apiError.js'
import { t, useLanguage } from '../../i18n/index.js'

/** Table card (DESIGN.md › Table) with loading, error, empty and sorted
 * states built in. See components/ds/README.md › DataTable for the full API.
 *
 *   <DataTable
 *     caption={t('Stores')}
 *     columns={[
 *       { key: 'name', header: t('Store'), primary: true, sortable: true },
 *       { key: 'stock', header: t('Units'), align: 'end', sortable: true, firstDirection: 'desc' },
 *       { key: 'actions', header: t('Actions'), cell: (row) => <Button size="small">…</Button> },
 *     ]}
 *     rows={stores}
 *     loading={loading} error={error} onRetry={refetch}
 *     empty={<EmptyState title={t('No stores yet.')} />}
 *   />
 *
 * Phones (≤640px) get one card per row with each value labelled by its
 * header (`layout="cards"`, the default) or keep a sideways-scrolling
 * table (`layout="scroll"`) for wide numeric grids. */
export default function DataTable({
  columns,
  rows,
  rowKey = 'id',
  caption,
  showCaption = false,
  loading = false,
  error = null,
  errorTitle,
  onRetry,
  empty,
  sort: sortProp,
  defaultSort = null,
  onSortChange,
  manualSort = false,
  skeletonRows = 5,
  layout = 'cards',
  minWidth,
  footer,
  rowClassName,
  renderDetail,
  density = 'comfortable',
  delay = 200,
  style,
  className,
}) {
  const lang = useLanguage()
  const captionId = useId()
  const [ownSort, setOwnSort] = useState(defaultSort)
  const sort = sortProp !== undefined ? sortProp : ownSort
  const list = Array.isArray(rows) ? rows : NO_ROWS
  const hasRows = list.length > 0
  const showSkeleton = useDelayedFlag(loading && !hasRows, delay)

  const visibleRows = useMemo(
    () => (manualSort ? list : sortRows(list, columns, sort, lang)),
    [list, columns, sort, lang, manualSort],
  )

  function changeSort(column) {
    const next = nextSort(sort, column.key, column.firstDirection)
    if (sortProp === undefined) setOwnSort(next)
    onSortChange?.(next)
  }

  const scrollRef = useRef(null)
  const scrollable = useIsOverflowing(scrollRef)
  const sortable = columns.filter((c) => c.sortable)
  const span = columns.length

  let stateRow = null
  if (!hasRows) {
    if (error && !loading) {
      stateRow = (
        <div className="ds-dt-state">
          <NoticeBox
            variant="error"
            title={errorTitle || t('Could not load this.')}
            action={onRetry && <Button size="small" onClick={() => onRetry()}>{t('Try again')}</Button>}
          >
            {apiErrorText(error, error?.message)}
          </NoticeBox>
        </div>
      )
    } else if (!loading) {
      if (empty == null) stateRow = <EmptyState icon="search" title={t('Nothing to show yet.')} />
      else if (typeof empty === 'string') stateRow = <p className="ds-dt-empty-text">{empty}</p>
      else stateRow = empty
    }
  }

  return (
    <div className={['ds-dt', className].filter(Boolean).join(' ')} data-layout={layout} data-density={density} style={style}>
      {error && hasRows && !loading && (
        <NoticeBox
          variant="error"
          action={onRetry && <Button size="small" onClick={() => onRetry()}>{t('Try again')}</Button>}
        >
          {apiErrorText(error, error?.message)}
        </NoticeBox>
      )}

      {sortable.length > 0 && layout === 'cards' && hasRows && (
        <MobileSort columns={sortable} sort={sort} onChange={(next) => {
          if (sortProp === undefined) setOwnSort(next)
          onSortChange?.(next)
        }} />
      )}

      <div
        ref={scrollRef}
        className="ds-table-card"
        // A scrolling region must be reachable by keyboard (WCAG 2.1.1).
        {...(scrollable ? { tabIndex: 0, role: 'region', ...(caption ? { 'aria-labelledby': captionId } : { 'aria-label': t('Table') }) } : {})}
      >
        <table
          role="table"
          aria-busy={loading || undefined}
          style={minWidth ? { minWidth } : undefined}
          data-refreshing={(loading && hasRows) || undefined}
        >
          {caption && <caption id={captionId} className={showCaption ? 'ds-dt-caption' : 'sr-only'}>{caption}</caption>}
          <thead role="rowgroup">
            <tr role="row">
              {columns.map((col) => (
                <th
                  key={col.key}
                  role="columnheader"
                  scope="col"
                  aria-sort={col.sortable ? ariaSort(sort, col.key) : undefined}
                  className={cellClass(col)}
                  style={col.width ? { width: col.width } : undefined}
                >
                  {col.sortable ? (
                    <button type="button" className="ds-dt-sort" onClick={() => changeSort(col)}>
                      {col.header}
                      <SortIcon direction={sort?.key === col.key ? sort.direction : null} />
                    </button>
                  ) : col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody role="rowgroup">
            {visibleRows.map((row, index) => {
              const key = rowKeyOf(rowKey, row, index)
              const detail = renderDetail?.(row, index)
              return (
                <Fragment key={key}>
                  <tr role="row" className={[rowClassName?.(row), detail && 'has-detail'].filter(Boolean).join(' ') || undefined}>
                    {columns.map((col) => (
                      <td key={col.key} role="cell" className={cellClass(col)} data-label={labelOf(col)}>
                        {renderCell(col, row, index)}
                      </td>
                    ))}
                  </tr>
                  {detail && (
                    <tr role="row" className="ds-dt-detail">
                      <td role="cell" colSpan={span}>{detail}</td>
                    </tr>
                  )}
                </Fragment>
              )
            })}

            {showSkeleton && Array.from({ length: skeletonRows }, (_, i) => (
              <tr key={`skeleton-${i}`} role="row" className="ds-dt-skeleton" aria-hidden="true">
                {columns.map((col, c) => (
                  <td key={col.key} role="cell" className={cellClass(col)} data-label={labelOf(col)}>
                    <Skeleton width={SKELETON_WIDTHS[(i + c) % SKELETON_WIDTHS.length]} />
                  </td>
                ))}
              </tr>
            ))}

            {stateRow && (
              <tr role="row" className="ds-dt-state-row">
                <td role="cell" colSpan={span}>{stateRow}</td>
              </tr>
            )}
          </tbody>
        </table>
        {showSkeleton && <span role="status" className="sr-only">{t('Loading…')}</span>}
      </div>

      {footer && <div className="ds-dt-foot">{footer}</div>}
    </div>
  )
}

const NO_ROWS = []

// Varied bar widths so skeleton rows look like text, not a grid.
const SKELETON_WIDTHS = ['72%', '48%', '60%', '36%', '54%']

function labelOf(col) {
  if (col.label != null) return col.label
  return typeof col.header === 'string' ? col.header : ''
}

function cellClass(col) {
  return [
    col.primary && 'primary',
    col.align === 'end' && 'end',
    col.align === 'center' && 'center',
    col.hideOnMobile && 'hide-mobile',
    col.className,
  ].filter(Boolean).join(' ') || undefined
}

function renderCell(col, row, index) {
  if (col.cell) return col.cell(row, index)
  const value = row?.[col.key]
  return value == null || value === '' ? '—' : value
}

function SortIcon({ direction }) {
  if (!direction) return <Icon name="chevron-down" size={14} className="ds-dt-sort-icon idle" />
  return <Icon name={direction === 'asc' ? 'arrow-up' : 'arrow-down'} size={14} className="ds-dt-sort-icon" />
}

/** On phones the header row is hidden, so sorting moves into a select. */
function MobileSort({ columns, sort, onChange }) {
  const value = sort ? `${sort.key}:${sort.direction}` : ''
  return (
    <label className="ds-dt-mobile-sort">
      <span className="ds-label">{t('Sort by')}</span>
      <select
        className="ds-input"
        value={value}
        onChange={(e) => {
          const [key, direction] = e.target.value.split(':')
          onChange(key ? { key, direction } : null)
        }}
      >
        <option value="">{t('Default order')}</option>
        {columns.flatMap((col) => {
          const label = labelOf(col)
          return [
            <option key={`${col.key}:asc`} value={`${col.key}:asc`}>{t('{label}, low to high', { label })}</option>,
            <option key={`${col.key}:desc`} value={`${col.key}:desc`}>{t('{label}, high to low', { label })}</option>,
          ]
        })}
      </select>
    </label>
  )
}

/** True while the element's content is wider than the element. */
function useIsOverflowing(ref) {
  const [overflowing, setOverflowing] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const check = () => setOverflowing(el.scrollWidth > el.clientWidth + 1)
    const observer = new ResizeObserver(check)
    observer.observe(el)
    if (el.firstElementChild) observer.observe(el.firstElementChild)
    check()
    return () => observer.disconnect()
  }, [ref])
  return overflowing
}
