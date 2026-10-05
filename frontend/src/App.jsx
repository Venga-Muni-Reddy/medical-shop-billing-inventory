import React, { useEffect, useState, useCallback } from 'react'

const api = async (path, opts = {}) => {
  const isForm = opts.body instanceof FormData
  const r = await fetch('/api' + path, { credentials: 'same-origin', ...opts, headers: isForm ? {} : { 'Content-Type': 'application/json' } })
  const j = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Request failed (' + r.status + ')')
  return j
}
const post = (p, b) => api(p, { method: 'POST', body: b === undefined ? undefined : JSON.stringify(b) })
const put = (p, b) => api(p, { method: 'PUT', body: JSON.stringify(b) })
const money = n => n == null ? '-' : '₹' + Number(n).toFixed(2)
const fdate = d => d ? new Date(d + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '-'
const useHash = () => {
  const [h, setH] = useState(location.hash || '#/')
  useEffect(() => { const f = () => setH(location.hash || '#/'); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f) }, [])
  return h
}
const Ctx = React.createContext(null)
const go = p => { location.hash = p }

export default function App() {
  const h = useHash()
  const [user, setUser] = useState(undefined)
  useEffect(() => { api('/auth/me').then(r => setUser(r.email ? r : null)).catch(() => setUser(null)) }, [])
  if (user === undefined) return <main className="wrap"><p className="muted">Loading...</p></main>
  if (!user) return <Ctx.Provider value={{ setUser }}><AuthForm mode={h === '#/signup' ? 'signup' : 'login'} /></Ctx.Provider>
  const logout = async () => { await post('/auth/logout').catch(() => {}); setUser(null); go('#/') }
  const tabs = [['#/', 'Home'], ['#/sell', 'New sale'], ['#/purchases', 'Purchases'], ['#/inventory', 'Stock'], ['#/sales', 'Sales history'], ['#/settings', 'Settings']]
  const cur = tabs.find(t => t[0] !== '#/' && h.startsWith(t[0])) || tabs[0]
  let page = <Home />
  if (h.startsWith('#/purchases/')) page = <PurchaseEdit id={h.split('/')[2]} />
  else if (h === '#/purchases') page = <Purchases />
  else if (h === '#/sell') page = <Sell />
  else if (h === '#/inventory') page = <Inventory />
  else if (h === '#/sales') page = <Sales />
  else if (h === '#/settings') page = <SettingsPage />
  return (
    <Ctx.Provider value={{ user, setUser }}>
      <header className="top"><a href="#/" className="logo">💊 {user.shop_name || 'MedShop'}</a>
        <nav>{tabs.map(([p, l]) => <a key={p} href={p} className={cur[0] === p ? 'on' : ''}>{l}</a>)}<a href="#/" onClick={e => { e.preventDefault(); logout() }}>Log out</a></nav></header>
      <main className="wrap">{page}</main>
    </Ctx.Provider>
  )
}

function AuthForm({ mode }) {
  const { setUser } = React.useContext(Ctx)
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [shop, setShop] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const su = mode === 'signup'
  const submit = async e => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await post('/auth/' + mode, { email, password: pw, shop_name: shop }); const me = await api('/auth/me'); setUser(me); go('#/') }
    catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <main className="wrap narrow">
      <h2 style={{ textAlign: 'center', marginTop: 30 }}>💊 Medical Shop Billing &amp; Inventory</h2>
      <form className="card" onSubmit={submit}>
        <h3>{su ? 'Create owner account' : 'Owner login'}</h3>
        {su && <div className="f"><label>Shop name</label><input value={shop} onChange={e => setShop(e.target.value)} placeholder="e.g. Sri Sai Medicals" maxLength={100} /></div>}
        <div className="f"><label>Email</label><input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoComplete="email" /></div>
        <div className="f"><label>Password {su && '(8 to 72 characters)'}</label><input type="password" value={pw} onChange={e => setPw(e.target.value)} required minLength={su ? 8 : 1} maxLength={72} autoComplete={su ? 'new-password' : 'current-password'} /></div>
        <button className="btn" disabled={busy}>{busy ? 'Please wait...' : su ? 'Create account' : 'Log in'}</button>
        {err && <p className="err">{err}</p>}
      </form>
      <p className="muted" style={{ textAlign: 'center' }}>{su ? <>Already have an account? <a href="#/login">Log in</a></> : <>New shop? <a href="#/signup">Create owner account</a></>}</p>
    </main>
  )
}

function Home() {
  const [s, setS] = useState(null); const [a, setA] = useState(null)
  useEffect(() => { api('/summary').then(setS); api('/alerts').then(setA) }, [])
  if (!s) return <p className="muted">Loading...</p>
  return (
    <div>
      <h2>Today</h2>
      <div className="grid g4" style={{ marginBottom: 14 }}>
        <a className="stat" href="#/sales"><div className="n">{money(s.sales_today)}</div><span>Sales today ({s.bills_today} bills)</span></a>
        <a className="stat" href="#/inventory"><div className="n">{s.units}</div><span>Units in stock ({s.products} products)</span></a>
        <a className={'stat ' + (s.low_stock ? 'warn' : '')} href="#/inventory"><div className="n">{s.low_stock}</div><span>Low-stock products</span></a>
        <a className={'stat ' + (s.expired ? 'bad' : s.expiring ? 'warn' : '')} href="#/inventory"><div className="n">{s.expiring + s.expired}</div><span>Expiring / expired batches</span></a>
      </div>
      <div className="row" style={{ marginBottom: 16 }}>
        <a className="btn" href="#/sell">New sale</a><a className="btn ghost" href="#/purchases">Add supplier invoice</a>
      </div>
      {a && <AlertLists a={a} />}
      {s.products === 0 && <div className="hint">Start here: open <b>Purchases</b>, upload a supplier invoice (photo or PDF) and confirm it. Your stock will appear and you can start billing.</div>}
    </div>
  )
}

function AlertLists({ a }) {
  const none = !a.low_stock.length && !a.expiring.length && !a.expired.length
  if (none) return <div className="card okmsg">All good: no low-stock or near-expiry items.</div>
  return (
    <div className="split two">
      <div className="card"><h3>Expiring soon (within {a.expiry_warn_days} days) and expired</h3>
        {!a.expiring.length && !a.expired.length && <p className="muted">None.</p>}
        <div className="tw"><table><tbody>
          {a.expired.map(e => <tr key={e.id}><td><span className="tag t-exp">Expired</span></td><td>{e.name} {e.size}</td><td>Batch {e.batch_no}</td><td>{fdate(e.expiry)}</td><td>{e.qty_on_hand} left</td></tr>)}
          {a.expiring.map(e => <tr key={e.id}><td><span className="tag t-near">{e.days_left} days</span></td><td>{e.name} {e.size}</td><td>Batch {e.batch_no}</td><td>{fdate(e.expiry)}</td><td>{e.qty_on_hand} left</td></tr>)}
        </tbody></table></div></div>
      <div className="card"><h3>Low stock</h3>
        {!a.low_stock.length && <p className="muted">None.</p>}
        <div className="tw"><table><tbody>{a.low_stock.map(p => <tr key={p.id}><td><span className="tag t-low">Low</span></td><td>{p.name} {p.size}</td><td>{p.stock} in stock</td><td className="muted">alert at {p.threshold}</td></tr>)}</tbody></table></div></div>
    </div>
  )
}

function Purchases() {
  const [list, setList] = useState(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('')
  const load = () => api('/purchases').then(setList).catch(e => setErr(e.message))
  useEffect(() => { load() }, [])
  const [file, setFile] = useState(null); const [stage, setStage] = useState(''); const [pct, setPct] = useState(0); const [secs, setSecs] = useState(0)
  useEffect(() => { if (stage !== 'reading') return; setSecs(0); const t = setInterval(() => setSecs(x => x + 1), 1000); return () => clearInterval(t) }, [stage])
  const pick = e => { setFile(e.target.files[0] || null); setErr('') }
  const upload = () => {
    if (!file || busy) return
    setBusy(true); setErr(''); setStage('uploading'); setPct(0)
    const fd = new FormData(); fd.append('file', file)
    const x = new XMLHttpRequest(); x.open('POST', '/api/purchases/extract')
    x.upload.onprogress = ev => { if (ev.lengthComputable) setPct(Math.round(ev.loaded * 100 / ev.total)) }
    x.upload.onload = () => { setPct(100); setStage('reading') }
    x.onload = () => {
      let j = {}; try { j = JSON.parse(x.responseText) } catch (_) {}
      if (x.status >= 200 && x.status < 300) go('#/purchases/' + j.id)
      else { setErr(typeof j.detail === 'string' ? j.detail : 'Upload failed (' + x.status + ')'); setBusy(false); setStage('') }
    }
    x.onerror = () => { setErr('Network problem. Please try again.'); setBusy(false); setStage('') }
    x.send(fd)
  }
  const remove = async p => { if (!window.confirm('Delete draft #' + p.id + (p.supplier ? ' (' + p.supplier + ')' : '') + '? This cannot be undone.')) return; try { await api('/purchases/' + p.id, { method: 'DELETE' }); load() } catch (x) { setErr(x.message) } }
  const manual = async () => { const r = await post('/purchases'); go('#/purchases/' + r.id) }
  return (
    <div>
      <h2>Purchases (supplier invoices)</h2>
      <div className="card">
        <div className="drop">
          <p><b>Upload a supplier invoice</b></p>
          <p className="muted">Photo (JPG, PNG, WEBP) or PDF, up to 6 MB. Any layout. You review everything before it is saved.</p>
          {!busy && <input type="file" accept="image/*,application/pdf" onChange={pick} style={{ maxWidth: 320 }} />}
          {file && !busy && <p className="muted">Selected: <b>{file.name}</b> ({(file.size / 1024).toFixed(0)} KB)</p>}
          {!busy && <p><button className="btn" disabled={!file} onClick={upload}>Upload and read invoice</button></p>}
          {busy && <div className="prog">
            <div className="spin" />
            <div><b>{stage === 'uploading' ? 'Uploading ' + (file && file.name) + '... ' + pct + '%' : 'AI is reading your invoice... ' + secs + 's'}</b>
              <div className="bar"><div className={stage === 'reading' ? 'fill ind' : 'fill'} style={{ width: stage === 'reading' ? '100%' : pct + '%' }} /></div>
              <span className="muted">{stage === 'reading' ? 'This usually takes 20-60 seconds. Please keep this page open.' : 'Sending the file to the server.'}</span></div>
          </div>}
        </div>
        <p className="muted">No invoice file or the reading failed? <button className="btn ghost sm" onClick={manual}>Enter an invoice manually</button></p>
        {err && <p className="err">{err}</p>}
      </div>
      <div className="card tw">
        <table><thead><tr><th>#</th><th>Supplier</th><th>Invoice</th><th>Lines</th><th>Added by</th><th>Status</th><th></th></tr></thead>
          <tbody>{list && list.map(p => <tr key={p.id}><td>{p.id}</td><td>{p.supplier || '-'}</td><td>{p.invoice_no || '-'} {p.invoice_date && <span className="muted">({fdate(p.invoice_date)})</span>}</td><td>{p.lines}</td>
            <td>{p.source === 'ai' ? 'Uploaded file' : 'Typed in'}</td>
            <td>{p.status === 'draft' ? (p.source === 'ai' && !p.lines ? <span className="tag t-low">AI reading failed</span> : <span className="tag t-draft">Needs review</span>) : <span className="tag t-ok">In stock</span>}</td>
            <td style={{ whiteSpace: 'nowrap' }}><a className="btn ghost sm" href={'#/purchases/' + p.id}>{p.status === 'draft' ? 'Review' : 'View'}</a>{p.status === 'draft' && <> <button className="btn danger sm" onClick={() => remove(p)}>Delete</button></>}</td></tr>)}
            {list && !list.length && <tr><td colSpan={7} className="muted">No purchases yet.</td></tr>}</tbody></table>
      </div>
    </div>
  )
}

const blank = { name: '', size: '', batch_no: '', expiry: '', qty: 0, purchase_price: null, mrp: null }

function PurchaseEdit({ id }) {
  const [p, setP] = useState(null); const [d, setD] = useState(null); const [err, setErr] = useState(''); const [msg, setMsg] = useState(''); const [busy, setBusy] = useState(false)
  const load = useCallback(() => api('/purchases/' + id).then(r => { setP(r); setD(r.draft.items && r.draft.items.length === 0 && r.status === 'draft' ? { ...r.draft, items: [{ ...blank }] } : r.draft) }).catch(e => setErr(e.message)), [id])
  useEffect(() => { load() }, [load])
  if (!p || !d) return <p className={err ? 'err' : 'muted'}>{err || 'Loading...'}</p>
  const ro = p.status !== 'draft'
  const set = (k, v) => setD({ ...d, [k]: v })
  const setItem = (i, k, v) => setD({ ...d, items: d.items.map((it, j) => j === i ? { ...it, [k]: v } : it) })
  const numv = v => v === '' ? null : Number(v)
  const save = async () => { setBusy(true); setErr(''); setMsg(''); try { const r = await put('/purchases/' + id, d); setP(r); setD(r.draft); setMsg('Saved and re-checked.') } catch (x) { setErr(x.message) } finally { setBusy(false) } }
  const confirm = async () => {
    setBusy(true); setErr(''); setMsg('')
    try { await put('/purchases/' + id, d); await post('/purchases/' + id + '/confirm'); go('#/inventory') } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  const retry = async () => { setBusy(true); setErr(''); setMsg('Reading the invoice again with AI... up to a minute.'); try { const r = await post('/purchases/' + id + '/reextract'); setP(r); setD(r.draft.items.length ? r.draft : { ...r.draft, items: [{ ...blank }] }); setMsg(r.lines ? 'Done. Check the lines below.' : '') } catch (x) { setErr(x.message); setMsg('') } finally { setBusy(false) } }
  const del = async () => { if (confirm_('Delete this draft?')) { await api('/purchases/' + id, { method: 'DELETE' }); go('#/purchases') } }
  const confirm_ = m => window.confirm(m)
  const I = (k, props = {}) => <input value={d[k] ?? ''} onChange={e => set(k, e.target.value)} disabled={ro} {...props} />
  return (
    <div>
      <p><a href="#/purchases">&larr; All purchases</a></p>
      <h2>{ro ? 'Purchase #' + p.id : 'Review invoice #' + p.id}</h2>
      {p.source === 'ai' && !ro && <div className="hint">The AI filled this in from your file{p.extractor ? ' (' + p.extractor + ')' : ''}. AI can make mistakes: check each line against the document, fix anything wrong, then press <b>Confirm and add to stock</b>.</div>}
      {p.has_doc && !ro && p.source === 'ai' && <p><button className="btn ghost sm" disabled={busy} onClick={retry}>Read this file with AI again</button> <span className="muted">(free AI models are sometimes busy; you can also type the lines yourself)</span></p>}
      {p.source === 'manual' && !ro && <div className="hint">Manual entry: fill in the supplier and add each medicine line below, then press <b>Confirm and add to stock</b>.</div>}
      {p.warnings.length > 0 && !ro && <div className="warns"><b>Please check:</b><ul>{p.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></div>}
      <div className="split two">
        <div>
          <div className="card"><h3>Supplier</h3>
            <div className="f"><label>Supplier name *</label>{I('supplier_name')}</div>
            <div className="f"><label>Supplier address</label>{I('supplier_address')}</div>
            <h3 style={{ marginTop: 12 }}>Buyer (your shop)</h3>
            <div className="f"><label>Shop name</label>{I('buyer_name')}</div>
            <div className="f"><label>Shop address</label>{I('buyer_address')}</div>
            <div className="grid g2"><div className="f"><label>Invoice no.</label>{I('invoice_no')}</div><div className="f"><label>Invoice date</label>{I('invoice_date', { type: 'date' })}</div></div>
          </div>
        </div>
        {p.has_doc && <div><div className="card"><h3>Original document</h3>{p.filename && /\.pdf$/i.test(p.filename) ? <a href={'/api/purchases/' + id + '/document'} target="_blank" rel="noreferrer">Open the PDF</a> : <a href={'/api/purchases/' + id + '/document'} target="_blank" rel="noreferrer"><img className="docimg" src={'/api/purchases/' + id + '/document'} alt="Invoice" /></a>}</div></div>}
      </div>
        <div className="card tw" style={{ marginTop: 14 }}><h3>Medicines ({d.items.length})</h3>
          <table><thead><tr><th>Name *</th><th>Size</th><th>Batch *</th><th>Expiry *</th><th>Qty *</th><th>Buy price</th><th>MRP</th>{!ro && <th></th>}</tr></thead>
            <tbody>{d.items.map((it, i) => <tr key={i}>
              <td><input value={it.name} disabled={ro} onChange={e => setItem(i, 'name', e.target.value)} style={{ minWidth: 150 }} /></td>
              <td><input value={it.size} disabled={ro} onChange={e => setItem(i, 'size', e.target.value)} style={{ minWidth: 80 }} /></td>
              <td><input value={it.batch_no} disabled={ro} onChange={e => setItem(i, 'batch_no', e.target.value)} /></td>
              <td><input type="date" value={it.expiry} disabled={ro} onChange={e => setItem(i, 'expiry', e.target.value)} /></td>
              <td><input type="number" min="0" value={it.qty} disabled={ro} onChange={e => setItem(i, 'qty', Number(e.target.value))} style={{ width: 80 }} /></td>
              <td><input type="number" step="0.01" min="0" value={it.purchase_price ?? ''} disabled={ro} onChange={e => setItem(i, 'purchase_price', numv(e.target.value))} style={{ width: 90 }} /></td>
              <td><input type="number" step="0.01" min="0" value={it.mrp ?? ''} disabled={ro} onChange={e => setItem(i, 'mrp', numv(e.target.value))} style={{ width: 90 }} /></td>
              {!ro && <td><button className="link btn danger sm" onClick={() => set('items', d.items.filter((_, j) => j !== i))}>Remove</button></td>}</tr>)}</tbody></table>
          {!ro && <p><button className="btn ghost sm" onClick={() => set('items', [...d.items, { ...blank }])}>+ Add medicine line</button></p>}
        </div>
      {err && <p className="err">{err}</p>}{msg && <p className="okmsg">{msg}</p>}
      {!ro && <div className="row"><button className="btn" disabled={busy} onClick={confirm}>Confirm and add to stock</button><button className="btn ghost" disabled={busy} onClick={save}>Save and re-check</button><button className="btn danger" onClick={del}>Delete draft</button></div>}
      {ro && <p className="muted">This purchase is confirmed and its batches are in stock. Edit batch details from the Stock page.</p>}
    </div>
  )
}

function Inventory() {
  const [rows, setRows] = useState(null); const [f, setF] = useState('all'); const [q, setQ] = useState(''); const [edit, setEdit] = useState(null); const [err, setErr] = useState(''); const [empty, setEmpty] = useState(false)
  const load = () => api('/inventory' + (empty ? '?show_empty=true' : '')).then(setRows).catch(e => setErr(e.message))
  useEffect(() => { load() }, [empty])
  if (!rows) return <p className="muted">{err || 'Loading...'}</p>
  const shown = rows.filter(r => (f === 'all' || (f === 'low' && r.low_stock) || (f === 'near' && r.near_expiry) || (f === 'expired' && r.expired)) && q.toLowerCase().split(/\s+/).filter(Boolean).every(t => (r.name + ' ' + (r.size || '') + ' ' + r.batch_no + ' ' + (r.supplier || '')).toLowerCase().includes(t)))
  const saveEdit = async () => { try { await put('/batches/' + edit.id, { batch_no: edit.batch_no, expiry: edit.expiry, qty_on_hand: Number(edit.qty_on_hand), purchase_price: edit.purchase_price === '' ? null : edit.purchase_price, mrp: edit.mrp === '' ? null : edit.mrp }); setEdit(null); load() } catch (x) { setErr(x.message) } }
  const thr = async r => { const v = prompt('Low-stock alert level for ' + r.name + ' (leave empty to use the shop default):', ''); if (v === null) return; try { await put('/products/' + r.product_id + '/threshold', { low_stock_threshold: v === '' ? null : Number(v) }); load() } catch (x) { setErr(x.message) } }
  return (
    <div>
      <h2>Stock by batch</h2>
      <div className="row" style={{ marginBottom: 12 }}>
        {[['all', 'All'], ['low', 'Low stock'], ['near', 'Expiring soon'], ['expired', 'Expired']].map(([k, l]) => <button key={k} className={'btn sm ' + (f === k ? '' : 'ghost')} onClick={() => setF(k)}>{l}</button>)}
        <input placeholder="Search medicine, size, batch or supplier" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 300 }} />
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', margin: 0 }}><input type="checkbox" checked={empty} onChange={e => setEmpty(e.target.checked)} style={{ width: 'auto', minWidth: 0 }} /> Show sold-out batches</label>
      </div>
      {err && <p className="err">{err}</p>}
      <div className="card tw"><table><thead><tr><th>Medicine</th><th>Size</th><th>Batch</th><th>Expiry</th><th>In stock</th><th>Buy price</th><th>MRP</th><th>Supplier</th><th>Status</th><th></th></tr></thead>
        <tbody>{shown.map(r => edit && edit.id === r.id ? (
          <tr key={r.id}><td>{r.name}</td><td>{r.size}</td>
            <td><input value={edit.batch_no} onChange={e => setEdit({ ...edit, batch_no: e.target.value })} /></td>
            <td><input type="date" value={edit.expiry || ''} onChange={e => setEdit({ ...edit, expiry: e.target.value })} /></td>
            <td><input type="number" min="0" value={edit.qty_on_hand} onChange={e => setEdit({ ...edit, qty_on_hand: e.target.value })} style={{ width: 80 }} /></td>
            <td><input type="number" step="0.01" value={edit.purchase_price ?? ''} onChange={e => setEdit({ ...edit, purchase_price: e.target.value === '' ? '' : Number(e.target.value) })} style={{ width: 90 }} /></td>
            <td><input type="number" step="0.01" value={edit.mrp ?? ''} onChange={e => setEdit({ ...edit, mrp: e.target.value === '' ? '' : Number(e.target.value) })} style={{ width: 90 }} /></td>
            <td>{r.supplier}</td><td></td><td><button className="btn sm" onClick={saveEdit}>Save</button> <button className="btn ghost sm" onClick={() => setEdit(null)}>Cancel</button></td></tr>
        ) : (
          <tr key={r.id}><td><b>{r.name}</b></td><td>{r.size}</td><td>{r.batch_no}</td><td>{fdate(r.expiry)}</td><td>{r.qty_on_hand}</td><td>{money(r.purchase_price)}</td><td>{money(r.mrp)}</td><td>{r.supplier || '-'}</td>
            <td>{r.expired && <span className="tag t-exp">Expired</span>}{r.near_expiry && <span className="tag t-near">Expires in {r.days_left}d</span>}{r.low_stock && <span className="tag t-low">Low stock</span>}{!r.expired && !r.near_expiry && !r.low_stock && <span className="tag t-ok">OK</span>}</td>
            <td><button className="btn ghost sm" onClick={() => setEdit({ ...r })}>Edit</button> <button className="btn ghost sm" onClick={() => thr(r)}>Alert level</button></td></tr>))}
          {!shown.length && <tr><td colSpan={10} className="muted">{q ? 'No stock matches "' + q + '". ' + (empty ? '' : 'Tick "Show sold-out batches" to include medicines with 0 stock.') : 'Nothing to show.'}</td></tr>}</tbody></table></div>
    </div>
  )
}

function Sell() {
  const [q, setQ] = useState(''); const [res, setRes] = useState([]); const [cart, setCart] = useState([]); const [cust, setCust] = useState(''); const [err, setErr] = useState(''); const [done, setDone] = useState(null); const [busy, setBusy] = useState(false)
  const [soldOut, setSoldOut] = useState(false)
  useEffect(() => { let live = true; const t = setTimeout(() => api('/products/search?q=' + encodeURIComponent(q)).then(r => { if (!live) return; setRes(r); setSoldOut(false); if (!r.length && q.trim()) api('/inventory?show_empty=true').then(all => { if (live) setSoldOut(all.some(x => q.toLowerCase().split(/\s+/).filter(Boolean).every(w => (x.name + ' ' + (x.size || '') + ' ' + x.batch_no).toLowerCase().includes(w)))) }).catch(() => {}) }).catch(() => {}), 200); return () => { live = false; clearTimeout(t) } }, [q, done])
  const add = (p, b) => {
    if (cart.some(c => c.batch.id === b.id)) return
    setCart([...cart, { p, batch: b, qty: 1, price: b.mrp ?? b.purchase_price ?? 0 }]); setErr('')
  }
  const upd = (i, k, v) => setCart(cart.map((c, j) => j === i ? { ...c, [k]: v } : c))
  const total = cart.reduce((s, c) => s + c.qty * c.price, 0)
  const checkout = async () => {
    setBusy(true); setErr('')
    try { const r = await post('/sales', { customer: cust, lines: cart.map(c => ({ batch_id: c.batch.id, qty: Number(c.qty), unit_price: Number(c.price) })) }); setDone(r); setCart([]); setCust('') }
    catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <div>
      <h2>New sale</h2>
      {done && <div className="card okmsg"><b>Bill #{done.id} saved. Total {money(done.total)}.</b> Stock has been reduced. <button className="btn ghost sm" onClick={() => setDone(null)}>Start another</button></div>}
      <div className="split two">
        <div className="card"><h3>1. Find the medicine</h3>
          <input placeholder="Type medicine name, size or batch no." value={q} onChange={e => setQ(e.target.value)} autoFocus />
          {res.length === 0 && <p className="muted">{q ? (soldOut ? 'That medicine exists but has no sellable stock (sold out or expired). Add a purchase to restock it.' : 'No medicine matches "' + q + '". Try part of the name, size or batch number.') : 'No stock yet. Add a purchase first.'}</p>}
          {res.map(p => <div key={p.product_id} style={{ marginTop: 10 }}><b>{p.name}</b> <span className="muted">{p.size}</span>
            <div className="tw"><table><tbody>{p.batches.map(b => <tr key={b.id}><td>Batch {b.batch_no}</td><td>exp {fdate(b.expiry)}</td><td>{b.qty_on_hand} left</td><td>{money(b.mrp ?? b.purchase_price)}</td>
              <td><button className="btn sm" onClick={() => add(p, b)}>Add</button></td></tr>)}</tbody></table></div></div>)}
          <p className="muted">Batches are listed earliest expiry first. Pick the batch you are handing over.</p>
        </div>
        <div className="card"><h3>2. Bill</h3>
          {!cart.length && <p className="muted">Nothing added yet.</p>}
          {cart.length > 0 && <div className="tw"><table className="cart"><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Amount</th><th></th></tr></thead>
            <tbody>{cart.map((c, i) => <tr key={c.batch.id}><td>{c.p.name} {c.p.size}<br /><span className="muted">Batch {c.batch.batch_no}, {c.batch.qty_on_hand} left</span></td>
              <td><input type="number" min="1" max={c.batch.qty_on_hand} value={c.qty} onChange={e => upd(i, 'qty', e.target.value)} style={{ width: 70 }} /></td>
              <td><input type="number" min="0" step="0.01" value={c.price} onChange={e => upd(i, 'price', e.target.value)} style={{ width: 90 }} /></td>
              <td>{money(c.qty * c.price)}</td><td><button className="btn danger sm" onClick={() => setCart(cart.filter((_, j) => j !== i))}>x</button></td></tr>)}</tbody></table></div>}
          <div className="f" style={{ marginTop: 10 }}><label>Customer name (optional)</label><input value={cust} onChange={e => setCust(e.target.value)} maxLength={120} /></div>
          <h3>Total: {money(total)}</h3>
          {err && <p className="err">{err}</p>}
          <button className="btn" disabled={!cart.length || busy} onClick={checkout}>{busy ? 'Saving...' : 'Save bill and reduce stock'}</button>
        </div>
      </div>
    </div>
  )
}

function Sales() {
  const [rows, setRows] = useState(null)
  useEffect(() => { api('/sales').then(setRows) }, [])
  if (!rows) return <p className="muted">Loading...</p>
  return (
    <div><h2>Sales history</h2>
      {!rows.length && <p className="muted">No sales yet.</p>}
      {rows.map(s => <div className="card" key={s.id}><div className="row sp"><b>Bill #{s.id}{s.customer ? ' - ' + s.customer : ''}</b><span>{new Date(s.created_at).toLocaleString('en-GB')} &nbsp; <b>{money(s.total)}</b></span></div>
        <div className="tw"><table><tbody>{s.items.map(i => <tr key={i.id}><td>{i.product_name}</td><td>Batch {i.batch_no}</td><td>{i.qty} x {money(i.unit_price)}</td><td>{money(i.qty * i.unit_price)}</td></tr>)}</tbody></table></div></div>)}
    </div>
  )
}

function SettingsPage() {
  const { setUser } = React.useContext(Ctx)
  const [s, setS] = useState(null); const [err, setErr] = useState(''); const [msg, setMsg] = useState(''); const [a, setA] = useState(null)
  useEffect(() => { api('/settings').then(setS); api('/alerts').then(setA) }, [])
  if (!s) return <p className="muted">Loading...</p>
  const set = (k, v) => setS({ ...s, [k]: v })
  const save = async e => {
    e.preventDefault(); setErr(''); setMsg('')
    try { const r = await put('/settings', { ...s, expiry_warn_days: Number(s.expiry_warn_days), default_low_stock: Number(s.default_low_stock) }); setS(r); setMsg('Saved.'); api('/auth/me').then(setUser); api('/alerts').then(setA) } catch (x) { setErr(x.message) }
  }
  const test = async () => { setErr(''); setMsg(''); try { const r = await post('/alerts/test'); setMsg('Test email sent to ' + r.sent_to) } catch (x) { setErr(x.message) } }
  return (
    <div className="narrow" style={{ maxWidth: 640 }}>
      <h2>Settings and alerts</h2>
      <form className="card" onSubmit={save}>
        <h3>Shop</h3>
        <div className="f"><label>Shop name</label><input value={s.shop_name} onChange={e => set('shop_name', e.target.value)} maxLength={100} /></div>
        <div className="f"><label>Shop address</label><input value={s.shop_address} onChange={e => set('shop_address', e.target.value)} maxLength={300} /></div>
        <h3 style={{ marginTop: 14 }}>Alerts</h3>
        <div className="grid g2">
          <div className="f"><label>Warn me this many days before expiry</label><input type="number" min="1" max="730" value={s.expiry_warn_days} onChange={e => set('expiry_warn_days', e.target.value)} /></div>
          <div className="f"><label>Default low-stock level (units)</label><input type="number" min="0" value={s.default_low_stock} onChange={e => set('default_low_stock', e.target.value)} /></div>
        </div>
        <p className="muted" style={{ marginTop: 0 }}>You can set a different low-stock level for one medicine from the Stock page ("Alert level").</p>
        <div className="f"><label>Send alert emails to</label><input type="email" value={s.alert_email} onChange={e => set('alert_email', e.target.value)} /></div>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 15, color: '#17302b' }}><input type="checkbox" checked={s.email_alerts} onChange={e => set('email_alerts', e.target.checked)} style={{ width: 'auto' }} /> Email me about expiring and low-stock items</label>
        <p className="muted">{s.email_provider ? 'Email sending is set up on the server. Alerts are checked daily and each item is emailed once.' : 'Email sending is not set up on the server yet, so alerts show in the app only.'}</p>
        <div className="row"><button className="btn">Save settings</button><button type="button" className="btn ghost" onClick={test} disabled={!s.email_provider}>Send test email</button></div>
        {err && <p className="err">{err}</p>}{msg && <p className="okmsg">{msg}</p>}
      </form>
      {a && <div><h3>Current alerts (in app)</h3><AlertLists a={a} /></div>}
    </div>
  )
}
