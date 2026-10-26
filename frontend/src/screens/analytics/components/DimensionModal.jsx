import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Chip, Modal, Select } from '../../../components/ds/index.js'
import { searchDimensionItems } from '../../../api/analytics.js'
import {
  AXES, AXIS_LABELS, FIXED_PERIOD_TYPES, MONTHS, fixedPeriods, flattenTree, periodLabel, placementError,
} from '../visualizationConfig.js'
import TransferList from './TransferList.jsx'

function DataHeader({ groups, group, onGroup }) {
  if (groups.length < 2) return null
  return (
    <div className="viz-search">
      <Select value={group} onChange={(e) => onGroup(e.target.value)} aria-label="Data group"
        options={[{ value: '', label: 'All groups' }, ...groups.map((g) => ({ value: g.id, label: g.label }))]} />
    </div>
  )
}

const THIS_YEAR = new Date().getFullYear()
const YEARS = Array.from({ length: 10 }, (_, i) => THIS_YEAR - i)

function PeriodSelector({ dim, draft, setDraft }) {
  const [tab, setTab] = useState('relative')
  const [periodType, setPeriodType] = useState('MONTH')
  const [year, setYear] = useState(THIS_YEAR)
  const [month, setMonth] = useState(new Date().getMonth() + 1)

  const relative = dim.items.filter((i) => i.type === 'relative')
  const available = tab === 'relative'
    ? relative
    : fixedPeriods(periodType, year, month).map((id) => ({ id, label: periodLabel(id) }))
  const relativeLabels = Object.fromEntries(relative.map((i) => [i.id, i.label]))

  const header = (
    <>
      <div className="ds-chip-row" style={{ marginBottom: 10 }}>
        <Chip dense selected={tab === 'relative'} onClick={() => setTab('relative')}>Relative periods</Chip>
        <Chip dense selected={tab === 'fixed'} onClick={() => setTab('fixed')}>Fixed periods</Chip>
      </div>
      {tab === 'fixed' && (
        <div className="viz-row2" style={periodType === 'DAY' ? { gridTemplateColumns: '1fr 1fr 1fr' } : undefined}>
          <Select value={periodType} onChange={(e) => setPeriodType(e.target.value)} aria-label="Period type"
            options={FIXED_PERIOD_TYPES.map((t) => ({ value: t.id, label: t.label }))} />
          <Select value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Year" options={YEARS} />
          {periodType === 'DAY' && (
            <Select value={month} onChange={(e) => setMonth(Number(e.target.value))} aria-label="Month"
              options={MONTHS.map((m, i) => ({ value: i + 1, label: m }))} />
          )}
        </div>
      )}
    </>
  )

  return (
    <TransferList header={header} available={available} selected={draft} onChange={setDraft}
      labelFor={(id) => relativeLabels[id] ?? periodLabel(id)} />
  )
}

// Products and customers: searched on the server, a page at a time.
function useItemSearch(dim, selected) {
  const [text, setText] = useState('')
  const [state, setState] = useState({ items: [], loading: true, error: false })
  const [names, setNames] = useState({})
  const first = useRef(selected)

  useEffect(() => {
    if (!dim.lazy) return undefined
    let cancelled = false
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true }))
      // The first call also names what was already selected.
      const ids = first.current
      first.current = []
      searchDimensionItems(dim.id, text, ids).then(
        (items) => {
          if (cancelled) return
          const named = Object.fromEntries(items.map((i) => [i.id, i.label]))
          setNames((n) => ({ ...n, ...named }))
          setState({ items, loading: false, error: false })
        },
        () => { if (!cancelled) setState({ items: [], loading: false, error: true }) },
      )
    }, text ? 250 : 0)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [dim, text])

  return { ...state, names, setText }
}

export default function DimensionModal({
  dim, title, groups, selected, axis, axisNames = AXIS_LABELS, labelFor, onApply, onAddTo, onClose,
}) {
  const [draft, setDraft] = useState(selected)
  const [group, setGroup] = useState('')
  const search = useItemSearch(dim, selected)

  const available = useMemo(() => {
    if (dim.kind === 'org_unit') return flattenTree(dim.items)
    if (dim.lazy) return search.items
    if (dim.kind === 'data') {
      return dim.items
        .filter((m) => !group || m.group === group)
        .map((m) => ({ id: m.id, label: m.label, description: m.description }))
    }
    // A breakdown can also pick out the facts with no value (no category…).
    return [...dim.items, { id: '', label: dim.blank_label }]
  }, [dim, group, search.items])

  const labels = useMemo(() => {
    const list = dim.kind === 'org_unit' ? flattenTree(dim.items) : dim.lazy ? [] : dim.items
    return { ...Object.fromEntries(list.map((i) => [i.id, i.label])), '': dim.blank_label, ...search.names }
  }, [dim, search.names])

  let body
  if (dim.kind === 'period') {
    body = <PeriodSelector dim={dim} draft={draft} setDraft={setDraft} />
  } else {
    body = (
      <TransferList
        header={dim.kind === 'data' ? <DataHeader groups={groups} group={group} onGroup={setGroup} /> : null}
        available={available}
        selected={draft}
        onChange={setDraft}
        labelFor={(id) => labels[id] ?? labelFor(dim.id, id)}
        onSearch={dim.lazy ? search.setText : undefined}
        searchPlaceholder={dim.lazy ? `Search ${dim.label.toLowerCase()}s` : 'Search'}
        emptyText={dim.lazy && search.loading ? 'Searching…' : dim.lazy && search.error ? 'Could not search. Try again.' : 'No items.'}
      />
    )
  }

  const hint = dim.kind === 'dynamic' && !dim.filter_only
    ? 'Leave empty to show every item when this dimension is in Columns or Rows.'
    : dim.kind === 'data' ? 'Hover an item to see how it is calculated.' : null

  const footer = (
    <>
      <Button onClick={onClose}>Cancel</Button>
      {axis ? (
        <>
          <Button variant="secondary" onClick={() => onApply(draft, false)}>Keep selection</Button>
          <Button variant="primary" onClick={() => onApply(draft, true)}>Update</Button>
        </>
      ) : (
        AXES.filter((a) => !placementError(dim, a)).map((a) => (
          <Button key={a} variant={a === 'filters' ? 'secondary' : 'primary'} onClick={() => onAddTo(a, draft)}>
            Add to {axisNames[a]}
          </Button>
        ))
      )}
    </>
  )

  return (
    <Modal title={title} onClose={onClose} size="xl" footer={footer}>
      {body}
      {hint && <p className="viz-help">{hint}</p>}
    </Modal>
  )
}
