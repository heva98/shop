// A small till snapshot for tests: what GET /api/pos/till/ returns.
// Sugar sells by the piece or by the bale of 10; milk expires; salt has no
// price yet; the antibiotic needs a prescription.

// Ids end in different digits, so each product has its own sync bucket.
export const SUGAR = 'a1000001-0000-4000-8000-000000000001'
export const MILK = 'b2000002-0000-4000-8000-000000000002'
export const SALT = 'c3000003-0000-4000-8000-000000000003'
export const AMOX = 'd4000004-0000-4000-8000-000000000004'
export const PIECE = 'u1'
export const BALE = 'u2'

const product = (id, name, extra = {}) => ({
  id, name, short_name: '', brand: '', size: '', barcode: '', category_name: '', uom: PIECE,
  vat_class: 'standard', tracks_expiry: false, generic_name: '', prescription_only: false, controlled: false, ...extra,
})

export function snapshot(overrides = {}) {
  return {
    store: 's1',
    cashier_discount_limit: '10',
    products: [
      product(SUGAR, 'Sugar 1kg', { brand: 'Kilombero', barcode: '6201234567890' }),
      product(MILK, 'Fresh milk 500ml', { tracks_expiry: true, vat_class: 'exempt' }),
      product(SALT, 'Salt 1kg'),
      product(AMOX, 'Amoxicillin 250mg', { generic_name: 'Amoxicillin', prescription_only: true }),
    ],
    units: [
      { id: PIECE, name: 'Piece', unit_value: '1' },
      { id: BALE, name: 'Bale of 10', unit_value: '10' },
    ],
    prices: [
      { product: SUGAR, uom: null, unit_price: '3200.00', regular_price: '3200.00', promotion: null },
      { product: SUGAR, uom: BALE, unit_price: '30000.00', regular_price: '30000.00', promotion: null },
      { product: MILK, uom: null, unit_price: '1500.00', regular_price: '1800.00', promotion: 'Milk week' },
      { product: AMOX, uom: null, unit_price: '500.00', regular_price: '500.00', promotion: null },
    ],
    stock: [
      { product: SUGAR, qty_on_hand: '25.00', expiry_date: null },
      { product: MILK, qty_on_hand: '4.00', expiry_date: '2000-01-01' },
      { product: MILK, qty_on_hand: '6.00', expiry_date: '2999-12-31' },
      { product: AMOX, qty_on_hand: '100.00', expiry_date: null },
    ],
    ...overrides,
  }
}
