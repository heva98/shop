import { client } from './client.js'

// The public pages behind the sign-in screen (backend core/signup.py):
// no session needed. signup() and resetPassword() answer with a token.
export const requestSignupCode = (phone) => client.post('/api/signup/code/', { phone })
export const signup = (data) => client.post('/api/signup/', data)
export const requestResetCode = (username) => client.post('/api/password-reset/code/', { username })
export const resetPassword = (data) => client.post('/api/password-reset/', data)
