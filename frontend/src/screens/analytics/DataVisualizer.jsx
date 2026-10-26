import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { Button, Icon, Menu, MenuItem, Modal, NoticeBox, Select } from '../../components/ds/index.js'
import {
  createVisualization, deleteVisualization, getAnalyticsDimensions, getVisualization, pinVisualization,
  runAnalyticsQuery, unpinVisualization, updateVisualization,
} from '../../api/analytics.js'
import { useApi } from '../../hooks/useApi.js'
import { cellFilters } from './breakdown.js'
import { buildChartModel, singleValueStatus } from './charts.js'
import BreakdownPanel from './components/BreakdownPanel.jsx'
import ChartView from './components/ChartView.jsx'
import DimensionModal from './components/DimensionModal.jsx'
import DimensionPanel from './components/DimensionPanel.jsx'
import FileMenu from './components/FileMenu.jsx'
import LayoutArea from './components/LayoutArea.jsx'
import OptionsModal from './components/OptionsModal.jsx'
import PivotTable from './components/PivotTable.jsx'
import { OpenVisualizationModal, SaveVisualizationModal } from './components/SavedModals.jsx'
import {
  downloadChartPng, downloadCsv, downloadFilename, downloadSingleValuePng, downloadXlsx, pivotGrid,
} from './download.js'
import { buildPivot } from './pivot.js'
import { apiErrorMessage, catalogueItemLabels, makeLabelFor, unavailableMessage } from './savedVisualizations.js'
import {
  FIXED_DIMENSION_LABELS, TOTAL, VISUALIZATION_TYPES, axisLabels, buildQuery, configReducer, initialConfig,
  isChart, layoutProblem, placementError, starterConfig, totalSpecs,
} from './visualizationConfig.js'

/**
 * The Data Visualizer (DHIS2 style): pick Data, Periods, Stores and any
 * other dimension, lay them out as Columns / Rows / Filter, and draw them as
 * a pivot table or chart. Any number in the table can be broken down further.
 *
 * `storeId` is the active store (null for a firm-wide role); `openVizId`
 * opens a saved visualization (from a dashboard widget).
 */
export default function DataVisualizer({ storeId, openVizId }) {
  const [config, dispatch] = useReducer(configReducer, initialConfig)
  // The config the table on screen was produced from: layout edits don't
  // reshape the table until Update runs them.
  const [applied, setApplied] = useState(null)
  const [result, setResult] = useState({ data: null, loading: false, error: null })
  const [refreshKey, setRefreshKey] = useState(0)
  const [validationError, setValidationError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [modalDimId, setModalDimId] = useState(null)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [downloadOpen, setDownloadOpen] = useState(false)
  // The pivot cell being broken down: { cell, cellSummary, metric }.
  const [breakdown, setBreakdown] = useState(null)
  const canvasRef = useRef(null)
  // The saved visualization on screen (API object), and its config as saved,
  // serialised, to tell whether there are unsaved changes.
  const [saved, setSaved] = useState(null)
  const [savedSnapshot, setSavedSnapshot] = useState(null)
  // 'open' | 'saveAs' | 'rename' | 'delete'
  const [fileDialog, setFileDialog] = useState(null)
  const started = useRef(false)

  const catalogue = useApi(() => getAnalyticsDimensions(), [])
  const dimensions = useMemo(() => catalogue.data?.dimensions ?? [], [catalogue.data])
  const dimensionsById = useMemo(() => Object.fromEntries(dimensions.map((d) => [d.id, d])), [dimensions])
  const metricsById = useMemo(
    () => Object.fromEntries((dimensionsById.dx?.items ?? []).map((m) => [m.id, m])),
    [dimensionsById],
  )

  useEffect(() => {
    if (!applied) return undefined
    const controller = new AbortController()
    setResult((r) => ({ ...r, loading: true, error: null }))
    runAnalyticsQuery(new URLSearchParams(applied.params), { signal: controller.signal }).then(
      (data) => setResult({ data, loading: false, error: null }),
      (error) => { if (error?.name !== 'AbortError') setResult({ data: null, loading: false, error }) },
    )
    return () => controller.abort()
  }, [applied, refreshKey])

  useEffect(() => {
    if (!notice) return undefined
    const t = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(t)
  }, [notice])

  const dimensionLabel = useCallback(
    (id) => FIXED_DIMENSION_LABELS[id] ?? dimensionsById[id]?.label ?? id,
    [dimensionsById],
  )
  const itemLabels = useMemo(() => catalogueItemLabels(dimensions), [dimensions])
  const labelFor = useMemo(() => makeLabelFor(itemLabels, result.data), [itemLabels, result.data])

  const pivot = useMemo(() => {
    if (!result.data || !applied) return null
    return buildPivot(result.data, applied.config, config.options, labelFor)
  }, [result.data, applied, config.options, labelFor])

  // Grey out dimensions that don't apply to every chosen metric.
  const notApplicable = useCallback((dim) => {
    if (dim.kind !== 'dynamic') return null
    const missing = (config.items.dx ?? []).map((id) => metricsById[id]).filter((m) => m && !dim.applies_to.includes(m.source))
    return missing.length ? `Does not apply to: ${missing.map((m) => m.label).join(', ')}` : null
  }, [config.items.dx, metricsById])

  const appliedType = applied?.config.type
  const chartModel = useMemo(() => {
    if (!pivot || pivot.isEmpty || !isChart(appliedType)) return null
    return buildChartModel(pivot, appliedType, config.options)
  }, [pivot, appliedType, config.options])

  function run(cfg) {
    // The layout banner already explains what's wrong and offers the fix.
    if (layoutProblem(cfg, dimensionLabel)) return
    const { params, error } = buildQuery(cfg, dimensionsById)
    if (error) {
      setValidationError(error)
      return
    }
    setValidationError(null)
    const paramString = params.toString()
    if (applied?.params === paramString) setRefreshKey((k) => k + 1)
    setApplied({ config: cfg, params: paramString })
  }

  function load(cfg) {
    const next = configReducer(initialConfig, { type: 'LOAD', config: cfg })
    dispatch({ type: 'LOAD', config: next })
    run(next)
  }

  // First visit: open on this month's numbers rather than an empty screen.
  useEffect(() => {
    if (!catalogue.data || started.current || openVizId) return
    started.current = true
    const cfg = starterConfig(Object.keys(metricsById), storeId)
    dispatch({ type: 'LOAD', config: cfg })
    if (cfg.items.dx.length) run(cfg)
  // Runs once, when the catalogue first arrives.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalogue.data])

  // ── saved visualizations ──────────────────────────────────────────────────

  function showSaved(viz, cfg) {
    setSaved(viz)
    setSavedSnapshot(JSON.stringify(cfg))
  }

  function openSaved(viz) {
    const cfg = configReducer(initialConfig, { type: 'LOAD', config: viz.config })
    setFileDialog(null)
    showSaved(viz, cfg)
    dispatch({ type: 'LOAD', config: cfg })
    const problem = unavailableMessage(viz.unavailable)
    if (problem) {
      setApplied(null)
      setValidationError(`“${viz.name}” can't be drawn. ${problem}`)
      return
    }
    run(cfg)
  }

  // A dashboard widget's "open" link.
  useEffect(() => {
    if (!catalogue.data || !openVizId || String(saved?.id) === String(openVizId)) return undefined
    started.current = true
    let cancelled = false
    getVisualization(openVizId).then(
      (viz) => { if (!cancelled) openSaved(viz) },
      () => { if (!cancelled) setValidationError('That saved visualization could not be opened. It may have been deleted or unshared.') },
    )
    return () => { cancelled = true }
  // Reacts to the link only; openSaved is a fresh closure every render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalogue.data, openVizId])

  function startNew() {
    setSaved(null)
    setSavedSnapshot(null)
    setApplied(null)
    setResult({ data: null, loading: false, error: null })
    setValidationError(null)
    dispatch({ type: 'LOAD', config: { ...initialConfig, items: { ...initialConfig.items, ou: [storeId || 'FIRM'] } } })
  }

  async function saveCurrent() {
    try {
      const viz = await updateVisualization(saved.id, { config })
      showSaved({ ...viz, is_pinned: saved.is_pinned }, config)
      setNotice({ variant: 'valid', text: 'Saved.' })
    } catch (err) {
      setNotice({ variant: 'error', text: apiErrorMessage(err, 'The visualization could not be saved. Try again.') })
    }
  }

  // Save as / Rename throw a readable message for their dialog to show.
  async function saveAs(values) {
    try {
      const viz = await createVisualization({ ...values, config })
      setFileDialog(null)
      showSaved(viz, config)
      setNotice({ variant: 'valid', text: `Saved as “${viz.name}”.` })
    } catch (err) {
      throw new Error(apiErrorMessage(err, 'The visualization could not be saved. Try again.'), { cause: err })
    }
  }

  async function rename(values) {
    try {
      const viz = await updateVisualization(saved.id, values)
      setFileDialog(null)
      setSaved({ ...viz, is_pinned: saved.is_pinned })
    } catch (err) {
      throw new Error(apiErrorMessage(err, 'The visualization could not be renamed. Try again.'), { cause: err })
    }
  }

  async function removeSaved() {
    try {
      await deleteVisualization(saved.id)
      setFileDialog(null)
      setNotice({ variant: 'valid', text: `Deleted “${saved.name}”.` })
      startNew()
    } catch (err) {
      setNotice({ variant: 'error', text: apiErrorMessage(err, 'The visualization could not be deleted. Try again.') })
    }
  }

  async function togglePin() {
    const pinned = saved.is_pinned
    try {
      await (pinned ? unpinVisualization(saved.id) : pinVisualization(saved.id))
      setSaved({ ...saved, is_pinned: !pinned })
      setNotice({ variant: 'valid', text: pinned ? 'Removed from your dashboard.' : 'Pinned to your dashboard.' })
    } catch (err) {
      setNotice({ variant: 'error', text: apiErrorMessage(err, 'The dashboard could not be updated. Try again.') })
    }
  }

  function fileAction(action) {
    if (action === 'new') startNew()
    else if (action === 'save') {
      if (saved?.is_owner) saveCurrent()
      else setFileDialog('saveAs')
    } else if (action === 'pin') togglePin()
    else setFileDialog(action)
  }

  // ── layout ────────────────────────────────────────────────────────────────

  // Switching type redraws the current result straight away when the new type
  // can draw it from the same query.
  function changeType(visType) {
    const next = configReducer(config, { type: 'SET_TYPE', visType })
    dispatch({ type: 'SET_TYPE', visType })
    if (!applied || layoutProblem(next, dimensionLabel)) return
    const params = buildQuery(next, dimensionsById).params?.toString()
    if (params === applied.params) setApplied({ config: next, params })
    else if (params) run(next)
  }

  function place(dimId, axis, index) {
    const error = placementError(dimensionsById[dimId], axis)
    if (error) {
      setValidationError(error)
      return
    }
    dispatch({ type: 'MOVE_DIMENSION', dimId, axis, index })
  }

  function openDimension(dimId) {
    setDrawerOpen(false)
    setModalDimId(dimId)
  }

  function applyOptions(options) {
    const next = configReducer(config, { type: 'SET_OPTIONS', options })
    dispatch({ type: 'SET_OPTIONS', options })
    setOptionsOpen(false)
    // Totals change the query; everything else only redraws.
    if (!applied) return
    const rerun = { ...applied.config, options: next.options }
    if (JSON.stringify(totalSpecs(rerun)) !== JSON.stringify(totalSpecs(applied.config))) run(rerun)
  }

  // ── breakdown ─────────────────────────────────────────────────────────────

  const canDrill = useCallback((colCombo, rowCombo) => {
    if (!pivot || !applied) return false
    const cell = cellFilters(applied.params, pivot.cellItems(colCombo, rowCombo))
    return Boolean(cell && metricsById[cell.metric])
  }, [pivot, applied, metricsById])

  function openBreakdown(colCombo, rowCombo) {
    const items = pivot.cellItems(colCombo, rowCombo)
    const cell = cellFilters(applied.params, items)
    const describe = (id, list) => list.map((i) => labelFor(id, i)).join(', ')
    const cellSummary = [
      { label: dimensionLabel('dx'), value: labelFor('dx', cell.metric) },
      ...Object.entries(cell.filters).map(([id, list]) => ({
        label: dimensionLabel(id), value: items[id] === TOTAL ? `Total (${describe(id, list)})` : describe(id, list),
      })),
    ]
    setBreakdown({ cell, cellSummary, metric: metricsById[cell.metric] })
  }
  const closeBreakdown = useCallback(() => setBreakdown(null), [])

  // ── download ──────────────────────────────────────────────────────────────

  const filterSummary = applied?.config.filters
    .filter((id) => applied.config.items[id]?.length)
    .map((id) => `${dimensionLabel(id)}: ${applied.config.items[id].map((i) => labelFor(id, i)).join(', ')}`)
  const subtitle = filterSummary?.join(' · ')

  const canDownload = Boolean(pivot && !pivot.isEmpty && !result.error)
  const canDownloadPng = Boolean(canDownload && chartModel && !chartModel.tooMany)

  async function download(format) {
    setDownloadOpen(false)
    const filename = downloadFilename()
    try {
      if (format === 'png') {
        if (appliedType === 'SINGLE_VALUE') {
          await downloadSingleValuePng({
            name: chartModel.single.name, subtitle, text: chartModel.single.text,
            status: singleValueStatus(chartModel, config.options), filename,
          })
        } else if (canvasRef.current) {
          await downloadChartPng(canvasRef.current, {
            title: applied.config.items.dx.map((i) => labelFor('dx', i)).join(', '), subtitle, filename,
          })
        }
        return
      }
      const grid = pivotGrid(pivot, dimensionLabel)
      if (format === 'csv') downloadCsv(grid, filename)
      else downloadXlsx(grid, filename)
    } catch (err) {
      setNotice({ variant: 'error', text: err.message })
    }
  }

  // ── render ────────────────────────────────────────────────────────────────

  const dirty = Boolean(saved) && JSON.stringify(config) !== savedSnapshot
  const current = buildQuery(config, dimensionsById)
  const stale = applied && current.params
    && (current.params.toString() !== applied.params || config.type !== applied.config.type)
  const problem = layoutProblem(config, dimensionLabel)
  const modalDim = modalDimId && dimensionsById[modalDimId]
  const modalAxis = modalDim && ['columns', 'rows', 'filters'].find((a) => config[a].includes(modalDimId))
  const ready = Boolean(catalogue.data)

  if (catalogue.error) {
    return <NoticeBox variant="error">{apiErrorMessage(catalogue.error, 'Analytics could not be loaded. Try again.')}</NoticeBox>
  }

  const panel = ready
    ? <DimensionPanel dimensions={dimensions} config={config} dimensionLabel={dimensionLabel} notApplicable={notApplicable} onOpen={openDimension} />
    : <div className="viz-panel"><div className="viz-center"><div className="viz-spinner" /></div></div>

  let body
  if (!applied) {
    body = (
      <div className="viz-center">
        <Icon name="pivot-table" size={32} style={{ color: 'var(--blue-600)' }} />
        <h3>Build a visualization</h3>
        <p>Choose data, periods and stores from the dimensions, arrange them as Columns, Rows and Filter, then click Update.</p>
      </div>
    )
  } else if (result.loading && !pivot) {
    body = <div className="viz-center"><div className="viz-spinner" /></div>
  } else if (result.error) {
    body = (
      <div className="viz-center">
        <h3>The visualization could not be built</h3>
        <p>{apiErrorMessage(result.error, 'The analytics service could not be reached. Try again.')}</p>
        <Button size="small" onClick={() => setRefreshKey((k) => k + 1)}><Icon name="sync" size={16} /> Try again</Button>
      </div>
    )
  } else if (pivot?.isEmpty) {
    body = (
      <div className="viz-center">
        <h3>No data</h3>
        <p>Nothing was recorded for this selection. Try a longer period or other stores.</p>
      </div>
    )
  } else if (pivot) {
    body = (
      <>
        {subtitle && appliedType !== 'SINGLE_VALUE' && <p className="viz-subtitle">{subtitle}</p>}
        {chartModel ? (
          <ChartView model={chartModel} options={config.options} subtitle={subtitle} canvasRef={canvasRef}
            onSwapAxes={chartModel.tooMany ? () => load({ ...applied.config, columns: applied.config.rows, rows: applied.config.columns }) : undefined} />
        ) : (
          <PivotTable pivot={pivot} options={config.options} dimensionLabel={dimensionLabel} canDrill={canDrill} onDrill={openBreakdown} />
        )}
        {!chartModel && <p className="viz-footnote">Click any number to break it down by product, store, cashier, day and more.</p>}
      </>
    )
  }

  return (
    <div className="viz">
      <div className="viz-topbar">
        <span className="viz-only-narrow">
          <Button size="small" onClick={() => setDrawerOpen(true)}><Icon name="layers" size={16} /> Dimensions</Button>
        </span>
        <FileMenu saved={saved} canSave={ready} onAction={fileAction} />
        <Select value={config.type} onChange={(e) => changeType(e.target.value)} aria-label="Visualization type"
          options={VISUALIZATION_TYPES.map((t) => ({ value: t.id, label: t.label }))} />
        <div className="viz-title">
          {saved && (
            <>
              <span title={saved.description || undefined}>{saved.name}</span>
              {dirty && <span className="viz-muted">(unsaved changes)</span>}
              {saved.shared && <span className="viz-muted">· Shared</span>}
              {saved.is_pinned && <Icon name="pin" size={14} style={{ color: 'var(--muted)' }} />}
              {!saved.is_owner && <span className="viz-muted">by {saved.created_by_name}</span>}
            </>
          )}
        </div>
        {stale && <span className="viz-stale">Layout changed — click Update</span>}
        <Button size="small" onClick={() => setOptionsOpen(true)}><Icon name="sliders" size={16} /> Options</Button>
        <div className="viz-rel">
          <Button size="small" disabled={!canDownload} aria-haspopup="menu" aria-expanded={downloadOpen}
            onClick={() => setDownloadOpen((o) => !o)}>
            <Icon name="download" size={16} /> Download
          </Button>
          {downloadOpen && (
            <>
              <div className="viz-scrim" onClick={() => setDownloadOpen(false)} />
              <div className="viz-popover right">
                <Menu>
                  <div className="viz-menu-heading">Table</div>
                  <MenuItem label="Excel (.xlsx)" onClick={() => download('xlsx')} />
                  <MenuItem label="CSV (.csv)" onClick={() => download('csv')} />
                  <div className="viz-menu-heading">Chart</div>
                  <MenuItem label={canDownloadPng ? 'Image (.png)' : 'Image (.png) — switch to a chart'} disabled={!canDownloadPng}
                    onClick={() => download('png')} />
                </Menu>
              </div>
            </>
          )}
        </div>
        <Button size="small" variant="primary" disabled={!ready} onClick={() => run(config)}>
          <Icon name="sync" size={16} /> Update
        </Button>
      </div>

      <div className="viz-body">
        {panel}
        <div className="viz-main">
          <LayoutArea config={config} dimensionsById={dimensionsById} dimensionLabel={dimensionLabel}
            onOpen={openDimension} onPlace={place} onRemove={(dimId) => dispatch({ type: 'REMOVE_DIMENSION', dimId })} />

          {notice && <NoticeBox variant={notice.variant}>{notice.text}</NoticeBox>}
          {problem && (
            <NoticeBox variant="warning" action={<Button size="small" onClick={() => load(problem.fixed)}><Icon name="wand" size={16} /> Fix layout</Button>}>
              {problem.message} Fix layout will {problem.fixDescription}.
            </NoticeBox>
          )}
          {validationError && (
            <NoticeBox variant="error" action={<button type="button" className="ds-icon-btn" aria-label="Dismiss" onClick={() => setValidationError(null)}><Icon name="cross" size={16} /></button>}>
              {validationError}
            </NoticeBox>
          )}

          <section className={`viz-canvas${result.loading && pivot ? ' busy' : ''}`} aria-busy={result.loading}>{body}</section>
        </div>
      </div>

      {drawerOpen && (
        <>
          <div className="viz-drawer-backdrop" onClick={() => setDrawerOpen(false)} />
          <aside className="viz-drawer left" aria-label="Dimensions">
            <div className="viz-drawer-head">
              <h2>Dimensions</h2>
              <button type="button" className="ds-icon-btn" onClick={() => setDrawerOpen(false)} aria-label="Close"><Icon name="cross" size={18} /></button>
            </div>
            <div className="viz-drawer-body">{panel}</div>
          </aside>
        </>
      )}

      {modalDim && (
        <DimensionModal
          key={modalDim.id}
          dim={modalDim}
          title={dimensionLabel(modalDim.id)}
          groups={catalogue.data?.groups ?? []}
          selected={config.items[modalDim.id] ?? []}
          axis={modalAxis}
          axisNames={axisLabels(config.type)}
          labelFor={labelFor}
          onClose={() => setModalDimId(null)}
          onApply={(items, andRun) => {
            const action = { type: 'SET_ITEMS', dimId: modalDim.id, items }
            dispatch(action)
            setModalDimId(null)
            if (andRun) run(configReducer(config, action))
          }}
          onAddTo={(axis, items) => {
            dispatch({ type: 'SET_ITEMS', dimId: modalDim.id, items })
            dispatch({ type: 'MOVE_DIMENSION', dimId: modalDim.id, axis })
            setModalDimId(null)
          }}
        />
      )}

      {fileDialog === 'open' && <OpenVisualizationModal currentId={saved?.id} onOpen={openSaved} onClose={() => setFileDialog(null)} />}
      {fileDialog === 'saveAs' && (
        <SaveVisualizationModal
          title={saved ? 'Save as' : 'Save visualization'}
          submitLabel="Save"
          initial={saved ? { name: `${saved.name} (copy)`, description: saved.description } : null}
          onSubmit={saveAs}
          onClose={() => setFileDialog(null)}
        />
      )}
      {fileDialog === 'rename' && saved && (
        <SaveVisualizationModal title="Rename visualization" submitLabel="Rename" initial={saved} onSubmit={rename} onClose={() => setFileDialog(null)} />
      )}
      {fileDialog === 'delete' && saved && (
        <Modal title="Delete visualization" size="sm" onClose={() => setFileDialog(null)}
          footer={<><Button onClick={() => setFileDialog(null)}>Cancel</Button><Button variant="destructive" onClick={removeSaved}>Delete</Button></>}>
          <p style={{ margin: 0, fontSize: 14 }}>
            Delete “{saved.name}”?
            {saved.shared ? ' It is shared, so your colleagues lose it too, including any dashboard pins.' : ''}
            {' '}This cannot be undone.
          </p>
        </Modal>
      )}

      {breakdown && (
        <BreakdownPanel cell={breakdown.cell} cellSummary={breakdown.cellSummary} metric={breakdown.metric}
          dimensionsById={dimensionsById} dimensionLabel={dimensionLabel} itemLabels={itemLabels} options={config.options}
          onOpenAsTable={(cfg) => { setBreakdown(null); load(cfg) }} onClose={closeBreakdown} />
      )}

      {optionsOpen && <OptionsModal type={config.type} options={config.options} onClose={() => setOptionsOpen(false)} onApply={applyOptions} />}
    </div>
  )
}
