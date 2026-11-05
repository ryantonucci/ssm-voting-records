import { useEffect, useState } from 'react'
import { Routes, Route, Link, useParams, useNavigate } from 'react-router-dom'
import ChatWidget from './ChatWidget'

// The chatbot needs the paid Python backend, so only show it in local dev or
// when a deployed backend URL is configured.
const CHAT_ENABLED = import.meta.env.DEV || Boolean(import.meta.env.VITE_CHAT_API_URL)

function useData() {
  const [data, setData] = useState(null)
  useEffect(() => {
    fetch(import.meta.env.BASE_URL + 'data.json')
      .then((r) => r.json())
      .then(setData)
  }, [])
  return data
}

function friendlyMeetingName(sourceFile) {
  if (!sourceFile) return null
  const cleaned = sourceFile
    .replace(/\.pdf$/i, '')
    .replace(/^\d{4}-\d{2}-\d{2}_\w+_/, '')
    .replace(/[_-]/g, ' ')
  return cleaned
}

function Header({ meetingCount, itemCount, termStart, latestMeetingDate, pendingCount }) {
  const navigate = useNavigate()
  return (
    <header style={{ padding: '48px 0 32px', borderBottom: '1px solid oklch(0.15 0 0)' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          gap: 24,
          flexWrap: 'wrap',
        }}
      >
        <div onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
          <div
            style={{
              fontSize: 13,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'oklch(0.45 0 0)',
              marginBottom: 10,
            }}
          >
            Sault Ste. Marie Council Records
          </div>
          <h1 style={{ fontSize: 34, fontWeight: 700, margin: 0 }}>Council Members</h1>
        </div>
        <div style={{ fontSize: 13, color: 'oklch(0.45 0 0)', textAlign: 'right' }}>
          {meetingCount} meetings on file &middot; {itemCount} items indexed
        </div>
      </div>
      {termStart && (
        <p style={{ fontSize: 13, color: 'oklch(0.45 0 0)', margin: '16px 0 0' }}>
          Covers the full current council term: {termStart} &ndash; {latestMeetingDate}.
          {pendingCount > 0 && (
            <>
              {' '}
              {pendingCount} item{pendingCount === 1 ? '' : 's'} from the most recent meeting
              {pendingCount === 1 ? '' : 's'} are still <strong>pending</strong> — minutes
              haven't been posted yet, so these are drawn from the agenda and may not reflect
              the final outcome.
            </>
          )}
        </p>
      )}
    </header>
  )
}

function CouncillorCard({ c }) {
  const [hover, setHover] = useState(false)
  return (
    <Link
      to={`/councillor/${encodeURIComponent(c.shortName)}`}
      style={{ textDecoration: 'none', color: 'inherit' }}
    >
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          background: hover ? 'oklch(0.94 0 0)' : 'oklch(0.98 0 0)',
          padding: '28px 24px',
          cursor: 'pointer',
          transition: 'background 0.1s',
        }}
      >
        <div style={{ fontSize: 18, fontWeight: 700 }}>Councillor {c.shortName}</div>
        <div style={{ fontSize: 13, color: 'oklch(0.45 0 0)', marginTop: 10 }}>
          {c.count} items &middot; {c.movedCount} moved &middot; {c.secondedCount} seconded
        </div>
      </div>
    </Link>
  )
}

function Home({ data }) {
  return (
    <section style={{ marginTop: 40 }}>
      <p style={{ fontSize: 16, color: 'oklch(0.4 0 0)', maxWidth: 640, margin: '0 0 32px' }}>
        Select a councillor to see everything they've moved or seconded, most recent first.
      </p>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 1,
          background: 'oklch(0.15 0 0)',
          border: '1px solid oklch(0.15 0 0)',
        }}
      >
        {data.councillors.map((c) => (
          <CouncillorCard key={c.name} c={c} />
        ))}
      </div>
      {CHAT_ENABLED && <ChatWidget />}
    </section>
  )
}

function BackLink() {
  const [hover, setHover] = useState(false)
  return (
    <Link
      to="/"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        fontSize: 13,
        color: hover ? 'oklch(0.15 0 0)' : 'oklch(0.45 0 0)',
        cursor: 'pointer',
        textDecoration: 'none',
      }}
    >
      &larr; All councillors
    </Link>
  )
}

function Row({ item, onSelect }) {
  const [hover, setHover] = useState(false)
  return (
    <div
      onClick={() => onSelect(item)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'grid',
        gridTemplateColumns: '110px 70px 1fr 90px 110px',
        gap: 16,
        padding: '18px 20px',
        borderBottom: '1px solid oklch(0.9 0 0)',
        alignItems: 'start',
        cursor: 'pointer',
        background: hover ? 'oklch(0.94 0 0)' : 'transparent',
      }}
    >
      <div style={{ fontSize: 13, color: 'oklch(0.4 0 0)', fontVariantNumeric: 'tabular-nums' }}>
        {item.date}
      </div>
      <div style={{ fontSize: 14, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
        {item.number}
      </div>
      <div style={{ fontSize: 14, lineHeight: 1.4 }}>{item.description}</div>
      <div
        style={{
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: '0.03em',
          textTransform: 'uppercase',
          color: 'oklch(0.45 0 0)',
        }}
      >
        {item.role}
      </div>
      <div
        style={{
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          fontStyle: item.pending ? 'italic' : 'normal',
          color: item.pending ? 'oklch(0.45 0 0)' : 'oklch(0.15 0 0)',
        }}
      >
        {item.result}
      </div>
    </div>
  )
}

function ItemDetailModal({ item, onClose }) {
  if (!item) return null
  const meetingName = friendlyMeetingName(item.sourceFile)
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'oklch(0.15 0 0 / 0.5)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: '64px 24px',
        zIndex: 10,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'oklch(0.98 0 0)',
          border: '1px solid oklch(0.15 0 0)',
          maxWidth: 640,
          width: '100%',
          padding: '32px',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            marginBottom: 20,
          }}
        >
          <div
            style={{
              fontSize: 13,
              color: 'oklch(0.4 0 0)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {item.date} &middot; Item {item.number}
          </div>
          <div
            onClick={onClose}
            style={{ fontSize: 13, color: 'oklch(0.45 0 0)', cursor: 'pointer' }}
          >
            Close &times;
          </div>
        </div>

        <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1.3, marginBottom: 16 }}>
          {item.description}
        </div>

        {item.fullText && item.fullText !== item.description && (
          <p style={{ fontSize: 15, lineHeight: 1.6, color: 'oklch(0.15 0 0)', margin: '0 0 24px' }}>
            {item.fullText}
          </p>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: 16,
            borderTop: '1px solid oklch(0.9 0 0)',
            paddingTop: 20,
            fontSize: 13,
          }}
        >
          <div>
            <div style={{ color: 'oklch(0.45 0 0)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
              Role
            </div>
            <div style={{ fontWeight: 700 }}>{item.role}</div>
          </div>
          <div>
            <div style={{ color: 'oklch(0.45 0 0)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
              Result
            </div>
            <div style={{ fontWeight: 700, fontStyle: item.pending ? 'italic' : 'normal' }}>
              {item.result}
              {item.pending && ' (minutes not yet posted)'}
            </div>
          </div>
          {item.bylawCount > 0 && (
            <div>
              <div style={{ color: 'oklch(0.45 0 0)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
                By-laws
              </div>
              <div style={{ fontWeight: 700 }}>{item.bylawCount}</div>
            </div>
          )}
          {meetingName && (
            <div>
              <div style={{ color: 'oklch(0.45 0 0)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>
                Meeting
              </div>
              <div style={{ fontWeight: 700 }}>{meetingName}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Toggle({ view, setView, allCount }) {
  const opt = (key, label) => (
    <div
      onClick={() => setView(key)}
      style={{
        fontSize: 13,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        cursor: 'pointer',
        color: view === key ? 'oklch(0.15 0 0)' : 'oklch(0.45 0 0)',
        borderBottom: view === key ? '2px solid oklch(0.15 0 0)' : '2px solid transparent',
        paddingBottom: 6,
      }}
    >
      {label}
    </div>
  )
  return (
    <div style={{ display: 'flex', gap: 24, marginBottom: 20 }}>
      {opt('all', `All items (${allCount})`)}
      {opt('top10', 'Top 10')}
    </div>
  )
}

function Detail({ data }) {
  const { name } = useParams()
  const councillor = data.councillors.find((c) => c.shortName === name)
  const [view, setView] = useState('all')
  const [selectedItem, setSelectedItem] = useState(null)

  if (!councillor) {
    return (
      <section style={{ marginTop: 40 }}>
        <BackLink />
        <p style={{ marginTop: 24 }}>Councillor not found.</p>
      </section>
    )
  }

  const rows = view === 'top10' ? councillor.top10 : councillor.items

  return (
    <section style={{ marginTop: 40 }}>
      <BackLink />
      <h2 style={{ fontSize: 32, fontWeight: 700, margin: '16px 0 4px' }}>
        Councillor {councillor.shortName}
      </h2>
      <p style={{ fontSize: 15, color: 'oklch(0.4 0 0)', margin: '0 0 28px' }}>
        {councillor.count} items &middot; {councillor.movedCount} moved &middot;{' '}
        {councillor.secondedCount} seconded
      </p>

      <Toggle view={view} setView={setView} allCount={councillor.count} />

      {view === 'top10' && (
        <p style={{ fontSize: 13, color: 'oklch(0.45 0 0)', margin: '0 0 16px' }}>
          Auto-ranked by a keyword heuristic (budget, tax, zoning, borrowing, tenders,
          contested/defeated votes, etc.) — a rough first pass, not a definitive ranking.
        </p>
      )}

      <div style={{ border: '1px solid oklch(0.15 0 0)' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '110px 70px 1fr 90px 110px',
            gap: 16,
            padding: '14px 20px',
            background: 'oklch(0.15 0 0)',
            color: 'oklch(0.98 0 0)',
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}
        >
          <div>Date</div>
          <div>Item</div>
          <div>Description</div>
          <div>Role</div>
          <div>Result</div>
        </div>
        {rows.map((item, i) => (
          <Row key={i} item={item} onSelect={setSelectedItem} />
        ))}
      </div>

      <ItemDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} />
    </section>
  )
}

function App() {
  const data = useData()

  if (!data) {
    return (
      <div
        style={{
          fontFamily: 'Helvetica, Arial, sans-serif',
          color: 'oklch(0.15 0 0)',
          background: 'oklch(0.98 0 0)',
          minHeight: '100vh',
        }}
      />
    )
  }

  return (
    <div
      style={{
        fontFamily: 'Helvetica, Arial, sans-serif',
        color: 'oklch(0.15 0 0)',
        background: 'oklch(0.98 0 0)',
        minHeight: '100vh',
      }}
    >
      <div style={{ maxWidth: 1120, margin: '0 auto', padding: '0 32px 96px' }}>
        <Header
          meetingCount={data.meetingCount}
          itemCount={data.itemCount}
          termStart={data.termStart}
          latestMeetingDate={data.latestMeetingDate}
          pendingCount={data.pendingCount}
        />
        <Routes>
          <Route path="/" element={<Home data={data} />} />
          <Route path="/councillor/:name" element={<Detail data={data} />} />
        </Routes>
      </div>
    </div>
  )
}

export default App
