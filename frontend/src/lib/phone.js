// User mobile numbers are typed in local form — 10 digits, 0712345678 —
// while the API stores them as 255712345678 for the SMS gateway.
export const PHONE_DIGITS = 10

export function phoneInput(value) {
  return (value || '').replace(/\D/g, '').slice(0, PHONE_DIGITS)
}

export function localPhone(stored) {
  const digits = (stored || '').replace(/\D/g, '')
  return digits.length === 12 && digits.startsWith('255') ? `0${digits.slice(3)}` : digits
}
