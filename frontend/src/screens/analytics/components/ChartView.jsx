import { memo, useEffect, useMemo, useRef } from 'react'
import { Button, Icon } from '../../../components/ds/index.js'
import { Chart } from '../../../components/ds/chartTheme.js'
import { MAX_SERIES, singleValueStatus, tickFormatter } from '../charts.js'
import { formatValue } from '../pivot.js'

const INK = '#1B2333'
const SURFACE = '#FFFFFF'

// A dashed line across the value axis at the target, with its label.
const targetLine = {
  id: 'vizTarget',
  afterDatasetsDraw(chart, _args, opts) {
    if (opts?.value === null || opts?.value === undefined) return
    const horizontal = chart.options.indexAxis === 'y'
    const scale = chart.scales[horizontal ? 'x' : 'y']
    if (!scale) return
    const at = scale.getPixelForValue(opts.value)
    const { left, right, top, bottom } = chart.chartArea
    const { ctx } = chart
    ctx.save()
    ctx.strokeStyle = INK
    ctx.lineWidth = 1.5
    ctx.setLineDash([6, 4])
    ctx.beginPath()
    if (horizontal) { ctx.moveTo(at, top); ctx.lineTo(at, bottom) } else { ctx.moveTo(left, at); ctx.lineTo(right, at) }
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = INK
    ctx.font = '600 12px Poppins, system-ui, sans-serif'
    ctx.textAlign = 'right'
    ctx.textBaseline = 'bottom'
    if (horizontal) ctx.fillText(opts.text, at - 4, top + 14)
    else ctx.fillText(opts.text, right, at - 4)
    ctx.restore()
  },
}

// Values written at the end of each bar / above each point (stacked: inside).
const dataLabels = {
  id: 'vizLabels',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts?.show) return
    const { ctx } = chart
    const horizontal = chart.options.indexAxis === 'y'
    const stacked = Boolean(chart.options.scales?.x?.stacked)
    ctx.save()
    ctx.font = '11px Poppins, system-ui, sans-serif'
    chart.data.datasets.forEach((ds, i) => {
      const meta = chart.getDatasetMeta(i)
      if (meta.hidden) return
      meta.data.forEach((el, j) => {
        const text = ds.labels?.[j]
        if (!text || ds.data[j] === null) return
        const { x, y } = el.tooltipPosition()
        ctx.fillStyle = stacked ? SURFACE : INK
        if (stacked) {
          const mid = el.getCenterPoint()
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(text, mid.x, mid.y)
        } else if (horizontal) {
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(text, x + 4, y)
        } else {
          ctx.textAlign = 'center'
          ctx.textBaseline = 'bottom'
          ctx.fillText(text, x, y - 4)
        }
      })
    })
    ctx.restore()
  },
}

function targetOption(options, unit) {
  if (options.targetValue === null || options.targetValue === undefined) return { value: null }
  return {
    value: options.targetValue,
    text: `${options.targetLabel || 'Target'} ${formatValue(options.targetValue, unit ?? 'count', options.decimals)}`,
  }
}

function chartConfig(model, options) {
  const { type, series, data, unit } = model
  const legend = { display: type === 'PIE' || series.filter((s) => s.name).length >= 2 }

  if (type === 'PIE') {
    return {
      type: 'pie',
      data: {
        labels: data.map((s) => s.name),
        datasets: [{
          data: data.map((s) => s.value),
          backgroundColor: data.map((s) => s.color),
          labels: data.map((s) => s.label),
        }],
      },
      options: {
        animation: false,
        plugins: {
          legend,
          tooltip: { callbacks: { label: (c) => ` ${c.label}: ${data[c.dataIndex].label}` } },
          vizLabels: { show: false },
        },
      },
    }
  }

  const horizontal = type === 'BAR'
  const stacked = type === 'STACKED_COLUMN'
  const ticks = tickFormatter(unit)
  const last = series.length - 1
  const valueAxis = {
    beginAtZero: true, stacked, border: { display: false },
    ticks: { callback: (v) => ticks(v), maxTicksLimit: 6 },
  }
  const categoryAxis = {
    stacked, grid: { display: false },
    ticks: {
      autoSkip: false, maxRotation: horizontal ? 0 : 40,
      callback(v) {
        const l = this.getLabelForValue(v)
        return l.length > 26 ? `${l.slice(0, 25)}…` : l
      },
    },
  }

  return {
    type: type === 'LINE' ? 'line' : 'bar',
    data: {
      labels: data.map((r) => r.category),
      datasets: series.map((s, i) => ({
        label: s.name ?? '',
        data: data.map((r) => r[s.key]),
        labels: data.map((r) => r[`${s.key}__label`]),
        backgroundColor: s.color,
        borderColor: type === 'LINE' ? s.color : SURFACE,
        pointBackgroundColor: s.color,
        ...(type === 'LINE'
          ? { fill: false, tension: 0, pointRadius: 4, pointHoverRadius: 6, spanGaps: false }
          : {
            maxBarThickness: 48,
            // Only a bar's outer end is rounded; stacked segments meet flush,
            // split by a 2px surface gap.
            borderWidth: stacked ? { top: 2 } : 0,
            borderRadius: !stacked || i === last ? 4 : 0,
            borderSkipped: 'start',
          }),
      })),
    },
    options: {
      animation: false,
      indexAxis: horizontal ? 'y' : 'x',
      interaction: { mode: 'index', intersect: false },
      layout: { padding: { top: options.showDataLabels ? 18 : 6, right: horizontal ? 48 : 8 } },
      scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
      plugins: {
        legend,
        tooltip: {
          callbacks: {
            label: (c) => {
              const text = c.dataset.labels[c.dataIndex] || '–'
              return c.dataset.label ? ` ${c.dataset.label}: ${text}` : ` ${text}`
            },
          },
        },
        vizTarget: targetOption(options, unit),
        vizLabels: { show: options.showDataLabels },
      },
    },
    plugins: [targetLine, dataLabels],
  }
}

function CanvasChart({ model, options, canvasRef }) {
  const ref = useRef(null)
  const config = useMemo(() => chartConfig(model, options), [model, options])
  useEffect(() => {
    const chart = new Chart(ref.current, config)
    if (canvasRef) canvasRef.current = ref.current
    return () => chart.destroy()
  }, [config, canvasRef])

  const horizontal = model.type === 'BAR'
  const height = horizontal ? Math.max(320, model.data.length * (model.series.length * 14 + 18) + 80) : 400
  return (
    <div style={{ position: 'relative', height }}>
      <canvas ref={ref} role="img" aria-label="Chart of the table's values; switch to Pivot table to read them" />
    </div>
  )
}

function SingleValue({ model, options, subtitle }) {
  const { name, text } = model.single
  const status = singleValueStatus(model, options)
  return (
    <div className="viz-single">
      <span className="viz-single-name">{name}</span>
      {subtitle && <span className="viz-muted">{subtitle}</span>}
      <span className="viz-single-value">{text || '–'}</span>
      {status && <span className="viz-single-status" style={{ color: status.color }}>{status.text}</span>}
    </div>
  )
}

/**
 * Draws a chart model (see charts.js). `canvasRef` receives the chart's
 * <canvas>, so the PNG download can copy it.
 */
export default memo(function ChartView({ model, options, subtitle, canvasRef, onSwapAxes }) {
  if (model.tooMany) {
    const canSwap = model.type !== 'PIE' && model.data.length <= MAX_SERIES && onSwapAxes
    return (
      <div className="viz-center">
        <h3>Too many {model.type === 'PIE' ? 'slices' : 'series'} to tell apart</h3>
        <p>
          This chart would need {model.tooMany} colours; charts show at most {MAX_SERIES}. Choose fewer items
          {canSwap ? ', or swap Series and Category' : ''}, or view it as a pivot table.
        </p>
        {canSwap && (
          <Button size="small" onClick={onSwapAxes}><Icon name="transfer" size={16} /> Swap Series and Category</Button>
        )}
      </div>
    )
  }
  if (model.type === 'SINGLE_VALUE') return <SingleValue model={model} options={options} subtitle={subtitle} />
  return <CanvasChart model={model} options={options} canvasRef={canvasRef} />
})
