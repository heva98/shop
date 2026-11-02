import { client } from './client.js'

// The owner's SMS: settings, editable texts, preview/send and the delivery log.
export const getSmsConfig = () => client.get('/api/notifications/sms/config/')
export const updateSmsConfig = (data) => client.patch('/api/notifications/sms/config/', data)
export const listSmsTemplates = (params) => client.get('/api/notifications/sms/templates/', params)
export const updateSmsTemplate = (id, data) => client.patch(`/api/notifications/sms/templates/${id}/`, data)
export const previewSms = (data) => client.post('/api/notifications/sms/preview/', data)
export const sendSms = (data) => client.post('/api/notifications/sms/send/', data)
export const listSmsBatches = (params) => client.get('/api/notifications/sms/batches/', params)
export const getSmsBatch = (id) => client.get(`/api/notifications/sms/batches/${id}/`)
export const resendFailedSms = (id) => client.post(`/api/notifications/sms/batches/${id}/resend-failed/`)
