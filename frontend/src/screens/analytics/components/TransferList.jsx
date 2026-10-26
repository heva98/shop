import { useMemo, useState } from 'react'
import { Icon, Input } from '../../../components/ds/index.js'

/**
 * Two-pane item picker: available items (searchable, with "Select all") on
 * the left, the ordered selection on the right. `available` entries are
 * { id, label, depth?, description? }; `labelFor` names selected ids that
 * aren't in the current `available` list (another tab's periods, say).
 * With `onSearch`, the text is handed to the caller (a server-side search)
 * instead of filtering `available` here.
 */
export default function TransferList({
  available, selected, onChange, labelFor, header, emptyText = 'No items.', onSearch, searchPlaceholder = 'Search',
}) {
  const [search, setSearch] = useState('')
  const selectedSet = useMemo(() => new Set(selected), [selected])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q || onSearch) return available
    return available.filter((i) => i.label.toLowerCase().includes(q) || i.id.toLowerCase().includes(q))
  }, [available, search, onSearch])

  const toggle = (id) => onChange(selectedSet.has(id) ? selected.filter((s) => s !== id) : [...selected, id])
  const selectAll = () => onChange([...selected, ...filtered.map((i) => i.id).filter((id) => !selectedSet.has(id))])

  return (
    <div className="viz-transfer">
      <div className="viz-transfer-col">
        {header}
        <Input
          value={search}
          prefixIcon="search"
          placeholder={searchPlaceholder}
          onChange={(e) => { setSearch(e.target.value); onSearch?.(e.target.value) }}
        />
        <div className="viz-transfer-meta">
          <span>{filtered.length} available</span>
          <button type="button" className="viz-link" onClick={selectAll} disabled={!filtered.length}>Select all</button>
        </div>
        <ul className="viz-list">
          {filtered.length === 0 && <li className="viz-empty-row">{emptyText}</li>}
          {filtered.map((item) => {
            const on = selectedSet.has(item.id)
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`viz-item${on ? ' on' : ''}`}
                  aria-pressed={on}
                  title={item.description || undefined}
                  onClick={() => toggle(item.id)}
                  style={{ paddingLeft: 12 + (search ? 0 : item.depth ?? 0) * 18 }}
                >
                  <span className="viz-box">{on && <Icon name="checkmark" size={12} strokeWidth={3} />}</span>
                  <span style={{ minWidth: 0 }}>
                    {item.label}
                    {item.description && <span className="viz-item-desc">{item.description}</span>}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="viz-transfer-col" style={{ justifyContent: 'flex-end' }}>
        <div className="viz-transfer-meta">
          <span style={{ fontWeight: 600 }}>{selected.length} selected</span>
          <button type="button" className="viz-link danger" onClick={() => onChange([])} disabled={!selected.length}>Clear all</button>
        </div>
        <ul className="viz-list selected">
          {selected.length === 0 && <li className="viz-empty-row">Nothing selected.</li>}
          {selected.map((id) => (
            <li key={id} className="viz-selected-row">
              <span>{labelFor(id)}</span>
              <button type="button" className="ds-icon-btn" onClick={() => toggle(id)} aria-label={`Remove ${labelFor(id)}`}>
                <Icon name="cross" size={14} />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
