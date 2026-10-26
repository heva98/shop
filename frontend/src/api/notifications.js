import { client } from './client.js'

export const listNotificationLogs = (params) => client.get('/api/notifications/logs/', params)
