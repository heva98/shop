import { listAll } from './client.js'

// Pharmacies: the controlled drugs register (backend controlled_substances).
export const listAllControlledEntries = (params) => listAll('/api/controlled-substances/entries/', params)
