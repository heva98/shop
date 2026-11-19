# Design-system components (`components/ds`)

The shared UI kit for every screen. Visual rules live in
[`design-system/DESIGN.md`](../../../../design-system/DESIGN.md); this file covers
the **code**: what's here, how the pieces fit together, and the API of each.

```js
import { Button, DataTable, AsyncContent, Field, Input } from '../components/ds/index.js'
```

Always import from `index.js`, never from a component file directly. That keeps
the public surface in one place.

## Architecture

```
tokens.css            CSS variables + every .ds-* class. Components carry no colours of their own.
   │
primitives            Icon · Spinner · Skeleton · Tag · Chip
   │
controls              Button · Input · Select · Checkbox · Radio · Switch
   │                    └─ read FieldContext (fieldContext.js) for aria wiring
composites            Field · Card · NoticeBox · EmptyState · Modal · Menu · StatCard
   │
data views            AsyncContent · DataTable   ← own the loading / error / empty states
   │                    └─ dataTable.js: pure sort helpers (unit-tested, no JSX)
shell                 HeaderBar · Sidebar · MobileNav · SubNav · PageHeader
```

Rules the layers follow:

1. **Styling is CSS classes on tokens.** A component adds a `.ds-*` class, and
   `tokens.css` decides how it looks. Use `style` for one-off layout (margins,
   widths), never for colour or type.
2. **Native props pass through.** `Button`, `Input` and `Select` spread the rest
   of their props onto the real element, so `name`, `autoComplete`, `min/max`,
   `aria-*`, `form` and `ref` all work without the component knowing about them.
3. **Strings go through `t()`.** Every text a component renders by default is
   English in the code with a Swahili entry in `i18n/sw.js`. Add both, or the
   Swahili UI falls back to English.
4. **Logic that can be pure is pure.** Anything testable without a DOM goes in
   a `.js` file next to the component, with a `*.test.js` beside it (`npm test`).

## State handling: the one pattern

Every server-backed view has the same four states. `AsyncContent` and
`DataTable` implement them once, so screens don't each write their own:

| State | What the user sees | Notes |
|---|---|---|
| **Loading, nothing yet** | Skeleton shaped like the content | Shown only after 200 ms (`delay`), so fast replies don't flash. Container has `aria-busy` and a hidden "Loading…" status. |
| **Refreshing, data shown** | The old data, slightly faded | Never blank a screen the user is reading. `aria-busy` while it refreshes. |
| **Error, nothing to show** | Red notice with the server's message and **Try again** | Message comes from `apiErrorText`; network failures already read "No connection to the server." |
| **Error, data shown** | Data stays, notice above it | E.g. "Load more" failed. Don't throw away rows the user already has. |
| **Empty** | `EmptyState` with an action that fills it | An empty screen should say what to do next (see the shop-usability goals). |

## Components

### `DataTable`

```jsx
const columns = [
  { key: 'name', header: t('Product'), primary: true, sortable: true },
  { key: 'stock', header: t('In stock'), align: 'end', sortable: true, firstDirection: 'desc' },
  { key: 'price', header: t('Price'), align: 'end', sortable: true,
    sortValue: (p) => Number(p.price), cell: (p) => formatMoney(p.price) },
  { key: 'supplier', header: t('Supplier'), hideOnMobile: true },
  { key: 'actions', header: t('Actions'), label: '', cell: (p) => <Button size="small">{t('Edit')}</Button> },
]

const { data, loading, error, refetch } = useApi(() => listProducts(), [])

<DataTable
  caption={t('Products')}
  columns={columns}
  rows={data}
  loading={loading}
  error={error}
  onRetry={refetch}
  empty={<EmptyState icon="stock" title={t('No products yet')} action={<Button variant="primary">{t('Add product')}</Button>} />}
/>
```

| Prop | Type | Default | |
|---|---|---|---|
| `columns` | `Column[]` | required | See below. Build them with `.filter(Boolean)` so a column can be conditional, and spans stay right. |
| `rows` | `object[] \| null` | | `null` while loading is fine. |
| `rowKey` | `string \| (row, i) => key` | `'id'` | |
| `caption` | `string` | | **Always set it.** It names the table for screen readers (hidden unless `showCaption`). |
| `loading`, `error`, `onRetry` | | | Straight from `useApi`. |
| `errorTitle` | `string` | "Could not load this." | |
| `empty` | `node \| string` | generic "Nothing to show yet." | Pass a real `EmptyState` with an action. A plain string shows as muted centred text. |
| `defaultSort` | `{key, direction}` | `null` | Uncontrolled client-side sort. |
| `sort` + `onSortChange` | | | Controlled sort. Add `manualSort` when the **server** sorts (paged lists), so rows are shown as given. |
| `layout` | `'cards' \| 'scroll'` | `'cards'` | How phones (≤640px) show it: labelled cards, or a sideways-scrolling table for wide numeric grids. |
| `minWidth` | `number` | | Desktop: below this the card scrolls sideways (and becomes keyboard-focusable). |
| `footer` | `node` | | Under the card, e.g. a **Load more** button. |
| `skeletonRows` | `number` | `5` | Match the usual page size so the layout doesn't jump. |
| `rowClassName` | `(row) => string` | | |
| `renderDetail` | `(row, i) => node \| null` | | A full-width row under that row: an inline form, a statement, a row's batches. Return `null` to show none. The button that opens it should carry `aria-expanded`. |
| `density` | `'comfortable' \| 'compact'` | `'comfortable'` | `compact` is 13px with tighter padding and top-aligned cells, for dense, multi-line grids (logs, reports, transfers). |

**Column:** `key` (unique), `header` (node), `label` (plain text for the phone
card and sort menu; defaults to `header` if it's a string; `''` hides it),
`cell(row, i)` (defaults to `row[key]`, with `—` for blanks), `sortable`,
`sortValue(row)`, `firstDirection` (`'desc'` for numbers and dates people want
biggest or newest first), `align` (`'end'` for numbers, which also gets
tabular figures), `primary` (bold first column, card title on phones),
`hideOnMobile`, `width`, `className`.

Sorting is locale-aware and natural ("Item 2" before "Item 10"), stable, and
keeps blanks last in both directions. Headers get `aria-sort`. On phones the
header row is hidden, so a **Sort by** select replaces it.

### Settings `Table` (simple lists)

`screens/settings/FormParts.jsx` exports `Table`, a thin wrapper around
DataTable for lists that are just headers plus rows of cells. Most settings
panels and the stock-control screens use it:

```jsx
<Table
  caption={t('Suppliers')}
  headers={['Name', 'Phone', '']}
  rows={(suppliers ?? []).map((s) => [s.name, s.phone, <Button key="edit" size="small">{t('Edit')}</Button>])}
  loading={loading} error={error} onRetry={refetch}
  empty={t('No suppliers yet.')}
/>
```

Headers are translated for you, and a blank cell (`null`, `''`) shows `—` in
its own column. Pass `loading` from `useApi`; don't write
`empty={data ? … : t('Loading…')}`, which shows "Loading…" forever when the
request fails.

### What isn't a DataTable

These stay as plain `<table>`s on purpose:

- **Editable line grids**: the till cart (Pos), invoice lines (Receiving),
  transfer request lines (Enquiries). Their rows are inputs, not records.
- **Printouts** inside `PrintArea`: customer statement, delivery note, stock
  count sheet, and the print mode of Reports. Paper layouts follow print CSS.
- **Analytics** pivot and breakdown tables, which are part of the visualizer.
- **Small key-value lists** inside a card (an invoice's payments, an import's
  column help).

### `AsyncContent`

For anything that isn't a table: cards, summaries, detail panes.

```jsx
const statement = useApi(() => getStatement(customerId), [customerId])

<AsyncContent
  state={statement}
  skeleton={<Skeleton.Text lines={4} />}
  isEmpty={(s) => s.entries.length === 0}
  empty={<EmptyState title={t('No credit sales yet')} />}
>
  {(s) => <StatementView statement={s} />}
</AsyncContent>
```

| Prop | Default | |
|---|---|---|
| `state` | required | `{data, loading, error, refetch}`, i.e. `useApi`'s result as-is |
| `children` | required | `(data) => node`, only called with real data |
| `isEmpty` | `null`, `[]` or `{results: []}` | |
| `empty`, `skeleton`, `idle`, `errorTitle`, `delay` | | `idle` shows when `useApi` skipped the call (its `fn` returned `null`). |

### `Field` + `Input` / `Select`

```jsx
<Field label={t('Selling price')} required hint={t('Per piece, in TZS')} error={errors.price}>
  <Input name="price" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
</Field>
```

`Field` wires its control automatically: `aria-describedby` points at the
hint or error, plus `aria-invalid` and `aria-required`, and the error outline
appears. The error line is a polite live region. The DOM shape never changes
when an error appears, so live validation can't steal focus from the input.

`Input`: every `<input>` prop plus `prefixIcon`, `invalid`, and `inputStyle`
(`style` sizes the wrapper). `Select`: `options` as values or
`{value, label, disabled}`, plus `placeholder` for a "choose one" first option.

A custom control can join in with `useFieldContext()` and `describedBy()`.

### `Button`

```jsx
<Button variant="primary" icon="save" loading={busy} onClick={save}>{t('Save')}</Button>
```

`variant`: default | `primary` | `secondary` | `destructive`. `size`: default | `small` | `large`.

Use **`loading`, not `disabled`**, while a save runs. The button keeps focus and
width, ignores clicks (and blocks form submits), and is announced as busy. A
disabled button drops keyboard focus to the page body. Pair it with
`useAsyncAction`:

```jsx
const { busy, error, run } = useAsyncAction()
<Button variant="primary" loading={busy} onClick={() => run(() => save(form), t('Could not save.'))}>{t('Save')}</Button>
```

### `Modal`

`title`, `onClose`, `footer`, `size` (`sm|md|lg|xl`), `initialFocus` (ref),
`dismissible` (default `true`; `false` blocks Escape, backdrop and the close
button while a save must finish). Focus is trapped inside and returns to the
opener on close. With nested dialogs, Escape closes only the top one and the
page scroll lock lasts until the last one closes.

### `Spinner`, `Skeleton`

`<Spinner size={20} label={t('Saving…')} />` announces itself. Use
`label={null}` when the surrounding element already says it's busy.
`<Skeleton width height circle radius />` and `<Skeleton.Text lines={3} />` are
decorative; put them inside something with `aria-busy` (AsyncContent does).

`useDelayedFlag(flag, ms)` is the anti-flash timer behind both data views,
for your own loading indicators.

## Best practices

- **Prefer the data views over hand-rolled branches.** A new
  `{loading && …}{error && …}{!loading && rows.length === 0 && …}` block in a
  screen is a sign it should use `DataTable` or `AsyncContent`. Hand-written
  `colSpan`s also go stale: AdminStores had 5 while pharmacy shops showed 6
  columns.
- **Empty states give the next step.** Title says what's missing, hint says why
  it matters, action fixes it. "No products yet" plus an **Add product** button.
- **Name everything.** Tables get a `caption`, icon-only buttons an
  `aria-label`, inputs a `Field` label (or `aria-label` inside a table cell).
- **Numbers: `align: 'end'`.** Tabular figures line up digits; money and
  quantities sort with `sortValue` because the API sends decimals as strings.
- **Phones first.** Check every new table at 375px: decide `cards` vs `scroll`,
  and mark low-value columns `hideOnMobile`.
- **Motion respects `prefers-reduced-motion`.** Shimmer stops and spinners slow down.
  New animations go in `tokens.css` with the same guard.
- **Don't add colours in components.** Need a new one? Add a token to
  `tokens.css` and `design-tokens.json` first.

## Testing

- Pure logic: `*.test.js` next to the module, run by `npm test` (`node --test`).
  See `dataTable.test.js`.
- Rendering: there's no DOM test runner yet. Component changes were checked by
  server-rendering each state through Vite's `ssrLoadModule` and asserting on
  the markup (ARIA attributes, spans, sort order). If the suite grows, adding
  Vitest + Testing Library is the next step.
