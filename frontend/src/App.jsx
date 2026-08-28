import React, { useState, useEffect, useRef } from 'react'

const BASE = '/api'          // vite 代理到 FastAPI
const GOODS = [
  { gid: '', label: '（全店通用）' },
  { gid: 'G10086', label: 'G10086 · 星野 T5 耳机' },
  { gid: 'G20077', label: 'G20077 · 星野 Note 12 手机' },
]

function Message({ m }) {
  return (
    <div className={"msg " + (m.role === 'user' ? 'user' : 'bot')}>
      {m.text}
      {m.meta && (
        <div className="meta">
          {m.meta.human ? <span className="tag human">转人工</span>
                         : <span className="tag kb">知识库命中</span>}
          {m.meta.score != null && <span className="tag score">相关度 {m.meta.score.toFixed(2)}</span>}
          {m.meta.sources && <div style={{marginTop:6, fontSize:11, color:'#7c8aa5'}}>来源：{m.meta.sources.join('、')}</div>}
          {m.meta.reason && m.meta.human && <div style={{marginTop:4, fontSize:11, color:'#fca5a5'}}>原因：{m.meta.reason}</div>}
        </div>
      )}
    </div>
  )
}

function SellerPanel() {
  const [stats, setStats] = useState(null)
  useEffect(() => {
    fetch(`${BASE}/stat/get`)
      .then(r => r.json())
      .then(d => setStats(d)).catch(() => {})
  }, [])
  const cards = stats ? [
    ['总问答量', stats.total_qa],
    ['转人工率', stats.need_human_rate != null ? stats.need_human_rate.toFixed(1) + '%' : '—'],
    ['知识库未命中', stats.kb_miss_count],
    ['平均延迟', stats.avg_latency_ms != null ? stats.avg_latency_ms + 'ms' : '—'],
  ] : []
  return (
    <aside className="stats">
      <div className="s-title">观测统计</div>
      {cards.map(([l, v]) => (
        <div className="stat-card" key={l}>
          <div className="v">{v}</div>
          <div className="l">{l}</div>
        </div>
      ))}
      {stats && (
        <div className="stat-card">
          <div className="l" style={{marginBottom:6}}>转人工原因 Top</div>
          {(stats.top_human_reasons || []).slice(0, 4).map(r =>
            <div key={r.reason} style={{fontSize:12, color:'#cdd6e6', padding:'2px 0'}}>{r.reason} · {r.cnt} 次</div>)}
        </div>
      )}
    </aside>
  )
}

export default function App() {
  const [sessionId, setSessionId] = useState('web_001')
  const [goodsId, setGoodsId] = useState('G10086')
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState([])
  const [busy, setBusy] = useState(false)
  const [kb, setKb] = useState(null)
  const chatRef = useRef(null)

  useEffect(() => { fetch(`${BASE}/health`).then(r=>r.json()).then(setKb).catch(()=>{}) }, [])
  useEffect(() => { chatRef.current && (chatRef.current.scrollTop = chatRef.current.scrollHeight) }, [msgs])

  async function send(extraText) {
    const text = (extraText || input).trim()
    if (!text || busy) return
    setMsgs(p => [...p, { role: 'user', text }])
    if (!extraText) setInput('')
    setBusy(true)
    const payload = { session_id: sessionId, query: text, goods_id: goodsId }
    try {
      const resp = await fetch(`${BASE}/rag/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      })
      const d = await resp.json()
      setMsgs(p => [...p, {
        role: 'bot', text: d.answer || '（无返回）',
        meta: { human: !!d.need_human, reason: d.human_reason, score: d.top_score, sources: d.sources },
      }])
    } catch (e) {
      setMsgs(p => [...p, { role: 'bot', text: '请求失败：' + String(e) }])
    } finally { setBusy(false) }
  }

  return (
    <div className="console">
      <aside className="sidebar">
        <div className="brand">
          <h1>星野数码 · 智能客服</h1>
          <p>电商 RAG 智能客服控制台</p>
        </div>
        <div className="kb-box">
          <div className="title">知识库状态</div>
          <div className="kb-row"><span>向量库</span><span>{kb && kb.code === 0 ? '正常' : '检测中' }</span></div>
          <div className="kb-row"><span>知识片段</span><span>{kb ? kb.kb_chunk_total + ' 条' : '—'}</span></div>
        </div>
        <div className="sessions">
          <div className="title" style={{fontSize:12, color:'#8b96ad', padding:'4px 10px'}}>会话历史</div>
          {['web_001', 'web_002', 'web_003'].map(s => (
            <div key={s} className={"session" + (s === sessionId ? ' active' : '')} onClick={() => setSessionId(s)}>
              会话 {s}
            </div>
          ))}
        </div>
      </aside>

      <section className="main">
        <div className="topbar">
          <span className="htitle">会话 {sessionId}</span>
          <span className="badge on">在线客服</span>
          <span className="badge wait">人工接管可用</span>
        </div>
        <div className="chat" ref={chatRef}>
          {msgs.length === 0 && (
            <div style={{color:'#7c8aa5', fontSize:13, textAlign:'center', marginTop:60}}>
              请输入您的问题，例如「这个耳机能续航多久？」；系统会按所选商品做元数据过滤检索。
            </div>
          )}
          {msgs.map((m, i) => <Message key={i} m={m} />)}
        </div>
        <div className="inputbar">
          <select value={goodsId} onChange={e => setGoodsId(e.target.value)}>
            {GOODS.map(g => <option key={g.gid} value={g.gid}>{g.label}</option>)}
          </select>
          <input value={input} placeholder="输入问题，回车发送…" onChange={e => setInput(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && send()} />
          <button disabled={busy} onClick={() => send()}>{busy ? '回复中…' : '发送'}</button>
        </div>
      </section>

      <SellerPanel />
    </div>
  )
}