import { useState, useEffect, useCallback, Fragment } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'

const API = '/api'

async function apiFetch(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Request failed')
  }
  return res.json()
}

function StatusBadge({ status }) {
  const styles = {
    pending:   'bg-yellow-100 text-yellow-800 border border-yellow-300',
    funded:    'bg-blue-100 text-blue-800 border border-blue-300',
    delivered: 'bg-purple-100 text-purple-800 border border-purple-300',
    released:  'bg-green-100 text-green-800 border border-green-300',
    cancelled: 'bg-red-100 text-red-800 border border-red-300',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${styles[status] ?? 'bg-gray-100 text-gray-700'}`}>
      {status}
    </span>
  )
}

function Button({ onClick, disabled, loading, children, variant = 'primary', size = 'sm' }) {
  const base = 'inline-flex items-center gap-1.5 rounded font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
  const sizes = { sm: 'px-3 py-1.5 text-sm', md: 'px-4 py-2 text-sm' }
  const variants = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700',
    warning: 'bg-amber-500 text-white hover:bg-amber-600',
    danger:  'bg-red-500 text-white hover:bg-red-600',
    ghost:   'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className={`${base} ${sizes[size]} ${variants[variant]}`}
    >
      {loading && <span className="animate-spin text-xs">⟳</span>}
      {children}
    </button>
  )
}

function Alert({ message, type = 'error', onClose }) {
  if (!message) return null
  const styles = {
    error:   'bg-red-50 border-red-300 text-red-800',
    success: 'bg-green-50 border-green-300 text-green-800',
    info:    'bg-blue-50 border-blue-300 text-blue-800',
  }
  return (
    <div className={`flex items-start gap-2 border rounded p-3 text-sm ${styles[type]}`}>
      <span className="flex-1">{message}</span>
      <button onClick={onClose} className="opacity-60 hover:opacity-100">✕</button>
    </div>
  )
}

// --- BUDGET WIDGET ---

function BudgetWidget({ refreshKey }) {
  const [budget, setBudget] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await apiFetch('/inventory/budget')
      setBudget(data)
    } catch {}
  }, [])

  useEffect(() => { load() }, [load, refreshKey])

  async function save() {
    const val = parseFloat(draft)
    if (isNaN(val) || val < 0) return
    setSaving(true)
    try {
      await apiFetch('/inventory/budget', {
        method: 'PUT',
        body: JSON.stringify({ total_budget: val }),
      })
      await load()
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  if (!budget) return null

  const pct = budget.total_budget > 0
    ? Math.min(100, (budget.spent / budget.total_budget) * 100)
    : 0
  const barColor = pct > 85 ? 'bg-red-500' : pct > 60 ? 'bg-amber-400' : 'bg-emerald-500'

  return (
    <div className="flex items-center gap-3 text-sm">
      {editing ? (
        <div className="flex items-center gap-1.5">
          <input
            autoFocus
            type="number"
            step="0.01"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
            className="w-28 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            placeholder="ALGO budget"
          />
          <Button onClick={save} loading={saving} size="sm" variant="success">Save</Button>
          <Button onClick={() => setEditing(false)} size="sm" variant="ghost">✕</Button>
        </div>
      ) : (
        <button
          onClick={() => { setDraft(String(budget.total_budget)); setEditing(true) }}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          title="Click to set budget"
        >
          <div className="text-right">
            <div className="text-xs text-gray-400 leading-none">Budget</div>
            <div className="font-semibold text-gray-700 leading-tight">
              {budget.remaining.toFixed(2)}
              <span className="text-gray-400 font-normal"> / {budget.total_budget.toFixed(2)} ALGO</span>
            </div>
          </div>
          {budget.total_budget > 0 && (
            <div className="w-20 h-2 bg-gray-200 rounded-full overflow-hidden">
              <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
            </div>
          )}
        </button>
      )}
    </div>
  )
}

// --- INVENTORY TAB ---

// --- AUTO-BUY PANEL ---

function AutoBuyPanel({ suppliers, refreshOrders }) {
  const [configs, setConfigs]   = useState([])
  const [saving, setSaving]     = useState({})
  const [expanded, setExpanded] = useState({})
  const [catalog, setCatalog]   = useState([])   // all SupplierProduct entries

  useEffect(() => {
    apiFetch('/inventory/catalog').then(setCatalog).catch(() => {})
  }, [])

  useEffect(() => {
    apiFetch('/inventory/auto-buy').then(setConfigs).catch(() => {})
  }, [])

  async function update(productId, patch) {
    // Optimistic update
    setConfigs(cs => cs.map(c => c.product_id === productId ? { ...c, ...patch } : c))
    setSaving(s => ({ ...s, [productId]: true }))
    try {
      const current = configs.find(c => c.product_id === productId) ?? {}
      const body = {
        enabled:     patch.enabled     ?? current.enabled,
        mode:        patch.mode        ?? current.mode,
        supplier_id: patch.supplier_id !== undefined ? patch.supplier_id : current.supplier_id,
      }
      const updated = await apiFetch(`/inventory/auto-buy/${productId}`, {
        method: 'PUT', body: JSON.stringify(body),
      })
      setConfigs(cs => cs.map(c => c.product_id === productId ? { ...c, ...updated } : c))
      if (refreshOrders) refreshOrders()
    } catch {}
    finally { setSaving(s => ({ ...s, [productId]: false })) }
  }

  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Auto-buy</span>
        <span className="text-xs text-gray-400">Auto-reorder when stock drops below the reorder point</span>
      </div>

      <div className="divide-y divide-gray-100">
        {configs.map(cfg => {
          const aiChoice = cfg.last_ai_choice
          const isExpanded = expanded[cfg.product_id]

          return (
            <div key={cfg.product_id} className="px-4 py-3">
              <div className="flex items-center gap-4 flex-wrap">
                {/* Product name */}
                <div className="w-36 flex-shrink-0">
                  <span className="text-sm font-medium text-gray-900">{cfg.product_name}</span>
                  <span className="ml-1 text-xs text-gray-400">{cfg.unit}</span>
                </div>

                {/* Toggle */}
                <label className="relative inline-flex items-center cursor-pointer gap-2 flex-shrink-0">
                  <div
                    onClick={() => update(cfg.product_id, { enabled: !cfg.enabled })}
                    className={`w-9 h-5 rounded-full transition-colors cursor-pointer
                      ${cfg.enabled ? 'bg-indigo-600' : 'bg-gray-300'}
                      ${saving[cfg.product_id] ? 'opacity-50' : ''}`}
                  >
                    <div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform
                      ${cfg.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
                  </div>
                  <span className={`text-xs font-medium ${cfg.enabled ? 'text-indigo-700' : 'text-gray-400'}`}>
                    {cfg.enabled ? 'On' : 'Off'}
                  </span>
                </label>

                {cfg.enabled && (<>
                  {/* Mode selector */}
                  <select
                    value={cfg.mode}
                    onChange={e => update(cfg.product_id, { mode: e.target.value })}
                    className="text-xs border border-gray-300 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  >
                    <option value="fixed">Fixed supplier</option>
                    <option value="ai">AI agent</option>
                  </select>

                  {/* Supplier selector (fixed mode) */}
                  {cfg.mode === 'fixed' && (() => {
                    const hasEntry = cfg.supplier_id
                      ? catalog.some(e => e.supplier_id === cfg.supplier_id && e.product_id === cfg.product_id)
                      : false
                    const showWarn = cfg.supplier_id && !hasEntry
                    return (
                      <div className="flex items-center gap-1.5">
                        <select
                          value={cfg.supplier_id ?? ''}
                          onChange={e => update(cfg.product_id, { supplier_id: e.target.value ? Number(e.target.value) : null })}
                          className={`text-xs border rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-indigo-400
                            ${showWarn ? 'border-amber-400' : 'border-gray-300'}`}
                        >
                          <option value="">— Select supplier —</option>
                          {suppliers.map(s => {
                            const inCatalog = catalog.some(e => e.supplier_id === s.id && e.product_id === cfg.product_id)
                            return (
                              <option key={s.id} value={s.id}>
                                {s.name}{inCatalog ? '' : ' (no offer)'}
                              </option>
                            )
                          })}
                        </select>
                        {showWarn && (
                          <span title="This supplier does not carry this product in their catalog" className="text-amber-500 text-sm cursor-help">⚠</span>
                        )}
                      </div>
                    )
                  })()}

                  {/* AI mode badge + reasoning toggle */}
                  {cfg.mode === 'ai' && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full font-medium">
                        🤖 Claude Haiku
                      </span>
                      {aiChoice && (
                        <button
                          onClick={() => setExpanded(e => ({ ...e, [cfg.product_id]: !isExpanded }))}
                          className="text-xs text-violet-600 hover:underline"
                        >
                          {isExpanded ? 'hide' : 'last decision ▾'}
                        </button>
                      )}
                    </div>
                  )}
                </>)}
              </div>

              {/* AI reasoning expansion */}
              {cfg.mode === 'ai' && isExpanded && aiChoice && (
                <div className="mt-2 ml-40 bg-violet-50 border border-violet-100 rounded px-3 py-2 text-xs text-violet-800 space-y-0.5">
                  <div className="font-semibold">Chosen: {aiChoice.supplier_name}</div>
                  <div className="text-violet-600">{aiChoice.reasoning}</div>
                  <div className="text-violet-400">
                    {aiChoice.at && new Date(aiChoice.at).toLocaleString('en-US', { dateStyle: 'short', timeStyle: 'short' })}
                  </div>
                </div>
              )}

              {/* Fixed mode: show configured supplier chip */}
              {cfg.enabled && cfg.mode === 'fixed' && cfg.supplier_name && (
                <div className="mt-1 ml-40">
                  <span className="text-xs text-gray-500">→ {cfg.supplier_name}</span>
                </div>
              )}
            </div>
          )
        })}

        {configs.length === 0 && (
          <div className="px-4 py-4 text-xs text-gray-400 text-center">No products found.</div>
        )}
      </div>
    </div>
  )
}

const REASON_LABEL = {
  sale:       { label: 'Sale',          color: 'text-red-600',   bg: 'bg-red-50',   icon: '▼' },
  restock:    { label: 'Restock',       color: 'text-green-600', bg: 'bg-green-50', icon: '▲' },
  simulation: { label: 'Simulation',    color: 'text-indigo-500',bg: 'bg-indigo-50',icon: '⏩' },
}

function ActivityLog({ refreshKey }) {
  const [entries, setEntries] = useState([])

  useEffect(() => {
    apiFetch('/inventory/activity').then(setEntries).catch(() => {})
  }, [refreshKey])

  if (entries.length === 0) return (
    <div className="text-xs text-gray-400 text-center py-4">No movements recorded yet.</div>
  )

  return (
    <div className="divide-y divide-gray-100">
      {entries.map(e => {
        const r = REASON_LABEL[e.reason] ?? { label: e.reason, color: 'text-gray-600', bg: 'bg-gray-50', icon: '·' }
        const ts = new Date(e.logged_at)
        const timeStr = ts.toLocaleString('en-US', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
        return (
          <div key={e.id} className={`flex items-center gap-3 px-3 py-2 ${r.bg}`}>
            <span className={`text-base leading-none ${r.color}`}>{r.icon}</span>
            <div className="flex-1 min-w-0">
              <span className="font-medium text-gray-900 text-sm">{e.product_name}</span>
              <span className="ml-1.5 text-gray-400 text-xs">{e.unit}</span>
              {e.note && <span className="ml-2 text-xs text-gray-400">{e.note}</span>}
            </div>
            <span className={`text-sm font-mono font-semibold ${r.color}`}>
              {e.change > 0 ? `+${e.change}` : e.change}
            </span>
            <span className="text-xs text-gray-400 tabular-nums whitespace-nowrap">{timeStr}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded ${r.bg} ${r.color} border border-current border-opacity-20`}>
              {r.label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function InventoryTab({ onOrdersChanged }) {
  const [stocks, setStocks]       = useState([])
  const [products, setProducts]   = useState({})
  const [loading, setLoading]     = useState(true)
  const [selling, setSelling]     = useState({})
  const [alert, setAlert]         = useState(null)
  const [logKey, setLogKey]       = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [stockList, productList] = await Promise.all([
        apiFetch('/inventory/stock'),
        apiFetch('/inventory/products'),
      ])
      const productMap = Object.fromEntries(productList.map(p => [p.id, p]))
      setProducts(productMap)
      setStocks(stockList)
    } catch (e) {
      setAlert({ message: e.message, type: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function sell(productId) {
    setSelling(s => ({ ...s, [productId]: true }))
    setAlert(null)
    try {
      const data = await apiFetch(`/inventory/stock/${productId}/sell?quantity=1`, { method: 'POST' })
      if (data.auto_orders?.length > 0) {
        setAlert({ message: `Sold — reorder auto-triggered for ${data.auto_orders.length} product(s)`, type: 'success' })
        onOrdersChanged()
      } else {
        setAlert({ message: 'Sold — stock updated', type: 'success' })
      }
      await load()
      setLogKey(k => k + 1)
    } catch (e) {
      setAlert({ message: e.message, type: 'error' })
      await load()
    } finally {
      setSelling(s => ({ ...s, [productId]: false }))
    }
  }

  if (loading) return <div className="py-16 text-center text-gray-400">Loading inventory…</div>

  return (
    <div className="space-y-4">
      {alert && <Alert message={alert.message} type={alert.type} onClose={() => setAlert(null)} />}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Stock Levels</h2>
        <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
      </div>
      <div className="overflow-hidden rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3 text-left">Product</th>
              <th className="px-4 py-3 text-right">Quantity</th>
              <th className="px-4 py-3 text-right">Reorder Point</th>
              <th className="px-4 py-3 text-right">Reorder Qty</th>
              <th className="px-4 py-3 text-right">Lead Time</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-center">Simulate Sale</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {stocks.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                  No stock entries yet.
                </td>
              </tr>
            )}
            {stocks.map(stock => {
              const low = stock.quantity <= stock.reorder_point
              const product = products[stock.product_id]
              return (
                <tr key={stock.id} className={low ? 'bg-red-50' : 'bg-white'}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {product?.name ?? `Product #${stock.product_id}`}
                    <span className="ml-2 text-gray-400 text-xs">{product?.unit}</span>
                  </td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${low ? 'text-red-600' : 'text-gray-700'}`}>
                    {stock.quantity}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-500">{stock.reorder_point}</td>
                  <td className="px-4 py-3 text-right text-gray-500">{stock.reorder_qty}</td>
                  <td className="px-4 py-3 text-right text-gray-500">
                    {product?.lead_time_days != null ? `${product.lead_time_days} ${product.lead_time_days === 1 ? 'day' : 'days'}` : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {low
                      ? <span className="px-2 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-700 border border-red-200">Low Stock</span>
                      : <span className="px-2 py-0.5 rounded text-xs font-semibold bg-green-100 text-green-700 border border-green-200">OK</span>
                    }
                  </td>
                  <td className="px-4 py-3 text-center">
                    <Button
                      onClick={() => sell(stock.product_id)}
                      loading={selling[stock.product_id]}
                      disabled={stock.quantity === 0}
                      variant="ghost"
                      size="sm"
                    >
                      Sell 1
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Activity Log */}
      <div className="rounded-lg border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Recent Activity</span>
          <button onClick={() => setLogKey(k => k + 1)} className="text-xs text-indigo-500 hover:underline">↻</button>
        </div>
        <ActivityLog refreshKey={logKey} />
      </div>
    </div>
  )
}

// --- ORDERS TAB ---

function StarRating({ value, onChange, size = 'md' }) {
  const [hovered, setHovered] = useState(null)
  const sz = size === 'sm' ? 'text-base' : 'text-2xl'
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map(star => (
        <button
          key={star}
          type="button"
          onClick={() => onChange?.(star)}
          onMouseEnter={() => onChange && setHovered(star)}
          onMouseLeave={() => onChange && setHovered(null)}
          className={`${sz} transition-colors leading-none ${
            star <= (hovered ?? value ?? 0) ? 'text-amber-400' : 'text-gray-300'
          } ${onChange ? 'cursor-pointer hover:scale-110' : 'cursor-default'}`}
        >
          ★
        </button>
      ))}
    </div>
  )
}

function RateModal({ order, onClose, onRated }) {
  const [stars, setStars] = useState(0)
  const [note, setNote]   = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState(null)

  async function submit() {
    if (!stars) return
    setSaving(true)
    setError(null)
    try {
      await apiFetch(`/orders/${order.id}/rate`, {
        method: 'POST',
        body: JSON.stringify({ stars, note }),
      })
      onRated()
    } catch (e) {
      setError(e.message)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">Rate Supplier — Order #{order.id}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
        </div>

        <div className="flex flex-col items-center gap-3 py-2">
          <StarRating value={stars} onChange={setStars} />
          <div className="text-sm text-gray-400">
            {['', 'Very poor', 'Poor', 'OK', 'Good', 'Excellent'][stars] || 'Select a rating'}
          </div>
        </div>

        <textarea
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="Optional note (punctuality, quality…)"
          rows={3}
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
        />

        {error && <Alert message={error} type="error" onClose={() => setError(null)} />}

        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose} variant="ghost" size="sm">Cancel</Button>
          <Button onClick={submit} loading={saving} disabled={!stars} variant="primary" size="sm">
            Save rating
          </Button>
        </div>
      </div>
    </div>
  )
}

function FundModal({ order, onClose, onFunded }) {
  const [offers, setOffers]     = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading]   = useState(true)
  const [funding, setFunding]   = useState(false)
  const [error, setError]       = useState(null)

  useEffect(() => {
    apiFetch(`/inventory/catalog/product/${order.product_id}`)
      .then(data => {
        setOffers(data)
        if (data.length > 0) setSelected(data[0].supplier_id)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [order.product_id])

  const chosen = offers.find(o => o.supplier_id === selected)
  const estimatedTotal = chosen ? (chosen.unit_price * order.quantity).toFixed(4) : '—'

  async function fund() {
    if (!selected) return
    setFunding(true)
    setError(null)
    try {
      await apiFetch(`/orders/${order.id}/fund`, {
        method: 'POST',
        body: JSON.stringify({ supplier_id: selected }),
      })
      onFunded()
    } catch (e) {
      setError(e.message)
      setFunding(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">Fund Escrow — Order #{order.id}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>

        <div className="text-sm text-gray-500">
          Quantity: <span className="font-semibold text-gray-700">{order.quantity} units</span>
        </div>

        {loading && <div className="py-4 text-center text-gray-400 text-sm">Loading offers…</div>}

        {!loading && offers.length === 0 && (
          <div className="py-4 text-center text-amber-600 text-sm">
            No suppliers have this product in their catalog yet.
            Add a catalog entry in the Suppliers tab first.
          </div>
        )}

        {!loading && offers.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Select Supplier</div>
            {offers.map(offer => (
              <label
                key={offer.supplier_id}
                className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  selected === offer.supplier_id
                    ? 'border-indigo-500 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <input
                  type="radio"
                  name="supplier"
                  value={offer.supplier_id}
                  checked={selected === offer.supplier_id}
                  onChange={() => setSelected(offer.supplier_id)}
                  className="accent-indigo-600"
                />
                <div className="flex-1">
                  <div className="font-medium text-gray-900">{offer.supplier_name}</div>
                  <div className="text-xs text-gray-500">
                    {offer.unit_price.toFixed(4)} ALGO/unit
                    {offer.min_order_qty > 1 && ` · min ${offer.min_order_qty}`}
                  </div>
                </div>
                <div className="text-sm font-semibold text-indigo-700">
                  {(offer.unit_price * order.quantity).toFixed(4)} ALGO
                </div>
              </label>
            ))}
          </div>
        )}

        {error && <Alert message={error} type="error" onClose={() => setError(null)} />}

        <div className="flex items-center justify-between pt-2 border-t border-gray-100">
          <div className="text-sm text-gray-500">
            Total: <span className="font-bold text-gray-900">{estimatedTotal} ALGO</span>
          </div>
          <div className="flex gap-2">
            <Button onClick={onClose} variant="ghost" size="sm">Cancel</Button>
            <Button
              onClick={fund}
              loading={funding}
              disabled={!selected || offers.length === 0}
              variant="primary"
              size="sm"
            >
              💰 Fund Escrow
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function OrderActions({ order, acting, onAction, onFundClick, onRateClick }) {
  const id = order.id
  const loading = (action) => acting[id] === action

  if (order.status === 'pending') {
    return (
      <div className="flex items-center gap-2 justify-center">
        <Button onClick={() => onFundClick(order)} variant="primary" size="sm">
          💰 Fund Escrow
        </Button>
        <Button onClick={() => onAction(id, 'cancel')} loading={loading('cancel')} variant="ghost" size="sm">
          ✕ Cancel
        </Button>
      </div>
    )
  }
  if (order.status === 'funded') {
    return (
      <Button onClick={() => onAction(id, 'confirm-delivery')} loading={loading('confirm-delivery')} variant="warning" size="sm">
        📦 Confirm Delivery
      </Button>
    )
  }
  if (order.status === 'delivered') {
    return (
      <Button onClick={() => onAction(id, 'release')} loading={loading('release')} variant="success" size="sm">
        ✓ Release Payment
      </Button>
    )
  }
  if (order.status === 'released') {
    return order.rating
      ? <StarRating value={order.rating} size="sm" />
      : <Button onClick={() => onRateClick(order)} variant="ghost" size="sm">⭐ Rate</Button>
  }
  return <span className="text-gray-400 text-xs">—</span>
}

const LORA = 'https://lora.algokit.io/localnet'

function TxnLink({ txnId, label }) {
  if (!txnId) return <span className="text-gray-300">—</span>
  return (
    <a
      href={`${LORA}/transaction/${txnId}`}
      target="_blank"
      rel="noreferrer"
      className="font-mono text-indigo-500 hover:text-indigo-700 hover:underline text-xs"
      title={txnId}
    >
      {label ?? txnId.slice(0, 10) + '…'}
    </a>
  )
}

function AuditTrail({ order }) {
  const steps = [
    { label: 'Order Created',     done: true,                              txnId: null },
    { label: 'Escrow Deployed',   done: !!order.app_id,                   txnId: order.create_txn_id },
    { label: 'Escrow Funded',     done: order.status !== 'pending',       txnId: order.txn_id },
    { label: 'Delivery Confirmed',done: ['delivered','released'].includes(order.status), txnId: null },
    { label: 'Payment Released',  done: order.status === 'released',      txnId: null },
  ]
  return (
    <div className="px-4 pb-4 pt-1 bg-gray-50 border-t border-gray-100 space-y-3">
      {/* Timeline */}
      <div className="flex items-start gap-0 mt-2">
        {steps.map((step, i) => (
          <div key={i} className="flex-1 flex flex-col items-center">
            <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold border-2 z-10 ${
              step.done ? 'bg-indigo-600 border-indigo-600 text-white' : 'bg-white border-gray-300 text-gray-300'
            }`}>
              {step.done ? '✓' : i + 1}
            </div>
            {i < steps.length - 1 && (
              <div className="absolute mt-2.5 h-0.5 w-full" />
            )}
            <div className="text-center mt-1.5">
              <div className={`text-xs font-medium leading-tight ${step.done ? 'text-gray-700' : 'text-gray-300'}`}>
                {step.label}
              </div>
              {step.txnId && (
                <TxnLink txnId={step.txnId} />
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Details grid */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs mt-3 pt-3 border-t border-gray-200">
        {order.order_hash && <>
          <span className="text-gray-400">Order Hash</span>
          <span className="font-mono text-gray-600 break-all">{order.order_hash}</span>
        </>}
        {order.app_id && <>
          <span className="text-gray-400">Escrow App ID</span>
          <a
            href={`${LORA}/application/${order.app_id}`}
            target="_blank" rel="noreferrer"
            className="text-indigo-500 hover:underline font-mono"
          >
            {order.app_id}
          </a>
        </>}
        {order.escrow_address && <>
          <span className="text-gray-400">Escrow Address</span>
          <span className="font-mono text-gray-600 break-all">{order.escrow_address}</span>
        </>}
        {order.create_txn_id && <>
          <span className="text-gray-400">Create Txn</span>
          <TxnLink txnId={order.create_txn_id} label={order.create_txn_id} />
        </>}
        {order.txn_id && <>
          <span className="text-gray-400">Fund Txn</span>
          <TxnLink txnId={order.txn_id} label={order.txn_id} />
        </>}
      </div>
    </div>
  )
}

function useOrders({ onBudgetChanged } = {}) {
  const [orders, setOrders]   = useState([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing]   = useState({})
  const [alert, setAlert]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const list = await apiFetch('/orders/')
      setOrders([...list].reverse())
    } catch (e) {
      setAlert({ message: e.message, type: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const orderAction = useCallback(async (orderId, action) => {
    if (action === 'cancel' && !window.confirm(`Really cancel Order #${orderId}?`)) return
    setActing(a => ({ ...a, [orderId]: action }))
    setAlert(null)
    try {
      await apiFetch(`/orders/${orderId}/${action}`, { method: 'POST' })
      setAlert({ message: `Order #${orderId}: ${action} successful`, type: 'success' })
      if (action === 'release') onBudgetChanged?.()
      await load()
    } catch (e) {
      setAlert({ message: e.message, type: 'error' })
    } finally {
      setActing(a => ({ ...a, [orderId]: null }))
    }
  }, [load, onBudgetChanged])

  return { orders, loading, acting, alert, setAlert, load, orderAction }
}

function OrderSection({ title, hint, rows, acting, orderAction, onFundClick, onRateClick, expanded, toggleExpand }) {
  if (rows.length === 0) return null
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">{title}</h3>
      {hint && <p className="text-xs text-gray-400 -mt-1">{hint}</p>}
      <div className="overflow-hidden rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3 text-left">Order</th>
              <th className="px-4 py-3 text-right">Qty</th>
              <th className="px-4 py-3 text-right">Unit Price</th>
              <th className="px-4 py-3 text-right">Total (ALGO)</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-center">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(order => (
              <Fragment key={order.id}>
                <tr
                  className="bg-white hover:bg-gray-50 transition-colors border-t border-gray-100 cursor-pointer"
                  onClick={() => toggleExpand(order.id)}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-gray-400 text-xs transition-transform ${expanded[order.id] ? 'rotate-90' : ''}`}>▶</span>
                      <span className="font-medium text-gray-900">Order #{order.id}</span>
                    </div>
                    {order.order_hash && (
                      <div className="text-xs text-gray-400 font-mono ml-4" title={order.order_hash}>
                        {order.order_hash.slice(0, 14)}…
                      </div>
                    )}
                    {order.status === 'funded' && order.deliver_on_day != null && (
                      <div className="text-xs text-amber-600 ml-4">🚚 Arrives: sim day {order.deliver_on_day}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 font-mono">{order.quantity}</td>
                  <td className="px-4 py-3 text-right text-gray-500 font-mono">
                    {order.unit_price != null ? order.unit_price.toFixed(4) : '—'}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 font-mono font-semibold">
                    {order.total_price != null ? order.total_price.toFixed(4) : '—'}
                  </td>
                  <td className="px-4 py-3 text-center" onClick={e => e.stopPropagation()}>
                    <StatusBadge status={order.status} />
                  </td>
                  <td className="px-4 py-3 text-center" onClick={e => e.stopPropagation()}>
                    <OrderActions
                      order={order}
                      acting={acting}
                      onAction={orderAction}
                      onFundClick={onFundClick}
                      onRateClick={onRateClick}
                    />
                  </td>
                </tr>
                {expanded[order.id] && (
                  <tr>
                    <td colSpan={6} className="p-0">
                      <AuditTrail order={order} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OrdersTab({ onBudgetChanged }) {
  const { orders, loading, acting, alert, setAlert, load, orderAction } = useOrders({ onBudgetChanged })
  const [suppliers, setSuppliers]       = useState([])
  const [generating, setGenerating]     = useState(false)
  const [fundingOrder, setFundingOrder] = useState(null)
  const [ratingOrder, setRatingOrder]   = useState(null)
  const [expanded, setExpanded]         = useState({})
  const toggleExpand = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }))

  useEffect(() => {
    apiFetch('/inventory/suppliers').then(setSuppliers).catch(() => {})
  }, [])

  async function generate() {
    setGenerating(true)
    setAlert(null)
    try {
      const data = await apiFetch('/orders/generate', { method: 'POST' })
      setAlert({ message: data.message, type: data.orders?.length > 0 ? 'success' : 'info' })
      await load()
    } catch (e) {
      setAlert({ message: e.message, type: 'error' })
    } finally {
      setGenerating(false)
    }
  }

  const pending   = orders.filter(o => o.status === 'pending')
  const completed = orders.filter(o => ['released', 'cancelled'].includes(o.status))

  if (loading) return <div className="py-16 text-center text-gray-400">Loading orders…</div>

  return (
    <div className="space-y-6">
      {fundingOrder && (
        <FundModal
          order={fundingOrder}
          onClose={() => setFundingOrder(null)}
          onFunded={async () => {
            setFundingOrder(null)
            setAlert({ message: `Order #${fundingOrder.id} funded successfully`, type: 'success' })
            onBudgetChanged?.()
            await load()
          }}
        />
      )}

      {ratingOrder && (
        <RateModal
          order={ratingOrder}
          onClose={() => setRatingOrder(null)}
          onRated={async () => {
            setRatingOrder(null)
            setAlert({ message: 'Rating saved', type: 'success' })
            await load()
          }}
        />
      )}

      {alert && <Alert message={alert.message} type={alert.type} onClose={() => setAlert(null)} />}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Purchase Orders</h2>
        <div className="flex gap-2">
          <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
          <Button onClick={generate} loading={generating} variant="primary" size="sm">
            ⚡ Generate Orders
          </Button>
        </div>
      </div>

      {orders.length === 0 && (
        <div className="py-16 text-center text-gray-400 border-2 border-dashed border-gray-200 rounded-lg">
          No orders yet. Sell products until stock drops below the reorder point, then click Generate Orders.
        </div>
      )}

      <OrderSection
        title="Pending" rows={pending} acting={acting} orderAction={orderAction}
        onFundClick={setFundingOrder} onRateClick={setRatingOrder}
        expanded={expanded} toggleExpand={toggleExpand}
      />
      <OrderSection
        title="Completed" rows={completed} acting={acting} orderAction={orderAction}
        onFundClick={setFundingOrder} onRateClick={setRatingOrder}
        expanded={expanded} toggleExpand={toggleExpand}
      />

      {/* Auto-buy settings */}
      <AutoBuyPanel suppliers={suppliers} refreshOrders={load} />
    </div>
  )
}

// --- DELIVERIES TAB ---

function DeliveriesTab({ onBudgetChanged }) {
  const { orders, loading, acting, alert, setAlert, load, orderAction } = useOrders({ onBudgetChanged })
  const [expanded, setExpanded] = useState({})
  const toggleExpand = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }))
  const noop = () => {}

  const incoming  = orders.filter(o => o.status === 'funded')
  const delivered = orders.filter(o => o.status === 'delivered')

  if (loading) return <div className="py-16 text-center text-gray-400">Loading deliveries…</div>

  return (
    <div className="space-y-6">
      {alert && <Alert message={alert.message} type={alert.type} onClose={() => setAlert(null)} />}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Deliveries</h2>
        <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
      </div>

      {incoming.length === 0 && delivered.length === 0 && (
        <div className="py-16 text-center text-gray-400 border-2 border-dashed border-gray-200 rounded-lg">
          No open deliveries. Once an order is funded in the Orders tab,
          it appears here for delivery confirmation.
        </div>
      )}

      <OrderSection
        title="Confirm Delivery"
        hint="Funded orders — confirm receipt of the goods."
        rows={incoming} acting={acting} orderAction={orderAction}
        onFundClick={noop} onRateClick={noop}
        expanded={expanded} toggleExpand={toggleExpand}
      />
      <OrderSection
        title="Delivered — Release Payment"
        hint="Goods confirmed — release the escrow payment to the supplier."
        rows={delivered} acting={acting} orderAction={orderAction}
        onFundClick={noop} onRateClick={noop}
        expanded={expanded} toggleExpand={toggleExpand}
      />
    </div>
  )
}

// --- SUPPLIERS TAB ---

function SuppliersTab() {
  const [suppliers, setSuppliers] = useState([])
  const [ratings, setRatings]     = useState({})   // keyed by supplier id
  const [products, setProducts]   = useState([])
  const [catalog, setCatalog]     = useState([])
  const [loading, setLoading]     = useState(true)
  const [alert, setAlert]         = useState(null)
  const [form, setForm]           = useState({ supplier_id: '', product_id: '', unit_price: '', min_order_qty: '1' })
  const [saving, setSaving]       = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [sups, prods, cat, ratingList] = await Promise.all([
        apiFetch('/inventory/suppliers'),
        apiFetch('/inventory/products'),
        apiFetch('/inventory/catalog'),
        apiFetch('/inventory/suppliers/ratings'),
      ])
      setSuppliers(sups)
      setProducts(prods)
      setCatalog(cat)
      setRatings(Object.fromEntries(ratingList.map(r => [r.id, r])))
      if (sups.length > 0 && !form.supplier_id) {
        setForm(f => ({ ...f, supplier_id: String(sups[0].id) }))
      }
    } catch (e) {
      setAlert({ message: e.message, type: 'error' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const supplierMap = Object.fromEntries(suppliers.map(s => [s.id, s]))
  const productMap  = Object.fromEntries(products.map(p => [p.id, p]))

  async function addEntry(e) {
    e.preventDefault()
    setSaving(true)
    setAlert(null)
    try {
      await apiFetch('/inventory/catalog', {
        method: 'POST',
        body: JSON.stringify({
          supplier_id:   parseInt(form.supplier_id),
          product_id:    parseInt(form.product_id),
          unit_price:    parseFloat(form.unit_price),
          min_order_qty: parseInt(form.min_order_qty) || 1,
        }),
      })
      await load()
      setForm(f => ({ ...f, product_id: '', unit_price: '', min_order_qty: '1' }))
      setAlert({ message: 'Catalog entry saved', type: 'success' })
    } catch (err) {
      setAlert({ message: err.message, type: 'error' })
    } finally {
      setSaving(false)
    }
  }

  async function removeEntry(id) {
    if (!window.confirm('Remove this catalog entry?')) return
    try {
      await apiFetch(`/inventory/catalog/${id}`, { method: 'DELETE' })
      await load()
    } catch (err) {
      setAlert({ message: err.message, type: 'error' })
    }
  }

  if (loading) return <div className="py-16 text-center text-gray-400">Loading suppliers…</div>

  // Group catalog by supplier
  const bySupplier = {}
  for (const sup of suppliers) bySupplier[sup.id] = []
  for (const entry of catalog) {
    if (bySupplier[entry.supplier_id]) bySupplier[entry.supplier_id].push(entry)
  }

  return (
    <div className="space-y-6">
      {alert && <Alert message={alert.message} type={alert.type} onClose={() => setAlert(null)} />}

      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Supplier Catalogs</h2>
        <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
      </div>

      {/* Per-supplier catalog tables */}
      {suppliers.map(sup => {
        const entries   = bySupplier[sup.id] ?? []
        const ratingInfo = ratings[sup.id]
        return (
          <div key={sup.id} className="rounded-lg border border-gray-200 overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 flex items-center justify-between border-b border-gray-200">
              <div>
                <div className="font-semibold text-gray-900">{sup.name}</div>
                <div className="text-xs text-gray-400">{sup.contact_email}</div>
                {ratingInfo?.avg_rating != null && (
                  <div className="flex items-center gap-1.5 mt-1">
                    <StarRating value={Math.round(ratingInfo.avg_rating)} size="sm" />
                    <span className="text-xs text-gray-500">
                      {ratingInfo.avg_rating.toFixed(1)} / 5
                      <span className="text-gray-400"> ({ratingInfo.rating_count} {ratingInfo.rating_count === 1 ? 'review' : 'reviews'})</span>
                    </span>
                  </div>
                )}
                {ratingInfo?.avg_rating == null && (
                  <div className="text-xs text-gray-400 mt-1">No reviews yet</div>
                )}
              </div>
              <div className="text-xs text-gray-400 font-mono" title={sup.wallet_address}>
                {sup.wallet_address.slice(0, 8)}…
              </div>
            </div>
            {entries.length === 0 ? (
              <div className="px-4 py-6 text-center text-gray-400 text-sm">No products in catalog yet</div>
            ) : (
              <table className="w-full text-sm">
                <thead className="text-gray-500 text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-4 py-2 text-left">Product</th>
                    <th className="px-4 py-2 text-right">Unit Price (ALGO)</th>
                    <th className="px-4 py-2 text-right">Min Order</th>
                    <th className="px-4 py-2 text-center">Remove</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {entries.map(entry => (
                    <tr key={entry.id} className="bg-white hover:bg-gray-50">
                      <td className="px-4 py-2 font-medium text-gray-800">
                        {productMap[entry.product_id]?.name ?? `Product #${entry.product_id}`}
                        <span className="ml-1.5 text-xs text-gray-400">{productMap[entry.product_id]?.unit}</span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-gray-700">{entry.unit_price.toFixed(4)}</td>
                      <td className="px-4 py-2 text-right text-gray-500">{entry.min_order_qty}</td>
                      <td className="px-4 py-2 text-center">
                        <button
                          onClick={() => removeEntry(entry.id)}
                          className="text-red-400 hover:text-red-600 text-xs"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* Recent reviews */}
            {ratingInfo?.reviews?.length > 0 && (
              <div className="border-t border-gray-100 px-4 py-3 space-y-2">
                <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Recent Reviews</div>
                {ratingInfo.reviews.map(r => (
                  <div key={r.order_id} className="flex items-start gap-2">
                    <StarRating value={r.stars} size="sm" />
                    <div className="text-xs text-gray-500">
                      Order #{r.order_id}
                      {r.total_price && <span className="ml-1 text-gray-400">· {r.total_price.toFixed(4)} ALGO</span>}
                      {r.note && <span className="ml-2 text-gray-600 italic">"{r.note}"</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* Add catalog entry form */}
      <div className="rounded-lg border border-dashed border-gray-300 p-4 space-y-3">
        <div className="text-sm font-semibold text-gray-600">Add Catalog Entry</div>
        <form onSubmit={addEntry} className="flex flex-wrap gap-2 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Supplier</label>
            <select
              value={form.supplier_id}
              onChange={e => setForm(f => ({ ...f, supplier_id: e.target.value }))}
              className="px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              required
            >
              {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Product</label>
            <select
              value={form.product_id}
              onChange={e => setForm(f => ({ ...f, product_id: e.target.value }))}
              className="px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              required
            >
              <option value="">Select…</option>
              {products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Unit Price (ALGO)</label>
            <input
              type="number"
              step="0.0001"
              min="0.0001"
              value={form.unit_price}
              onChange={e => setForm(f => ({ ...f, unit_price: e.target.value }))}
              className="w-32 px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              placeholder="0.0500"
              required
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500">Min Order</label>
            <input
              type="number"
              min="1"
              value={form.min_order_qty}
              onChange={e => setForm(f => ({ ...f, min_order_qty: e.target.value }))}
              className="w-20 px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <Button type="submit" loading={saving} variant="primary" size="sm">
            + Add
          </Button>
        </form>
      </div>
    </div>
  )
}

// --- BLOCKCHAIN TAB ---

function BlockchainTab() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch('/blockchain/status')
      setStatus(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="py-16 text-center text-gray-400">Connecting to Algorand…</div>
  if (error) return (
    <div className="py-16 text-center">
      <div className="text-red-600 text-sm">{error}</div>
      <button onClick={load} className="mt-3 text-sm text-indigo-600 hover:underline">Retry</button>
    </div>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Algorand Network</h2>
        <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
      </div>
      <div className="rounded-lg border border-gray-200 divide-y divide-gray-100">
        {[
          ['Network',        status?.network ?? '—'],
          ['Buyer Address',  status?.buyer_address ?? '—'],
          ['Balance',        status?.balance_algo != null ? `${status.balance_algo.toFixed(4)} ALGO` : '—'],
          ['Latest Round',   status?.last_round ?? '—'],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between px-4 py-3 text-sm">
            <span className="text-gray-500">{label}</span>
            <span className="font-mono text-gray-800 break-all text-right max-w-xs">{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// --- ANALYTICS TAB ---

const PIE_COLORS = {
  pending:   '#fbbf24',
  funded:    '#60a5fa',
  delivered: '#a78bfa',
  released:  '#34d399',
  cancelled: '#f87171',
}

function KpiCard({ label, value, sub, accent }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-5 py-4">
      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${accent ?? 'text-gray-900'}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

function AnalyticsTab() {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await apiFetch('/analytics/summary'))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="py-16 text-center text-gray-400">Loading analytics…</div>
  if (error)   return (
    <div className="py-16 text-center">
      <div className="text-red-600 text-sm">{error}</div>
      <button onClick={load} className="mt-3 text-sm text-indigo-600 hover:underline">Retry</button>
    </div>
  )

  const { budget, kpis, orders_by_status, spending_by_supplier, top_products } = data

  const pieData = Object.entries(orders_by_status)
    .filter(([, v]) => v > 0)
    .map(([status, count]) => ({ name: status, value: count }))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Analytics</h2>
        <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Total Spent" value={`${kpis.total_spent.toFixed(2)} ALGO`} sub={`of ${budget.total.toFixed(2)} budget`} accent="text-indigo-700" />
        <KpiCard label="Budget Used" value={`${budget.pct_used}%`} sub={`${budget.remaining.toFixed(2)} ALGO remaining`} accent={budget.pct_used > 85 ? 'text-red-600' : 'text-emerald-600'} />
        <KpiCard label="Active Escrows" value={kpis.active_escrows} sub="funded + delivered" />
        <KpiCard label="Total Orders" value={kpis.total_orders} sub={`${kpis.cancelled_orders} cancelled`} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Spending per supplier */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-sm font-semibold text-gray-700 mb-3">Spending by Supplier (ALGO)</div>
          {spending_by_supplier.length === 0 ? (
            <div className="py-8 text-center text-gray-400 text-sm">No funded orders yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={spending_by_supplier} margin={{ left: -10 }}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => [`${v.toFixed(4)} ALGO`, 'Spent']} />
                <Bar dataKey="spent" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Orders by status pie */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-sm font-semibold text-gray-700 mb-3">Orders by Status</div>
          {pieData.length === 0 ? (
            <div className="py-8 text-center text-gray-400 text-sm">No orders yet</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={75} label={({ name, value }) => `${name} (${value})`} labelLine={false}>
                  {pieData.map(entry => (
                    <Cell key={entry.name} fill={PIE_COLORS[entry.name] ?? '#94a3b8'} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Top products */}
      {top_products.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 text-sm font-semibold text-gray-700">Product Overview</div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2 text-left">Product</th>
                <th className="px-4 py-2 text-right">Orders</th>
                <th className="px-4 py-2 text-right">Units Ordered</th>
                <th className="px-4 py-2 text-right">In Stock</th>
                <th className="px-4 py-2 text-right">Total Spent (ALGO)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {top_products.map(p => (
                <tr key={p.name} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-800">
                    {p.name}
                    <span className="ml-1.5 text-xs text-gray-400">{p.unit}</span>
                  </td>
                  <td className="px-4 py-2 text-right text-gray-600">{p.count}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-600">{p.units}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-600">{p.in_stock}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-700 font-semibold">{p.spent.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// --- PREDICTIONS TAB ---

const URGENCY = {
  critical: { label: 'Critical',     dot: 'bg-red-500',    row: 'bg-red-50',    text: 'text-red-700'    },
  warning:  { label: 'Soon',         dot: 'bg-amber-400',  row: 'bg-amber-50',  text: 'text-amber-700'  },
  ok:       { label: 'OK',           dot: 'bg-emerald-500',row: 'bg-white',     text: 'text-emerald-700'},
  no_data:  { label: 'No data',      dot: 'bg-gray-300',   row: 'bg-white',     text: 'text-gray-400'   },
}

// --- GLOBAL TIME SIMULATION BAR (visible on every tab) ---

function SimulationBar({ onTick }) {
  const [clock, setClock]         = useState(null)
  const [skipping, setSkipping]   = useState(false)
  const [resetting, setResetting] = useState(false)
  const [note, setNote]           = useState(null)

  const loadClock = useCallback(async () => {
    try { setClock(await apiFetch('/simulation/state')) } catch {}
  }, [])

  useEffect(() => { loadClock() }, [loadClock])

  async function skipDay() {
    setSkipping(true)
    setNote(null)
    try {
      const r = await apiFetch('/simulation/skip-day', { method: 'POST' })
      setClock({ sim_day: r.sim_day, started: true, current_sim_date: r.sim_date })
      const parts = []
      if (r.sales?.length) parts.push(`${r.sales.length} product(s) sold`)
      if (r.deliveries > 0) parts.push(`${r.deliveries} delivery(ies) 🚚`)
      if (r.orders_triggered > 0) parts.push(`${r.orders_triggered} reorder(s) ⚡`)
      setNote(`${r.sim_date}: ${parts.join(' · ') || 'no activity'}`)
      onTick()
    } catch (e) {
      setNote(e.message)
    } finally {
      setSkipping(false)
    }
  }

  async function reset() {
    if (!window.confirm('Reset the simulation? All sale events will be deleted.')) return
    setResetting(true)
    try {
      await apiFetch('/simulation/reset', { method: 'POST' })
      setClock({ sim_day: 0, started: false, current_sim_date: null })
      setNote(null)
      onTick()
    } finally {
      setResetting(false)
    }
  }

  const btn = 'inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

  return (
    <div className="bg-indigo-600 text-white px-6 py-2 flex items-center gap-3 text-sm">
      <span className="font-semibold whitespace-nowrap">⏱ Time Simulation</span>
      {clock?.started ? (
        <span className="bg-indigo-500/70 px-2 py-0.5 rounded-full font-mono text-xs whitespace-nowrap">
          Day {clock.sim_day} · {clock.current_sim_date}
        </span>
      ) : (
        <span className="text-indigo-200 text-xs whitespace-nowrap">Not started yet</span>
      )}
      {note && <span className="text-indigo-100 text-xs truncate hidden sm:block">{note}</span>}
      <div className="ml-auto flex gap-2">
        {clock?.started && (
          <button onClick={reset} disabled={resetting} className={`${btn} bg-indigo-500/60 hover:bg-indigo-500`}>
            {resetting && <span className="animate-spin">⟳</span>} ↺ Reset
          </button>
        )}
        <button onClick={skipDay} disabled={skipping} className={`${btn} bg-white text-indigo-700 hover:bg-indigo-50`}>
          {skipping && <span className="animate-spin">⟳</span>} ⏩ Skip 1 day
        </button>
      </div>
    </div>
  )
}

function PredictionsTab() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await apiFetch('/analytics/predictions'))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const predictions     = data?.predictions ?? []
  const monthly_budget_projection = data?.monthly_budget_projection ?? 0
  const critical = predictions.filter(p => p.urgency === 'critical').length
  const warning  = predictions.filter(p => p.urgency === 'warning').length
  const hasAny   = predictions.some(p => p.has_data)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Consumption Forecast</h2>
        <Button onClick={load} variant="ghost" size="sm">↻ Refresh</Button>
      </div>

      {loading && <div className="py-8 text-center text-gray-400 text-sm">Analyzing consumption data…</div>}
      {error && (
        <div className="py-4 text-center">
          <div className="text-red-600 text-sm">{error}</div>
          <button onClick={load} className="mt-2 text-sm text-indigo-600 hover:underline">Retry</button>
        </div>
      )}

      {!loading && !error && (<>
      {/* Summary KPIs */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-center">
          <div className="text-2xl font-bold text-red-600">{critical}</div>
          <div className="text-xs text-red-500 mt-0.5">Critical (&lt;3 days)</div>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-center">
          <div className="text-2xl font-bold text-amber-600">{warning}</div>
          <div className="text-xs text-amber-500 mt-0.5">Soon (&lt;7 days)</div>
        </div>
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3 text-center">
          <div className="text-2xl font-bold text-indigo-700">
            {monthly_budget_projection > 0 ? `${monthly_budget_projection.toFixed(2)}` : '—'}
          </div>
          <div className="text-xs text-indigo-400 mt-0.5">Proj. monthly cost (ALGO)</div>
        </div>
      </div>

      {!hasAny && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-700">
          <strong>No sales history yet.</strong> Simulate a few sales from the
          Inventory tab and come back — the forecasts will appear automatically.
        </div>
      )}

      {/* Predictions table */}
      <div className="overflow-hidden rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-4 py-3 text-left">Product</th>
              <th className="px-4 py-3 text-right">Stock</th>
              <th className="px-4 py-3 text-right">Usage/day</th>
              <th className="px-4 py-3 text-right">Stockout in</th>
              <th className="px-4 py-3 text-right">Reorder by</th>
              <th className="px-4 py-3 text-left">Cheapest supplier</th>
              <th className="px-4 py-3 text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {predictions.map(p => {
              const u = URGENCY[p.urgency]
              return (
                <tr key={p.product_id} className={u.row}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {p.product_name}
                    <span className="ml-1.5 text-xs text-gray-400">{p.unit}</span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {p.current_stock}
                    <span className="text-gray-400 text-xs"> / {p.reorder_point}</span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-600">
                    {p.has_data
                      ? <span title={`7d: ${p.velocity_7d ?? '—'}  30d: ${p.velocity_30d ?? '—'}`}>
                          {(p.velocity_7d ?? p.velocity_30d ?? 0).toFixed(2)}
                        </span>
                      : <span className="text-gray-300">—</span>
                    }
                  </td>
                  <td className={`px-4 py-3 text-right font-semibold ${u.text}`}>
                    {p.days_until_stockout != null
                      ? `${p.days_until_stockout} days`
                      : <span className="text-gray-300 font-normal">—</span>
                    }
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">
                    {p.reorder_by_date
                      ? <span className={p.urgency === 'critical' ? 'text-red-600 font-semibold' : ''}>
                          {new Date(p.reorder_by_date).toLocaleDateString('en-US', { day:'numeric', month:'short' })}
                        </span>
                      : <span className="text-gray-300">—</span>
                    }
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {p.best_supplier
                      ? <>
                          <span className="font-medium">{p.best_supplier}</span>
                          {p.best_price_algo && (
                            <span className="ml-1.5 text-xs text-gray-400">
                              {p.best_price_algo.toFixed(4)} ALGO
                            </span>
                          )}
                        </>
                      : <span className="text-gray-300">—</span>
                    }
                  </td>
                  <td className="px-4 py-3 text-center">
                    <div className="inline-flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${u.dot}`} />
                      <span className={`text-xs font-medium ${u.text}`}>{u.label}</span>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {hasAny && (
        <div className="text-xs text-gray-400 text-center">
          Velocity is based on the last 7 days (if available), otherwise the 30-day average.
          Sold in the last 7 days: {predictions.map(p => `${p.product_name.split(' ')[0]} ×${p.sold_last_7d}`).join(' · ')}
        </div>
      )}
      </>)}
    </div>
  )
}

// --- APP SHELL ---

const TABS = [
  { id: 'inventory',   label: '📦 Inventory' },
  { id: 'orders',      label: '📋 Orders' },
  { id: 'deliveries',  label: '🚚 Deliveries' },
  { id: 'suppliers',   label: '🏪 Suppliers' },
  { id: 'predictions', label: '🔮 Predictions' },
  { id: 'blockchain',  label: '⛓ Blockchain' },
  { id: 'analytics',   label: '📊 Analytics' },
]

export default function App() {
  const [tab, setTab] = useState('inventory')
  const [budgetKey, setBudgetKey] = useState(0)
  const [simTick, setSimTick]     = useState(0)

  function switchTab(next) {
    setTab(next)
  }

  function refreshBudget() {
    setBudgetKey(k => k + 1)
  }

  // Sim tick: refresh budget and force the active tab to reload its data.
  function handleTick() {
    setSimTick(k => k + 1)
    setBudgetKey(k => k + 1)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-2xl">🍸</span>
          <div>
            <h1 className="text-lg font-bold text-gray-900 leading-none">Bar Inventory</h1>
            <p className="text-xs text-gray-400">Automated reorder · Algorand escrow</p>
          </div>
        </div>
        <BudgetWidget refreshKey={`${tab}-${budgetKey}`} />
      </header>

      <nav className="bg-white border-b border-gray-200 px-6">
        <div className="flex">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => switchTab(t.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      <SimulationBar onTick={handleTick} />

      <main className="max-w-5xl mx-auto px-6 py-6">
        {tab === 'inventory'   && <InventoryTab key={simTick} onOrdersChanged={() => switchTab('orders')} />}
        {tab === 'orders'      && <OrdersTab key={simTick} onBudgetChanged={refreshBudget} />}
        {tab === 'deliveries'  && <DeliveriesTab key={simTick} onBudgetChanged={refreshBudget} />}
        {tab === 'suppliers'   && <SuppliersTab key={simTick} />}
        {tab === 'predictions' && <PredictionsTab key={simTick} />}
        {tab === 'blockchain'  && <BlockchainTab key={simTick} />}
        {tab === 'analytics'   && <AnalyticsTab key={simTick} />}
      </main>
    </div>
  )
}
