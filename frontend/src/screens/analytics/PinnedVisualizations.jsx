import { useMemo, useState } from 'react'
import { Card, Icon } from '../../components/ds/index.js'
import { getAnalyticsDimensions, listVisualizations, runAnalyticsQuery, unpinVisualization } from '../../api/analytics.js'
import { useApi } from '../../hooks/useApi.js'
import { buildChartModel } from './charts.js'
import ChartView from './components/ChartView.jsx'
import PivotTable from './components/PivotTable.jsx'
import { buildPivot } from './pivot.js'
import { catalogueItemLabels, makeLabelFor, unavailableMessage } from './savedVisualizations.js'
import {
  FIXED_DIMENSION_LABELS, buildQuery, configReducer, initialConfig, isChart, layoutProblem,
} from './visualizationConfig.js'
import { t, useLanguage, useT } from '../../i18n/index.js'

function Placeholder({ title, message }) {
  return (
    <div className="viz-placeholder">
      <strong>{title}</strong>
      {message && <span>{message}</span>}
    </div>
  )
}

function WidgetBody({ viz, catalogue }) {
  useT()
  const lang = useLanguage()
  const config = useMemo(() => configReducer(initialConfig, { type: 'LOAD', config: viz.config }), [viz.config])
  const problem = unavailableMessage(viz.unavailable)
  const dimensions = catalogue?.dimensions
  const dimensionsById = useMemo(() => Object.fromEntries((dimensions ?? []).map((d) => [d.id, d])), [dimensions])
  const dimensionLabel = (id) => FIXED_DIMENSION_LABELS[id] ?? t(dimensionsById[id]?.label) ?? id

  const query = catalogue && !problem ? buildQuery(config, dimensionsById) : null
  const layoutIssue = catalogue && !problem ? layoutProblem(config, dimensionLabel) : null
  const params = !layoutIssue ? query?.params?.toString() : null
  const result = useApi(() => (params ? runAnalyticsQuery(new URLSearchParams(params)) : null), [params])

  const itemLabels = useMemo(() => catalogueItemLabels(dimensions), [dimensions])
  const pivot = useMemo(() => {
    if (!result.data) return null
    return buildPivot(result.data, config, config.options, makeLabelFor(itemLabels, result.data))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.data, config, itemLabels, lang])
  const chartModel = useMemo(() => {
    if (!pivot || pivot.isEmpty || !isChart(config.type)) return null
    return buildChartModel(pivot, config.type, config.options)
  }, [pivot, config])

  if (problem) return <Placeholder title={t('Not available')} message={problem} />
  if (result.error) return <Placeholder title={t('Could not load this visualization')} message="Open it in Analytics to see what went wrong." />
  if (query?.error || layoutIssue) return <Placeholder title={t('Needs attention')} message={query?.error ?? layoutIssue.message} />
  if (!pivot) return <div className="viz-placeholder"><div className="viz-spinner" /></div>
  if (pivot.isEmpty) return <Placeholder title={t('No data')} message="Nothing was recorded for this selection yet." />
  if (chartModel) {
    if (chartModel.tooMany) return <Placeholder title={t('Too many series to draw here')} message="Open it in Analytics to view it as a table." />
    return <ChartView model={chartModel} options={config.options} />
  }
  return <div style={{ maxHeight: 320, overflow: 'auto' }}><PivotTable pivot={pivot} options={config.options} dimensionLabel={dimensionLabel} /></div>
}

/**
 * The saved visualizations the user pinned, drawn as dashboard widgets.
 * Renders nothing when nothing is pinned; `onOpen(id)` opens one in Analytics.
 */
export default function PinnedVisualizations({ onOpen }) {
  useT()
  const pinned = useApi(() => listVisualizations({ pinned: 'true' }), [])
  const [unpinned, setUnpinned] = useState([])
  const list = (pinned.data ?? []).filter((v) => !unpinned.includes(v.id))
  const catalogue = useApi(() => (list.length ? getAnalyticsDimensions() : null), [list.length > 0])

  async function unpin(viz) {
    try {
      await unpinVisualization(viz.id)
      setUnpinned((ids) => [...ids, viz.id])
    } catch {
      // The widget simply stays; the next visit shows the real state.
    }
  }

  if (!list.length) return null
  return (
    <section aria-label={t('Pinned visualizations')} className="viz-pins">
      {list.map((viz) => (
        <Card key={viz.id} title={viz.name} meta={viz.description || undefined}
          action={(
            <div style={{ display: 'flex', gap: 4 }}>
              <button type="button" className="ds-icon-btn" title={t('Open in Analytics')} aria-label={t('Open {name} in Analytics', { name: viz.name })} onClick={() => onOpen(viz.id)}>
                <Icon name="launch" size={16} />
              </button>
              <button type="button" className="ds-icon-btn" title={t('Unpin from dashboard')} aria-label={t('Unpin {name}', { name: viz.name })} onClick={() => unpin(viz)}>
                <Icon name="pin-off" size={16} />
              </button>
            </div>
          )}>
          {catalogue.data ? <WidgetBody viz={viz} catalogue={catalogue.data} /> : <div className="viz-placeholder"><div className="viz-spinner" /></div>}
        </Card>
      ))}
    </section>
  )
}
