import { Fragment, useEffect, useRef, useState } from 'react'
import { Button, Card, Checkbox, Field, Icon, Input, NoticeBox, PageHeader, Select, Switch, Tag } from '../components/ds/index.js'
import PrintArea from '../components/PrintArea.jsx'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { client } from '../api/client.js'
import {
  createCustomer, getCreditSummary, getStatement, listCustomers, receivePayment, updateCustomer, voidPayment,
} from '../api/credit.js'
import { listPaymentMethods } from '../api/payments.js'
import { fmt } from '../appData.js'
import { apiErrorText } from '../lib/apiError.js'

const MANAGERS = ['store_manager', 'entity_admin']
const money = (v) => fmt(Number(v))
const parseAmount = (v) => parseFloat(String(v).replace(/[,\s]/g, '')) || 0
const EMPTY_CUSTOMER = { name: '', phone: '', address: '', note: '', credit_limit: '' }

/** Customers who buy on credit (madeni): what each owes, taking their
 * repayments, and their statement. Credit itself is given at the till. */
export default function Customers({ storeId, storeName, role, features }) {
  const auth = useAuth()
  const entity = auth.entity
  const isManager = MANAGERS.includes(role)
  const { data: summary, refetch: refetchSummary } = useApi(() => getCreditSummary(), [])
  const { data: methodPage } = useApi(() => listPaymentMethods(), [])
  const methods = (methodPage?.results ?? methodPage ?? []).filter((m) => m.is_active)
  const [filters, setFilters] = useState({ search: '', owing: false, inactive: false })
  const [customers, setCustomers] = useState([])
  const [next, setNext] = useState(null)
  const [message, setMessage] = useState(null)
  const [editing, setEditing] = useState(null) // {id?, ...fields}
  const [paying, setPaying] = useState(null) // {customer, amount, payment_method, reference, note}
  const [statementFor, setStatementFor] = useState(null)

  // Changing a filter while a list is still loading must not let the older,
  // slower response overwrite the newer one.
  const latest = useRef(0)
  async function load(url) {
    const request = ++latest.current
    try {
      const params = {
        search: filters.search.trim() || undefined, owing: filters.owing ? 'true' : undefined,
        is_active: filters.inactive ? undefined : 'true',
      }
      const page = url ? await client.get(url.replace(/^https?:\/\/[^/]+/, '')) : await listCustomers(params)
      if (request !== latest.current) return
      setCustomers((prev) => (url ? [...prev, ...page.results] : page.results))
      setNext(page.next)
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, 'Could not load the customers.') })
    }
  }
  const [version, setVersion] = useState(0)
  useEffect(() => {
    load(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, version])
  const reload = () => { setVersion((v) => v + 1); refetchSummary() }

  async function saveCustomer() {
    setMessage(null)
    const { id, ...fields } = editing
    const data = { ...fields, credit_limit: fields.credit_limit === '' ? null : String(parseAmount(fields.credit_limit)) }
    if (!isManager) delete data.credit_limit
    try {
      const saved = id ? await updateCustomer(id, data) : await createCustomer(data)
      setMessage({ variant: 'valid', text: id ? `${saved.name} saved.` : (isManager
        ? `${saved.name} added.`
        : `${saved.name} added. A manager sets how much credit they may take.`) })
      setEditing(null)
      reload()
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, 'Could not save the customer.') })
    }
  }

  async function takePayment() {
    setMessage(null)
    try {
      const payment = await receivePayment({
        customer: paying.customer.id, store: storeId, amount: String(parseAmount(paying.amount)),
        payment_method: paying.payment_method, reference: paying.reference.trim(), note: paying.note.trim(),
      })
      setMessage({ variant: 'valid', text: `${money(payment.amount)} received from ${payment.customer_name} by ${payment.payment_method_name}.` })
      setPaying(null)
      reload()
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, 'Could not record the payment.') })
    }
  }

  const creditOff = features?.customer_credit === false
  const payMethod = methods.find((m) => m.id === paying?.payment_method)

  return (
    <div>
      <PageHeader title="Customers" subtitle="Customers who buy on credit, what they owe, and their repayments." />

      {creditOff && (
        <NoticeBox variant="info" style={{ marginBottom: 16 }}>
          Sales on credit are switched off{storeName ? ` at ${storeName}` : ''}. Customers can still be kept here and pay off what they owe. An admin can switch credit on under Settings &gt; Features.
        </NoticeBox>
      )}

      {summary && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 12, marginBottom: 16 }}>
          <Card><div className="ds-stat-label">Owed by customers</div><div className="ds-stat-value">{money(summary.owed)}</div></Card>
          <Card><div className="ds-stat-label">Customers owing</div><div className="ds-stat-value">{summary.customers_owing} <span style={{ fontSize: 14, color: 'var(--fg-subtle)' }}>of {summary.customers}</span></div></Card>
          <Card>
            <div className="ds-stat-label">Over their credit limit</div>
            <div className="ds-stat-value" style={{ color: summary.over_limit ? 'var(--red-700)' : undefined }}>{summary.over_limit}</div>
          </Card>
        </div>
      )}

      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="Search">
            <Input value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))} placeholder="Name or phone" prefixIcon="search" style={{ width: 240 }} />
          </Field>
          <Checkbox checked={filters.owing} onChange={() => setFilters((f) => ({ ...f, owing: !f.owing }))} label="Only those who owe" />
          <Checkbox checked={filters.inactive} onChange={() => setFilters((f) => ({ ...f, inactive: !f.inactive }))} label="Show inactive" />
          <div style={{ flex: 1 }} />
          <Button variant="primary" onClick={() => setEditing({ ...EMPTY_CUSTOMER })}><Icon name="add" size={16} /> Add customer</Button>
        </div>
      </Card>

      {message && <NoticeBox variant={message.variant} style={{ marginBottom: 12 }}>{message.text}</NoticeBox>}

      {editing && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>{editing.id ? `Edit ${editing.name}` : 'New customer'}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 12, marginBottom: 12 }}>
            <Field label="Name" required><Input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></Field>
            <Field label="Phone"><Input value={editing.phone} onChange={(e) => setEditing({ ...editing, phone: e.target.value })} placeholder="e.g. 255712345678" /></Field>
            <Field label="Address"><Input value={editing.address} onChange={(e) => setEditing({ ...editing, address: e.target.value })} /></Field>
            <Field label="Note"><Input value={editing.note} onChange={(e) => setEditing({ ...editing, note: e.target.value })} placeholder="e.g. Pays every Friday" /></Field>
            {isManager && (
              <Field label="Credit limit (TZS)">
                <Input value={editing.credit_limit} onChange={(e) => setEditing({ ...editing, credit_limit: e.target.value })} placeholder="Blank = no limit; 0 = no credit" />
              </Field>
            )}
          </div>
          {editing.id && (
            <div style={{ marginBottom: 12 }}>
              <Switch on={editing.is_active} onChange={() => setEditing({ ...editing, is_active: !editing.is_active })} label="Active (shown at the till)" />
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" onClick={saveCustomer} disabled={!editing.name.trim()}>Save customer</Button>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </Card>
      )}

      <div className="ds-table-card">
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
          <thead>
            <tr>{['Customer', 'Phone', 'Owes', 'Credit limit', ''].map((h, i) => <th key={i} style={th(['Owes', 'Credit limit'].includes(h) ? 'right' : undefined)}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {customers.map((c) => {
              const owing = Number(c.owing)
              const over = c.credit_limit !== null && owing > Number(c.credit_limit)
              return (
                <Fragment key={c.id}>
                  <tr>
                    <td style={td()}>
                      <span style={{ fontWeight: 600, color: 'var(--grey-900)' }}>{c.name}</span>
                      {!c.is_active && <> <Tag variant="neutral">Inactive</Tag></>}
                      {c.note && <div style={sub}>{c.note}</div>}
                    </td>
                    <td style={td()}>{c.phone || '—'}</td>
                    <td style={td('right')}>
                      <span style={{ color: over ? 'var(--red-700)' : owing > 0 ? 'var(--grey-900)' : 'var(--fg-subtle)', fontWeight: owing > 0 ? 600 : 400 }}>
                        {owing < 0 ? `${money(-owing)} in credit` : money(owing)}
                      </span>
                      {over && <div style={{ ...sub, color: 'var(--red-700)' }}>over the limit</div>}
                    </td>
                    <td style={td('right')}>{c.credit_limit === null ? 'No limit' : Number(c.credit_limit) === 0 ? 'No credit' : money(c.credit_limit)}</td>
                    <td style={{ ...td('right'), whiteSpace: 'nowrap' }}>
                      <Button size="small" onClick={() => setPaying({ customer: c, amount: owing > 0 ? String(owing) : '', payment_method: methods.find((m) => m.implementation === 'cash')?.id ?? methods[0]?.id ?? '', reference: '', note: '' })} disabled={!storeId}>
                        Take payment
                      </Button>{' '}
                      <Button size="small" onClick={() => setStatementFor(statementFor === c.id ? null : c.id)}>{statementFor === c.id ? 'Hide statement' : 'Statement'}</Button>{' '}
                      <Button size="small" onClick={() => setEditing({
                        id: c.id, name: c.name, phone: c.phone, address: c.address, note: c.note, is_active: c.is_active,
                        credit_limit: c.credit_limit === null ? '' : String(Number(c.credit_limit)),
                      })}>Edit</Button>
                    </td>
                  </tr>
                  {paying?.customer.id === c.id && (
                    <tr>
                      <td colSpan={5} style={{ padding: 16, background: 'var(--grey-050)', borderBottom: '1px solid var(--grey-300)' }}>
                        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                          <Field label="Amount paid" required><Input value={paying.amount} onChange={(e) => setPaying((p) => ({ ...p, amount: e.target.value }))} style={{ width: 150 }} /></Field>
                          <Field label="Paid by">
                            <Select value={paying.payment_method} onChange={(e) => setPaying((p) => ({ ...p, payment_method: e.target.value }))} options={methods.map((m) => ({ value: m.id, label: m.name }))} style={{ width: 170 }} />
                          </Field>
                          {payMethod && payMethod.implementation !== 'cash' && (
                            <Field label="Transaction reference" required><Input value={paying.reference} onChange={(e) => setPaying((p) => ({ ...p, reference: e.target.value }))} placeholder="e.g. QK7Y2ZT1" style={{ width: 170 }} /></Field>
                          )}
                          <Field label="Note"><Input value={paying.note} onChange={(e) => setPaying((p) => ({ ...p, note: e.target.value }))} style={{ width: 200 }} /></Field>
                          <Button variant="primary" onClick={takePayment} disabled={parseAmount(paying.amount) <= 0 || !payMethod || (payMethod.implementation !== 'cash' && !paying.reference.trim())}>Record payment</Button>
                          <Button onClick={() => setPaying(null)}>Cancel</Button>
                        </div>
                        {payMethod?.implementation === 'cash' && (
                          <div style={{ ...sub, marginTop: 8 }}>Cash taken by a cashier counts in their open shift&rsquo;s drawer at {storeName}.</div>
                        )}
                      </td>
                    </tr>
                  )}
                  {statementFor === c.id && (
                    <tr>
                      <td colSpan={5} style={{ padding: 16, background: 'var(--grey-050)', borderBottom: '1px solid var(--grey-300)' }}>
                        <Statement customerId={c.id} entity={entity} isManager={isManager} onChanged={reload} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {customers.length === 0 && (
              <tr><td colSpan={5} style={{ ...td(), textAlign: 'center', color: 'var(--fg-subtle)', padding: 32 }}>
                {filters.search || filters.owing ? 'No customers match.' : 'No customers yet — add the customers who buy on credit.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      {next && <div style={{ marginTop: 12 }}><Button onClick={() => load(next)}>Load more</Button></div>}
      {!storeId && <div style={{ ...sub, marginTop: 12 }}>Choose a store in the top bar to take payments.</div>}
    </div>
  )
}

/** Every credit sale and payment, oldest first, with the running balance. */
function Statement({ customerId, entity, isManager, onChanged }) {
  const { data, loading, error, refetch } = useApi(() => getStatement(customerId), [customerId])
  const [voiding, setVoiding] = useState(null) // {id, reason}
  const [voidError, setVoidError] = useState('')

  async function submitVoid() {
    setVoidError('')
    try {
      await voidPayment(voiding.id, voiding.reason.trim())
      setVoiding(null)
      refetch()
      onChanged()
    } catch (err) {
      setVoidError(apiErrorText(err, 'Could not void the payment.'))
    }
  }

  if (loading && !data) return <div style={sub}>Loading…</div>
  if (error) return <NoticeBox variant="error">{apiErrorText(error, 'Could not load the statement.')}</NoticeBox>
  const body = <StatementBody data={data} entity={entity} />
  return (
    <div>
      {body}
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <Button size="small" onClick={() => window.print()}><Icon name="print" size={16} /> Print statement</Button>
        {isManager && data.rows.some((r) => r.kind === 'payment' && !r.voided) && !voiding && (
          <Select
            value=""
            onChange={(e) => e.target.value && setVoiding({ id: e.target.value, reason: '' })}
            options={[{ value: '', label: 'Void a payment…' }, ...data.rows.filter((r) => r.kind === 'payment' && !r.voided)
              .map((r) => ({ value: r.id, label: `${new Date(r.date).toLocaleDateString()} · ${money(-Number(r.amount))}` }))]}
            style={{ width: 220 }}
          />
        )}
      </div>
      {voiding && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginTop: 12, flexWrap: 'wrap' }}>
          <Field label="Why void this payment?" required>
            <Input value={voiding.reason} onChange={(e) => setVoiding({ ...voiding, reason: e.target.value })} placeholder="e.g. Recorded twice" style={{ width: 260 }} />
          </Field>
          <Button variant="destructive" onClick={submitVoid} disabled={!voiding.reason.trim()}>Void payment</Button>
          <Button onClick={() => setVoiding(null)}>Cancel</Button>
        </div>
      )}
      {voidError && <NoticeBox variant="error" style={{ marginTop: 8 }}>{voidError}</NoticeBox>}
      <PrintArea>{body}</PrintArea>
    </div>
  )
}

function StatementBody({ data, entity }) {
  const c = data.customer
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontWeight: 600 }}>{entity?.name} — statement for {c.name}</div>
          <div style={sub}>{[c.phone, c.address].filter(Boolean).join(' · ')}</div>
        </div>
        <div style={{ fontWeight: 600 }}>Owes {money(data.owing)}</div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>{['Date', 'Branch', 'Details', 'Amount', 'Balance'].map((h) => <th key={h} style={th(['Amount', 'Balance'].includes(h) ? 'right' : undefined)}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={`${r.kind}:${r.id}`} style={{ opacity: r.voided ? 0.55 : 1 }}>
              <td style={td()}>{r.date ? new Date(r.date).toLocaleDateString() : '—'}</td>
              <td style={td()}>{r.store}</td>
              <td style={td()}>{r.description}{r.voided && <> <Tag variant="negative">Voided</Tag></>}</td>
              <td style={td('right')}>{Number(r.amount) < 0 ? `− ${money(-Number(r.amount))}` : money(r.amount)}</td>
              <td style={td('right')}>{money(r.balance)}</td>
            </tr>
          ))}
          {data.rows.length === 0 && <tr><td colSpan={5} style={{ ...td(), textAlign: 'center', color: 'var(--fg-subtle)' }}>No credit sales or payments yet.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

const sub = { fontSize: 12, color: 'var(--fg-subtle)' }
function th(align) {
  return { textAlign: align || 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 12px', borderBottom: '1px solid var(--grey-300)', whiteSpace: 'nowrap' }
}
function td(align) {
  return { padding: '10px 12px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'left', fontSize: 13, color: 'var(--grey-800, var(--grey-900))', verticalAlign: 'top' }
}
