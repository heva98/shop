import { useState } from 'react'
import { Icon, Menu, MenuItem } from '../../../components/ds/index.js'
import { AXES, DIM_MIME, axisLabels, placementError } from '../visualizationConfig.js'

function Chip({ dimId, axis, axisNames, index, label, count, emptyWarning, menuOpen, onMenu, onOpen, onDropAt, onMove, onRemove, canMoveTo }) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DIM_MIME, dimId)
        e.dataTransfer.effectAllowed = 'move'
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        // Dropping onto a chip inserts before it.
        e.preventDefault()
        e.stopPropagation()
        onDropAt(e.dataTransfer.getData(DIM_MIME), axis, index)
      }}
      className={`viz-chip ${axis}${emptyWarning ? ' empty' : ''}`}
    >
      <button type="button" className="viz-chip-main" onClick={() => onOpen(dimId)}
        title={emptyWarning ? 'Nothing selected' : `${label}: ${count || 'all'} selected`}>
        {label}
        <span className="viz-chip-count">{count > 0 ? count : emptyWarning ? '0' : 'all'}</span>
      </button>
      <button type="button" className="viz-chip-more" onClick={() => onMenu(menuOpen ? null : dimId)}
        aria-label={`${label} options`} aria-haspopup="menu" aria-expanded={menuOpen}>
        <Icon name="more" size={14} />
      </button>
      {menuOpen && (
        <>
          <div className="viz-scrim" onClick={() => onMenu(null)} />
          <div className="viz-popover">
            <Menu>
              {AXES.filter((a) => a !== axis && canMoveTo(a)).map((a) => (
                <MenuItem key={a} label={`Move to ${axisNames[a]}`} onClick={() => onMove(dimId, a)} />
              ))}
              <MenuItem label="Remove" destructive onClick={() => onRemove(dimId)} />
            </Menu>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Columns / Rows / Filter drop zones. Chips can be dragged between zones (or
 * in from the dimension panel); the ⋯ menu offers the same moves for touch
 * screens, where HTML drag and drop isn't available.
 */
export default function LayoutArea({ config, dimensionsById, dimensionLabel, onOpen, onPlace, onRemove }) {
  const [menu, setMenu] = useState(null)
  const [over, setOver] = useState(null)
  const axisNames = axisLabels(config.type)

  const drop = (dimId, axis, index) => {
    setOver(null)
    if (dimId) onPlace(dimId, axis, index)
  }

  return (
    <div className="viz-layout">
      {AXES.map((axis) => (
        <div
          key={axis}
          onDragOver={(e) => {
            e.preventDefault()
            if (over !== axis) setOver(axis)
          }}
          onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOver(null) }}
          onDrop={(e) => {
            e.preventDefault()
            drop(e.dataTransfer.getData(DIM_MIME), axis)
          }}
          className={`viz-zone${over === axis ? ' over' : ''}`}
        >
          <span className="viz-zone-label">{axisNames[axis]}</span>
          <div className="viz-zone-chips">
            {config[axis].length === 0 && <span className="viz-zone-empty">Drop a dimension here</span>}
            {config[axis].map((dimId, index) => {
              const count = config.items[dimId]?.length ?? 0
              const required = ['dx', 'pe'].includes(dimId) || (dimId === 'ou' && axis !== 'filters')
              return (
                <Chip
                  key={dimId}
                  dimId={dimId}
                  axis={axis}
                  axisNames={axisNames}
                  index={index}
                  label={dimensionLabel(dimId)}
                  count={count}
                  emptyWarning={count === 0 && required}
                  menuOpen={menu === dimId}
                  onMenu={setMenu}
                  onOpen={onOpen}
                  onDropAt={drop}
                  onMove={(id, a) => { setMenu(null); onPlace(id, a) }}
                  onRemove={(id) => { setMenu(null); onRemove(id) }}
                  canMoveTo={(a) => !placementError(dimensionsById[dimId], a)}
                />
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
