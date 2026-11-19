import { client } from './client.js'

export const getDashboard = (params) => client.get('/api/reports/dashboard/', params)
/** Totals for the period, and one page of its sales (`page`, `page_size`; 0 for totals only). */
export const getSalesReport = (params) => client.get('/api/reports/sales/', params)
/** Every sale of the period, a page at a time, for a download or a printout. */
export async function getAllSalesRows(params) {
  const rows = []
  for (let page = 1; ; page++) {
    const data = await client.get('/api/reports/sales/', { ...params, page, page_size: 1000 })
    for (const row of data.sales) rows.push(row)
    if (page >= data.sales_page.num_pages) return rows
  }
}
export const getSalesTrend = (params) => client.get('/api/reports/sales-trend/', params)
export const getShiftsReport = (params) => client.get('/api/reports/shifts/', params)
export const getStockReport = (params) => client.get('/api/reports/stock/', params)
export const getExpiryReport = (params) => client.get('/api/reports/expiry/', params)
export const getPurchasesReport = (params) => client.get('/api/reports/purchases/', params)
export const getLossesReport = (params) => client.get('/api/reports/losses/', params)
export const getTransfersReport = (params) => client.get('/api/reports/transfers/', params)
export const getSummary = (params) => client.get('/api/reports/summary/', params)
