/** Small helpers shared by the till screens. */

// cashiers type amounts like "10,000" or "10 000"; parseFloat alone would stop at the separator
export const parseAmount = (v) => parseFloat(String(v).replace(/[,\s]/g, '')) || 0

export const offlineNo = (sale) => sale.id.slice(0, 8).toUpperCase()

export function thStyle(align, width) {
  return { width, textAlign: align, fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: align === 'center' ? '12px 8px' : '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
export function tdStyle(align, wide) {
  return { padding: wide ? '14px 16px' : '14px 8px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'center', fontSize: 14, color: 'var(--fg-subtle)' }
}
export const stepBtnStyle = { width: 24, height: 24, borderRadius: 'var(--radius-sm)', border: '1px solid var(--grey-500)', background: 'var(--white)', cursor: 'pointer', fontSize: 14, lineHeight: 1 }
export const removeBtnStyle = { width: 24, height: 24, borderRadius: 'var(--radius-sm)', border: 0, background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fill: 'var(--status-error)', color: 'var(--status-error)' }
export const summaryRowStyle = { display: 'flex', justifyContent: 'space-between', fontSize: 14, color: 'var(--grey-700)', padding: '4px 0' }
