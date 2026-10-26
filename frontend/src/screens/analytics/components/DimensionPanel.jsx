import { useState } from 'react'
import { Icon, Input } from '../../../components/ds/index.js'
import { DIM_MIME, FIXED_DIMENSIONS, axisLabels, axisOf } from '../visualizationConfig.js'

const FIXED_ICONS = { dx: 'database', pe: 'calendar', ou: 'store' }

function DimensionRow({ dim, label, config, notApplicable, onOpen }) {
  const axis = axisOf(config, dim.id)
  const count = config.items[dim.id]?.length ?? 0
  return (
    <li>
      <button
        type="button"
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(DIM_MIME, dim.id)
          e.dataTransfer.effectAllowed = 'move'
        }}
        onClick={() => onOpen(dim.id)}
        title={notApplicable ?? undefined}
        className={`viz-dim${notApplicable ? ' na' : ''}`}
      >
        <Icon name={FIXED_ICONS[dim.id] ?? 'layers'} size={15} />
        <span className="viz-dim-label">{label}</span>
        {count > 0 && <span className="viz-dim-count">{count}</span>}
        {axis && <span className={`viz-dot ${axis}`} title={`In ${axisLabels(config.type)[axis]}`} />}
      </button>
    </li>
  )
}

export default function DimensionPanel({ dimensions, config, dimensionLabel, notApplicable, onOpen }) {
  const [search, setSearch] = useState('')
  const fixed = dimensions.filter((d) => FIXED_DIMENSIONS.includes(d.id))
  const q = search.trim().toLowerCase()
  const dynamic = dimensions
    .filter((d) => !FIXED_DIMENSIONS.includes(d.id))
    .filter((d) => !q || d.label.toLowerCase().includes(q))

  const row = (dim) => (
    <DimensionRow key={dim.id} dim={dim} label={dimensionLabel(dim.id)} config={config}
      notApplicable={notApplicable(dim)} onOpen={onOpen} />
  )

  return (
    <div className="viz-panel">
      <div className="viz-panel-section">
        <h2 className="viz-overline">Main dimensions</h2>
        <ul className="viz-dim-list">{fixed.map(row)}</ul>
      </div>
      <div className="viz-panel-section grow">
        <h2 className="viz-overline">Break down by</h2>
        <div className="viz-search">
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter dimensions" prefixIcon="search" />
        </div>
        <ul className="viz-dim-list">
          {dynamic.length === 0 && <li className="viz-empty-row">No dimensions.</li>}
          {dynamic.map(row)}
        </ul>
      </div>
      <p className="viz-hint">Click a dimension to choose items, or drag it onto the layout.</p>
    </div>
  )
}
