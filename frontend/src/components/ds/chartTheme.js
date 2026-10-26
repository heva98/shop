import { Chart } from 'chart.js/auto'

export { Chart }

// Chart.js theme from DESIGN.md › Charts (drop-in), applied once.
export const chartColors = ['#0B5ED7', '#F59E0B', '#6E5BD0', '#22A45D', '#E5484D']
Chart.defaults.font.family = 'Poppins, system-ui, sans-serif'
Chart.defaults.font.size = 12
Chart.defaults.color = '#5B6472'
Chart.defaults.borderColor = '#EEF1F5'
Chart.defaults.maintainAspectRatio = false
Chart.defaults.plugins.legend.position = 'bottom'
Chart.defaults.plugins.legend.labels.usePointStyle = true
Chart.defaults.plugins.legend.labels.pointStyle = 'circle'
Chart.defaults.plugins.legend.labels.boxWidth = 8
Chart.defaults.plugins.legend.labels.padding = 16
Object.assign(Chart.defaults.plugins.tooltip, {
  backgroundColor: '#1B2333', padding: 10, cornerRadius: 8, boxPadding: 4,
  titleFont: { weight: '600' }, usePointStyle: true,
})
Object.assign(Chart.defaults.elements.line, { borderWidth: 2, tension: 0.4 })
Object.assign(Chart.defaults.elements.point, {
  radius: 3, hoverRadius: 6, borderWidth: 2, borderColor: '#FFFFFF',
})
Object.assign(Chart.defaults.elements.bar, {
  borderRadius: { topLeft: 6, topRight: 6 }, borderSkipped: 'bottom', maxBarThickness: 36,
})
Object.assign(Chart.defaults.elements.arc, { borderWidth: 2, borderColor: '#FFFFFF' })

/** Abbreviated money tick: TZS 1.2M / TZS 840K. */
export function moneyTick(v) {
  const n = Number(v)
  if (Math.abs(n) >= 1e6) return `TZS ${(n / 1e6).toFixed(1).replace(/\.0$/, '')}M`
  if (Math.abs(n) >= 1e3) return `TZS ${(n / 1e3).toFixed(0)}K`
  return `TZS ${n}`
}
