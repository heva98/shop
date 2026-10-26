import { client } from './client.js'

export const getDashboard = (params) => client.get('/api/reports/dashboard/', params)
export const getSalesReport = (params) => client.get('/api/reports/sales/', params)
export const getSalesTrend = (params) => client.get('/api/reports/sales-trend/', params)
export const getShiftsReport = (params) => client.get('/api/reports/shifts/', params)
export const getStockReport = (params) => client.get('/api/reports/stock/', params)
export const getExpiryReport = (params) => client.get('/api/reports/expiry/', params)
export const getPurchasesReport = (params) => client.get('/api/reports/purchases/', params)
export const getLossesReport = (params) => client.get('/api/reports/losses/', params)
export const getTransfersReport = (params) => client.get('/api/reports/transfers/', params)
