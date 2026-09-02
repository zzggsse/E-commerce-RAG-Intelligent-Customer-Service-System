import React, { useState, useEffect, useRef } from 'react'

const BASE = '/api'          // vite 代理到 FastAPI

function newSessionId() {
  return 'web_' + Date.now().toString(36)
}

function Message({ m }) {
  return (
    <div className={"msg " + (m.role === 'user' ? 'user' : 'bot')}>
      {m.text}
      {m.meta && (
        <div className="meta">
          {m.meta.human ? <span className="tag human">转人工</span>
            : m.meta.kind === 'reco' ? <span className="tag reco">智能推荐</span>
            : m.meta.kind === 'clarify' ? <span className="tag clarify">请确认</span>
            : <span className="tag kb">知识库命中</span>}
          {m.meta.kind !== 'reco' && m.meta.kind !== 'clarify' && m.meta.score != null && <span className="tag score">相关度 {m.meta.score.toFixed(2)}</span>}
          {m.meta.sources && <div style={{marginTop:6, fontSize:11, color:'#626260'}}>来源：{m.meta.sources.join('、')}</div>}
          {m.meta.reason && m.meta.human && <div style={{marginTop:4, fontSize:11, color:'#b3261e'}}>原因：{m.meta.reason}</div>}
        </div>
      )}
    </div>
  )
}

function SellerPanel() {
  const [stats, setStats] = useState(null)
  const [days, setDays] = useState(7)
  const refreshStats = () =>
    fetch(`${BASE}/stat/get?days=${days}`)
      .then(r => r.json())
      .then(d => setStats(d)).catch(() => {})
  const clearStats = () => {
    fetch(`${BASE}/stat/clear`, { method: 'POST' })
      .then(r => r.json())
      .then(() => refreshStats()).catch(() => {})
  }
  useEffect(() => {
    refreshStats()
    const timer = setInterval(refreshStats, 5000)
    return () => clearInterval(timer)
  }, [days])
  const cards = stats ? [
    ['总问答量', stats.total_qa],
    ['转人工率', stats.need_human_rate != null ? stats.need_human_rate.toFixed(1) + '%' : '—'],
    ['知识库未命中', stats.kb_miss_count],
    ['平均延迟', stats.avg_latency_ms != null ? stats.avg_latency_ms + 'ms' : '—'],
  ] : []
  return (
    <aside className="stats">
      <div className="s-title" style={{display:'flex', justifyContent:'space-between', alignItems:'center', gap:8}}>
        <span>观测统计</span>
        <span style={{display:'flex', gap:6, alignItems:'center'}}>
          <span className="stat-toggle">
            <button className={days === 1 ? 'active' : ''} onClick={() => setDays(1)}>今日</button>
            <button className={days === 7 ? 'active' : ''} onClick={() => setDays(7)}>近7天</button>
          </span>
          <button className="clear-stats" onClick={clearStats}>清空</button>
        </span>
      </div>
      {cards.map(([l, v]) => (
        <div className="stat-card" key={l}>
          <div className="v">{v}</div>
          <div className="l">{l}</div>
        </div>
      ))}
      {stats && (
        <div className="stat-card">
          <div className="l" style={{marginBottom:6}}>转人工原因 Top</div>
          {(stats.top_human_reasons || []).length === 0
            ? <div className="reason" style={{color:'#9c9fa5'}}>暂无转人工</div>
            : (stats.top_human_reasons || []).slice(0, 4).map(r =>
                <div key={r.reason} className="reason">{r.reason} · {r.cnt} 次</div>)}
        </div>
      )}
    </aside>
  )
}

function typeLabel(t) { return ({ goods: '商品', aftersale: '售后' }[t] || t || '未分类') }

function KbManager({ onBrandChange }) {
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(false)
  const [kw, setKw] = useState('')
  const [dtype, setDtype] = useState('')
  const [hits, setHits] = useState(null)
  const [msg, setMsg] = useState('')
  const [files, setFiles] = useState([])
  const [uType, setUType] = useState('goods')
  const [uGid, setUGid] = useState('')
  const [uploading, setUploading] = useState(false)
  const [bName, setBName] = useState('')

  const refresh = () => {
    setLoading(true)
    fetch(`${BASE}/document/sources`)
      .then(r => r.json())
      .then(d => { if (d && Array.isArray(d.documents)) setSources(d.documents) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }
  useEffect(refresh, [])

  async function doSearch(ev) {
    ev && ev.preventDefault()
    const body = new URLSearchParams({ keyword: kw, doc_type: dtype })
    const d = await fetch(`${BASE}/document/search`, {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body,
    }).then(r => r.json()).catch(() => {})
    setHits(d && Array.isArray(d.hits) ? d.hits : [])
  }

  async function saveBrand() {
    const body = new URLSearchParams({ brand_name: bName })
    const d = await fetch(`${BASE}/config/brand`, {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body,
    }).then(r => r.json()).catch(() => {})
    setMsg(d && d.brand ? '品牌已设置为：' + d.brand : '品牌已留空（保存后，上传含“品牌：XXX”的内容会自动识别）')
    onBrandChange && onBrandChange()
  }

  async function doUpload(ev) {
    ev.preventDefault()
    if (uploading || files.length === 0) return
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    fd.append('doc_type', uType)
    if (uGid.trim()) fd.append('goods_id', uGid.trim())
    setUploading(true)
    try {
      const d = await fetch(`${BASE}/document/upload`, { method: 'POST', body: fd }).then(r => r.json()).catch(() => {})
      if (d && d.code === 0) {
        let txt = `成功入库 ${d.total_chunks} 条切片`
        const repl = (d.detail || []).filter(x => x.replaced_sources && x.replaced_sources.length)
        const replTotal = (repl || []).reduce((a, x) => a + (x.replaced_sources || []).length, 0)
        if (replTotal) txt += `；已自动替换合并 ${replTotal} 份旧副本`
        setMsg(txt)
      } else {
        setMsg('上传失败：' + JSON.stringify(d || {}))
      }
      refresh()
      onBrandChange && onBrandChange()
    } catch (e) {
      setMsg('上传失败：' + String(e))
    } finally {
      setUploading(false)
      setFiles([])
    }
  }

  async function del(source, goodsId, docType) {
    if (!window.confirm('确定删除文档「' + source + '」的全部切片吗？')) return
    const body = new URLSearchParams({ source, goods_id: goodsId || '', doc_type: docType || '' })
    const d = await fetch(`${BASE}/document/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body,
    }).then(r => r.json()).catch(() => {})
    setMsg(d && d.detail ? d.detail : '已删除')
    refresh()
  }

  const groupHits = () => {
    const g = {}
    ;(hits || []).forEach(h => {
      const k = (h.source || '') + '|' + (h.goods_id || '') + '|' + (h.doc_type || '')
      ;(g[k] = g[k] || { source: h.source, goods_id: h.goods_id, doc_type: h.doc_type, items: [] }).items.push(h)
    })
    return Object.values(g)
  }

  return (
    <div className="kb-manager">
      <div className="kb-header">
        <form className="kb-search" onSubmit={doSearch}>
          <input value={kw} placeholder="输入关键词检索知识库内容，如：双十一、售后期、运费险" onChange={e => setKw(e.target.value)} />
          <select className="kb-stype" value={dtype} onChange={e => setDtype(e.target.value)}>
            <option value="">全部类型</option>
            {Array.from(new Set((sources || []).map(x => x.doc_type).filter(Boolean))).map(t => (
              <option key={t} value={t}>{typeLabel(t)}</option>
            ))}
          </select>
          <button type="submit">检索</button>
        </form>
        <button className="kb-refresh" onClick={refresh}>{loading ? '刷新中…' : '刷新列表'}</button>
      </div>

      <div className="kb-brandline">
        <span className="kb-brandlabel">客服标题品牌</span>
        <input value={bName} placeholder="留空则待上传时自动识别" onChange={e => setBName(e.target.value)} />
        <button className="kb-brbtn" onClick={saveBrand}>保存品牌</button>
        <span className="kb-brand-hint">上传含「品牌：XXX」的商品内容会自动识别并替换标题</span>
      </div>

      <form className="kb-upload" onSubmit={doUpload}>
        <label className="kb-file">
          <input type="file" multiple accept=".md,.markdown,.txt,.pdf,.docx,.csv,.tsv" onChange={e => setFiles([...e.target.files])} />
          <span>{files.length ? `已选 ${files.length} 个文件` : '选择文件'}</span>
        </label>
        <input className="kb-type" value={uType} placeholder="文档类型，如：商品、售后、物流、退换货、发票、运费险…（可自由填写）" onChange={e => setUType(e.target.value)} />
        <input className="kb-gid" value={uGid} placeholder="商品编号(可选，商品资料建议填写，通用文档留空)" onChange={e => setUGid(e.target.value)} />
        <button className="kb-upbtn" disabled={uploading || files.length === 0}>{uploading ? '上传中…' : '上传并自动替换'}</button>
      </form>

      {msg && <div className="kb-msg">{msg}</div>}

      <div className="kb-body">
        <div className="kb-section">
          <div className="kb-section-title">全部文档（{sources.length}）</div>
          {sources.length === 0
            ? <div className="kb-empty">知识库暂无文档，请先上传。</div>
            : (
              <table className="kb-table">
                <thead><tr><th>文件名</th><th>类型</th><th>商品</th><th>切片数</th><th></th></tr></thead>
                <tbody>
                  {sources.map((s, i) => (
                    <tr key={i}>
                      <td className="src">{s.source}</td>
                      <td><span className="kb-tag">{typeLabel(s.doc_type)}</span></td>
                      <td>{s.goods_id || '—'}</td>
                      <td>{s.chunk_count}</td>
                      <td><button className="kb-del" onClick={() => del(s.source, s.goods_id, s.doc_type)}>删除</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>

        {hits !== null && (
          <div className="kb-section">
            <div className="kb-section-title">检索结果（{hits.length} 条切片）</div>
            {hits.length === 0
              ? <div className="kb-empty">没有匹配到「{kw}」，试试其他关键词。</div>
              : groupHits().map(g => (
                <div className="kb-hit-group" key={g.source}>
                  <div className="kb-hit-head">
                    <span className="src">{g.source}</span>
                    <span className="kb-meta">{typeLabel(g.doc_type)}{g.goods_id ? ' · ' + g.goods_id : ''} · {g.items.length} 条</span>
                    <button className="kb-del" onClick={() => del(g.source, g.goods_id, g.doc_type)}>删除该文档</button>
                  </div>
                  {g.items.map((h, i) => (
                    <div className="kb-hit" key={i}>{h.content}</div>
                  ))}
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState([])
  const [busy, setBusy] = useState(false)
  const [kb, setKb] = useState(null)
  const [view, setView] = useState('chat')
  const [brand, setBrand] = useState('')
  const asrEnabled = !!(kb && kb.asr_enabled)
  const chatRef = useRef(null)
  const [listening, setListening] = useState(false)
  const recRef = useRef(null)

  const refreshSessions = () => {
    fetch(`${BASE}/session/list`)
      .then(r => r.json())
      .then(d => { if (d && Array.isArray(d.sessions)) setSessions(d.sessions) })
      .catch(() => {})
  }

  const loadBrand = () => {
    fetch(`${BASE}/config/brand`)
      .then(r => r.json())
      .then(d => { if (d && d.brand) setBrand(d.brand) })
      .catch(() => {})
  }

  const loadSession = (id, thenSelect) => {
    fetch(`${BASE}/session/detail?session_id=${encodeURIComponent(id)}`)
      .then(r => r.json())
      .then(d => { if (d && Array.isArray(d.messages)) setMsgs(d.messages) })
      .catch(() => setMsgs([]))
      .finally(() => { if (thenSelect) setSessionId(id) })
  }

  // 首次：拉健康状态 + 会话列表，选中最近一个；没有则新建
  useEffect(() => {
    fetch(`${BASE}/health`).then(r => r.json()).then(setKb).catch(() => {})
    loadBrand()
    fetch(`${BASE}/session/list`)
      .then(r => r.json())
      .then(d => {
        const list = (d && Array.isArray(d.sessions)) ? d.sessions : []
        setSessions(list)
        if (list.length > 0) {
          loadSession(list[0].session_id, true)
        } else {
          setSessionId(newSessionId())
        }
      })
      .catch(() => setSessionId(newSessionId()))
  }, [])

  useEffect(() => {
    chatRef.current && (chatRef.current.scrollTop = chatRef.current.scrollHeight)
  }, [msgs])

  function selectSession(id) {
    if (id === sessionId) return
    loadSession(id, true)
  }

  function newSession() {
    setSessionId(newSessionId())
    setMsgs([])
  }

  // 语音输入：优先走后端 /asr 接口（需在 .env 配置 ASR_API_KEY），否则用浏览器内置识别
  function toggleVoice() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    const useApi = asrEnabled && (navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
    if (!useApi && !SR) { alert('当前浏览器不支持语音输入，请使用 Chrome / Edge 新版'); return }
    if (recRef.current && listening) { recRef.current.stop && recRef.current.stop(); setListening(false); return }
    if (useApi) {
      navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        const rec = new MediaRecorder(stream)
        const chunks = []
        rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data) }
        rec.onstop = async () => {
          setListening(false)
          stream.getTracks().forEach(t => t.stop())
          const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' })
          const fd = new FormData()
          fd.append('file', blob, 'voice.webm')
          try {
            const d = await fetch(BASE + '/asr', { method: 'POST', body: fd }).then(r => r.json())
            if (d && d.code === 0 && d.text) setInput(prev => (prev ? prev + ' ' + d.text : d.text))
            else alert(d && d.msg ? d.msg : '未识别到语音')
          } catch (err) { alert('语音识别失败：' + err) }
        }
        recRef.current = { stop: () => { if (rec.state !== 'inactive') rec.stop() }, _rec: rec }
        setListening(true)
        rec.start(1000)
      }).catch(() => alert('无法获取麦克风权限'))
      return
    }
    const rec = new SR()
    rec.lang = 'zh-CN'
    rec.interimResults = false
    rec.maxAlternatives = 1
    rec.onresult = (e) => {
      const t = Array.from(e.results).map(r => r[0].transcript).join('')
      setInput(prev => (prev ? prev + ' ' + t : t))
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recRef.current = rec
    setListening(true)
    try { rec.start() } catch (_) { setListening(false) }
  }

  async function send(extraText) {
    const text = (extraText || input).trim()
    if (!text || busy) return
    const sid = sessionId || newSessionId()
    if (!sessionId) setSessionId(sid)
    setMsgs(p => [...p, { role: 'user', text }])
    if (!extraText) setInput('')
    setBusy(true)
    const payload = { session_id: sid, query: text }
    try {
      const resp = await fetch(`${BASE}/rag/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      })
      const d = await resp.json()
      setMsgs(p => [...p, {
        role: 'bot', text: d.answer || '（无返回）',
        meta: { human: !!d.need_human, reason: d.human_reason, score: d.top_score, sources: d.sources, kind: d.kind },
      }])
    } catch (e) {
      setMsgs(p => [...p, { role: 'bot', text: '请求失败：' + String(e) }])
    } finally {
      setBusy(false)
      refreshSessions()
    }
  }

  function sessionLabel(s) {
    const q = (s.last_query || '').trim()
    if (q) return q.slice(0, 16) + (q.length > 16 ? '…' : '')
    return '会话 ' + (s.session_id || '?')
  }

  return (
    <div className={"console" + (view === 'kb' ? ' console-kb' : '')}>
      <aside className="sidebar">
        <div className="nav">
          <button className={"nav-btn" + (view === 'chat' ? ' active' : '')} onClick={() => setView('chat')}>客服对话</button>
          <button className={"nav-btn" + (view === 'kb' ? ' active' : '')} onClick={() => setView('kb')}>知识库管理</button>
        </div>
        <div className="brand">
          <h1>{brand ? brand + ' · 智能客服' : '您的品牌 · 智能客服'}</h1>
          <p>电商 RAG 智能客服控制台</p>
        </div>
        <div className="kb-box">
          <div className="title">知识库状态</div>
          <div className="kb-row"><span>向量库</span><span>{kb && kb.code === 0 ? '正常' : '检测中'}</span></div>
          <div className="kb-row"><span>知识片段</span><span>{kb ? kb.kb_chunk_total + ' 条' : '—'}</span></div>
        </div>
        <div className="sessions">
          <div className="title" style={{fontSize:12, padding:'4px 10px'}}>会话历史</div>
          <button className="new-session" onClick={newSession}>＋ 新会话</button>
          {sessions.length === 0 && <div className="session-hint">暂无历史会话，点击上方新建</div>}
          {sessions.map(s => (
            <div key={s.session_id} className={"session" + (s.session_id === sessionId ? ' active' : '')}
                 onClick={() => selectSession(s.session_id)}>
              {sessionLabel(s)}
            </div>
          ))}
        </div>
      </aside>

      {view === 'chat' ? (<>
      <section className="main">
        <div className="topbar">
          <span className="htitle">会话 {sessionId || '…'}</span>
          <span className="badge on">在线客服</span>
          <span className="badge wait">人工接管可用</span>
        </div>
        <div className="chat" ref={chatRef}>
          {msgs.length === 0 && (
            <div className="empty">
              请输入您的问题，例如「这个耳机能续航多久？」；系统会按所选商品做元数据过滤检索。
            </div>
          )}
          {msgs.map((m, i) => <Message key={i} m={m} />)}
        </div>
        <div className="inputbar">
          <input value={input} placeholder="输入问题，回车发送（点击话筒可直接语音输入）" onChange={e => setInput(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && send()} />
          <button type="button" className={"mic-btn" + (listening ? ' on' : '')} onClick={toggleVoice} title="语音输入" disabled={busy}>{listening ? '●●●' : '🎤'}</button>
          <button disabled={busy} onClick={() => send()}>{busy ? '回复中…' : '发送'}</button>
        </div>
      </section>

      <SellerPanel />
      </>) : (
      <main className="kb-main">
        <KbManager onBrandChange={loadBrand} />
      </main>
      )}
    </div>
  )
}
