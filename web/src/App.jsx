import { useEffect, useState } from 'react'
import { Routes, Route, Link, useParams } from 'react-router-dom'
import ChatWidget from './ChatWidget'

// The chat assistant (api/chat.js) is always on in local dev, and in a deployed
// build only when VITE_ENABLE_CHAT=true is set for that build.
const CHAT_ENABLED = import.meta.env.DEV || import.meta.env.VITE_ENABLE_CHAT === 'true'

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

// URL-safe form of a term label, e.g. "2022–2026" -> "2022-2026".
function termSlug(term) {
  return term.term.replace(/[^0-9]+/g, '-')
}

function termPath(term, isCurrent) {
  return isCurrent ? '/' : `/term/${termSlug(term)}`
}

function TermSwitcher({ terms, active }) {
  return (
    <nav style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 24 }} aria-label="Council term">
      {terms.map((t, i) => {
        const selected = t === active
        return (
          <Link
            key={t.term}
            to={termPath(t, i === 0)}
            aria-current={selected ? 'page' : undefined}
            style={{
              fontSize: 13,
              fontWeight: 700,
              letterSpacing: '0.04em',
              padding: '8px 14px',
              textDecoration: 'none',
              border: '1px solid oklch(0.15 0 0)',
              background: selected ? 'oklch(0.15 0 0)' : 'transparent',
              color: selected ? 'oklch(0.98 0 0)' : 'oklch(0.15 0 0)',
            }}
          >
            {t.term} council{i === 0 ? ' (current)' : ''}
          </Link>
        )
      })}
    </nav>
  )
}

function Header({ terms, term, isCurrent }) {
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
        <Link to={termPath(term, isCurrent)} style={{ textDecoration: 'none', color: 'inherit' }}>
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
        </Link>
        <div style={{ fontSize: 13, color: 'oklch(0.45 0 0)', textAlign: 'right' }}>
          {term.meetingCount} meetings on file &middot; {term.itemCount} items indexed
        </div>
      </div>
      <TermSwitcher terms={terms} active={term} />
      <p style={{ fontSize: 13, color: 'oklch(0.45 0 0)', margin: '16px 0 0' }}>
        {term.firstMeetingDate ? (
          <>
            The {term.term} council: meetings from {term.firstMeetingDate} &ndash;{' '}
            {term.latestMeetingDate}.
          </>
        ) : (
          <>
            The {term.term} council takes office {term.start}. Votes will appear here once
            minutes from its meetings are posted.
          </>
        )}
        {term.pendingCount > 0 && (
          <>
            {' '}
            {term.pendingCount} item{term.pendingCount === 1 ? '' : 's'} from the most recent
            meeting{term.pendingCount === 1 ? '' : 's'} are still <strong>pending</strong> —
            minutes haven't been posted yet, so these are drawn from the agenda and may not
            reflect the final outcome.
          </>
        )}
      </p>
    </header>
  )
}

function CouncillorCard({ c, basePath }) {
  const [hover, setHover] = useState(false)
  return (
    <Link
      to={`${basePath}councillor/${encodeURIComponent(c.shortName)}`}
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
        {c.ward != null && (
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'oklch(0.45 0 0)',
              marginBottom: 8,
            }}
          >
            Ward {c.ward}
          </div>
        )}
        <div style={{ fontSize: 18, fontWeight: 700 }}>Councillor {c.shortName}</div>
        <div style={{ fontSize: 13, color: 'oklch(0.45 0 0)', marginTop: 10 }}>
          {c.count > 0 ? (
            <>
              {c.count} items &middot; {c.movedCount} moved &middot; {c.secondedCount} seconded
            </>
          ) : (
            'No recorded votes yet this term'
          )}
        </div>
      </div>
    </Link>
  )
}

function MayorCard({ m, basePath }) {
  const [hover, setHover] = useState(false)
  return (
    <Link to={`${basePath}mayor`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          background: hover ? 'oklch(0.94 0 0)' : 'oklch(0.98 0 0)',
          padding: '28px 24px',
          cursor: 'pointer',
          transition: 'background 0.1s',
          height: '100%',
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            color: 'oklch(0.45 0 0)',
            marginBottom: 8,
          }}
        >
          Mayor
        </div>
        <div style={{ fontSize: 18, fontWeight: 700 }}>{m.name}</div>
        <div style={{ fontSize: 13, color: 'oklch(0.45 0 0)', marginTop: 10 }}>
          {m.voteCount > 0 ? (
            <>
              Chairs meetings &middot; {m.voteCount} recorded votes &middot; {m.votes.for} for &middot;{' '}
              {m.votes.against} against
            </>
          ) : (
            'Chairs council meetings · no recorded votes yet this term'
          )}
        </div>
      </div>
    </Link>
  )
}

function Home({ term, basePath }) {
  return (
    <section style={{ marginTop: 40 }}>
      <p style={{ fontSize: 16, color: 'oklch(0.4 0 0)', maxWidth: 640, margin: '0 0 32px' }}>
        Select a councillor to see everything they've moved or seconded, most recent first, or the
        mayor to see his recorded votes.
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
        {term.mayor && <MayorCard m={term.mayor} basePath={basePath} />}
        {term.councillors.map((c) => (
          <CouncillorCard key={c.name} c={c} basePath={basePath} />
        ))}
      </div>
      {CHAT_ENABLED && <ChatWidget />}
    </section>
  )
}

function BackLink({ to }) {
  const [hover, setHover] = useState(false)
  return (
    <Link
      to={to}
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

function ItemDetailModal({ item, onClose, roleLabel = 'Role' }) {
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
              {roleLabel}
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

function Detail({ term, basePath }) {
  const { name } = useParams()
  const councillor = term.councillors.find((c) => c.shortName === name)
  const [view, setView] = useState('all')
  const [selectedItem, setSelectedItem] = useState(null)

  if (!councillor) {
    return (
      <section style={{ marginTop: 40 }}>
        <BackLink to={basePath} />
        <p style={{ marginTop: 24 }}>Councillor not found.</p>
      </section>
    )
  }

  const rows = view === 'top10' ? councillor.top10 : councillor.items

  return (
    <section style={{ marginTop: 40 }}>
      <BackLink to={basePath} />
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
        {rows.length === 0 && (
          <div style={{ padding: '18px 20px', fontSize: 14, color: 'oklch(0.45 0 0)' }}>
            No recorded votes in the {term.term} term yet.
          </div>
        )}
      </div>

      <ItemDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} />
    </section>
  )
}

function MayorDetail({ term, basePath }) {
  const [selectedItem, setSelectedItem] = useState(null)
  const mayor = term.mayor
  if (!mayor) {
    return (
      <section style={{ marginTop: 40 }}>
        <BackLink to={basePath} />
        <p style={{ marginTop: 24 }}>No mayor listed for this term.</p>
      </section>
    )
  }
  // The mayor chairs meetings, so the minutes record his named votes rather
  // than motions he moved; show both if the minutes ever list him as mover.
  const rows = [...mayor.voteItems, ...mayor.items].sort((a, b) =>
    (b.date || '').localeCompare(a.date || ''),
  )
  const v = mayor.votes
  return (
    <section style={{ marginTop: 40 }}>
      <BackLink to={basePath} />
      <h2 style={{ fontSize: 32, fontWeight: 700, margin: '16px 0 4px' }}>{mayor.name}</h2>
      <p style={{ fontSize: 15, color: 'oklch(0.4 0 0)', margin: '0 0 8px', maxWidth: 640 }}>
        The mayor chairs council meetings and is not listed as mover or seconder in the minutes
        {mayor.count > 0 ? ` (except ${mayor.count} item${mayor.count === 1 ? '' : 's'})` : ''}. This page
        lists every recorded (named) vote he cast.
      </p>
      <p style={{ fontSize: 15, color: 'oklch(0.4 0 0)', margin: '0 0 28px' }}>
        {mayor.voteCount} recorded votes &middot; {v.for} for &middot; {v.against} against &middot;{' '}
        {v.conflict} conflict declared &middot; {v.absent} absent
      </p>

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
          <div>Vote</div>
          <div>Result</div>
        </div>
        {rows.map((item, i) => (
          <Row key={i} item={item} onSelect={setSelectedItem} />
        ))}
        {rows.length === 0 && (
          <div style={{ padding: '18px 20px', fontSize: 14, color: 'oklch(0.45 0 0)' }}>
            No recorded votes in the {term.term} term yet.
          </div>
        )}
      </div>

      <ItemDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} roleLabel="Vote" />
    </section>
  )
}

// Shared layout for one term's pages. The newest term lives at "/", older
// ones at "/term/2022-2026", so existing links keep pointing at the current
// council.
function TermLayout({ data, isCurrent }) {
  const { termId } = useParams()
  const term = isCurrent ? data.terms[0] : data.terms.find((t) => termSlug(t) === termId)
  if (!term) {
    return (
      <section style={{ marginTop: 40 }}>
        <BackLink to="/" />
        <p style={{ marginTop: 24 }}>Council term not found.</p>
      </section>
    )
  }
  const basePath = isCurrent ? '/' : `/term/${termSlug(term)}/`
  return (
    <>
      <Header terms={data.terms} term={term} isCurrent={isCurrent} />
      <Routes>
        <Route index element={<Home term={term} basePath={basePath} />} />
        <Route path="mayor" element={<MayorDetail term={term} basePath={basePath} />} />
        <Route path="councillor/:name" element={<Detail term={term} basePath={basePath} />} />
      </Routes>
    </>
  )
}

function Disclaimer() {
  return (
    <footer
      style={{
        marginTop: 72,
        paddingTop: 24,
        borderTop: '1px solid oklch(0.15 0 0)',
        fontSize: 13,
        lineHeight: 1.6,
        color: 'oklch(0.4 0 0)',
        maxWidth: 720,
      }}
    >
      <div
        style={{
          fontWeight: 700,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'oklch(0.15 0 0)',
          marginBottom: 8,
        }}
      >
        About this data
      </div>
      <p style={{ margin: '0 0 8px' }}>
        Everything here is pulled automatically from the council agendas and minutes published by
        the{' '}
        <a href="https://saultstemarie.ca" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>
          City of Sault Ste. Marie
        </a>
        . We do our best to match each motion to the right mover, seconder and outcome, but
        automated parsing can get things wrong. The official minutes are always the authoritative
        record. This site is not affiliated with the City.
      </p>
      <p style={{ margin: 0 }}>
        Spotted a mistake? Email{' '}
        <a href="mailto:tonucci.ryan@gmail.com" style={{ color: 'oklch(0.15 0 0)', fontWeight: 700 }}>
          tonucci.ryan@gmail.com
        </a>{' '}
        with the meeting date and item number, and I'll fix it.
      </p>
    </footer>
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
        <Routes>
          <Route path="/term/:termId/*" element={<TermLayout data={data} />} />
          <Route path="/*" element={<TermLayout data={data} isCurrent />} />
        </Routes>
        <Disclaimer />
      </div>
    </div>
  )
}

export default App
