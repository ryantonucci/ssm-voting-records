import { useState, useRef, useEffect } from 'react'

const API_URL = import.meta.env.VITE_CHAT_API_URL || 'http://localhost:5001/api/chat'

const MIN_HEIGHT = 90
const MAX_HEIGHT = 480

export default function ChatWidget() {
  const [messages, setMessages] = useState([])
  const [history, setHistory] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setError(null)
    setMessages((m) => [...m, { role: 'user', content: text }])
    setLoading(true)
    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Request failed')
      setMessages((m) => [...m, { role: 'assistant', content: data.reply }])
      setHistory(data.history || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section style={{ marginTop: 56 }}>
      <div style={{ borderBottom: '1px solid oklch(0.15 0 0)', paddingBottom: 12, marginBottom: 20 }}>
        <div
          style={{
            fontSize: 13,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'oklch(0.45 0 0)',
            marginBottom: 6,
          }}
        >
          Ask about council
        </div>
        <p style={{ fontSize: 14, color: 'oklch(0.4 0 0)', margin: 0 }}>
          e.g. "what has Councillor Gardi moved recently?" or "has anything been defeated this term?"
        </p>
      </div>

      <div style={{ border: '1px solid oklch(0.15 0 0)' }}>
        <div
          ref={scrollRef}
          style={{
            minHeight: messages.length === 0 ? MIN_HEIGHT : undefined,
            maxHeight: MAX_HEIGHT,
            overflowY: 'auto',
            padding: messages.length === 0 ? '20px 20px' : '16px 20px',
            transition: 'min-height 0.15s ease',
          }}
        >
          {messages.length === 0 && (
            <p style={{ fontSize: 13, color: 'oklch(0.45 0 0)', margin: 0 }}>
              No questions yet — type one below.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} style={{ marginBottom: 16 }}>
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  color: 'oklch(0.45 0 0)',
                  marginBottom: 4,
                }}
              >
                {m.role === 'user' ? 'You' : 'Assistant'}
              </div>
              <div style={{ fontSize: 14, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{m.content}</div>
            </div>
          ))}
          {loading && (
            <div style={{ fontSize: 13, color: 'oklch(0.45 0 0)', fontStyle: 'italic' }}>Thinking…</div>
          )}
          {error && (
            <div style={{ fontSize: 13, color: 'oklch(0.15 0 0)', marginTop: 8 }}>
              Error: {error}. Is the chatbot backend running (chatbot/server.py)?
            </div>
          )}
        </div>

        <div style={{ borderTop: '1px solid oklch(0.9 0 0)', padding: 12, display: 'flex', gap: 10 }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send()
            }}
            placeholder="Ask a question…"
            style={{
              flex: 1,
              fontSize: 14,
              padding: '10px 12px',
              border: '1px solid oklch(0.9 0 0)',
              fontFamily: 'inherit',
              background: 'oklch(0.98 0 0)',
            }}
          />
          <button
            onClick={send}
            disabled={loading}
            style={{
              fontSize: 12,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.03em',
              background: 'oklch(0.15 0 0)',
              color: 'oklch(0.98 0 0)',
              border: 'none',
              padding: '0 18px',
              cursor: loading ? 'default' : 'pointer',
            }}
          >
            Send
          </button>
        </div>
      </div>
    </section>
  )
}
