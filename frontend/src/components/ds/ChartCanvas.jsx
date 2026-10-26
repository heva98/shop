import { useEffect, useRef } from 'react'
import { Chart } from './chartTheme.js'

/** Thin wrapper: rebuilds the chart when `config` changes. `label` is the
 * accessible name of the canvas. */
export default function ChartCanvas({ config, height = 280, label }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current) return undefined
    const chart = new Chart(ref.current, config)
    return () => chart.destroy()
  }, [config])
  return (
    <div style={{ position: 'relative', height }}>
      <canvas ref={ref} role="img" aria-label={label} />
    </div>
  )
}
