// Read-only query layer over web/public/data.json for the chat assistant.
// The dashboard data lists each motion under every councillor who touched it
// (once as "Moved", once as "Seconded"), so this folds those back into one
// record per motion before the model ever sees it.

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const DATA_PATH = join(process.cwd(), 'web', 'public', 'data.json')
const TEXT_TRIM = 280

const STOPWORDS = new Set(
  'the and for with from that this what which were was has have had did does about any all are been into its not but who how when where why council councillor motion motions vote voted votes item items city'.split(
    ' ',
  ),
)

let cache = null

function load() {
  if (cache) return cache
  const data = JSON.parse(readFileSync(DATA_PATH, 'utf8'))
  const motions = new Map()
  const councillorsByTerm = []

  for (const term of data.terms) {
    councillorsByTerm.push({
      term: term.term,
      start: term.start,
      end: term.end,
      councillors: term.councillors.map((c) => ({
        name: c.shortName,
        ward: c.ward,
        movedCount: c.movedCount,
        secondedCount: c.secondedCount,
      })),
    })
    for (const c of term.councillors) {
      for (const it of c.items) {
        const key = `${it.date}|${it.number}`
        let m = motions.get(key)
        if (!m) {
          m = {
            date: it.date,
            item: it.number,
            title: it.description,
            text: it.fullText,
            result: it.result,
            pending: it.pending,
            bylaws: it.bylawCount,
            term: term.term,
            mover: null,
            seconder: null,
            score: it.score,
          }
          motions.set(key, m)
        }
        if (it.role === 'Moved') m.mover = c.shortName
        else if (it.role === 'Seconded') m.seconder = c.shortName
      }
    }
  }

  const all = [...motions.values()].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  for (const m of all) {
    m._title = new Set(tokens(m.title))
    m._text = new Set(tokens(m.text))
  }
  cache = { terms: councillorsByTerm, motions: all, byKey: motions }
  return cache
}

function publicMotion(m, full = false) {
  const text = m.text && m.text !== m.title ? m.text : ''
  return {
    date: m.date,
    item: m.item,
    title: m.title,
    text: full || text.length <= TEXT_TRIM ? text : text.slice(0, TEXT_TRIM) + '…',
    mover: m.mover,
    seconder: m.seconder,
    result: m.result,
    term: m.term,
  }
}

function tokens(s) {
  return (s || '')
    .toLowerCase()
    .split(/[^a-z0-9$.-]+/)
    .map((t) => t.replace(/^[.-]+|[.-]+$/g, ''))
    .filter((t) => t.length >= 3 && !STOPWORDS.has(t))
    .map((t) => (t.length > 4 && t.endsWith('s') ? t.slice(0, -1) : t))
}

// Accepts "Spina", "S. Spina", "Sonny Spina", "Councillor Spina", ...
function resolveCouncillor(input) {
  if (!input) return null
  const words = input.toLowerCase().replace(/councillor|coun\.?/g, ' ').split(/[^a-z-]+/).filter(Boolean)
  const names = new Set(load().terms.flatMap((t) => t.councillors.map((c) => c.name)))
  for (const name of names) {
    const surname = name.split(' ').pop().toLowerCase()
    if (words.includes(surname)) return name
  }
  return null
}

function termFilter(term) {
  if (!term) return () => true
  const t = term.replace(/[^0-9]+/g, '-')
  return (m) => m.term.replace(/[^0-9]+/g, '-') === t
}

export function listCouncillors({ term } = {}) {
  const { terms } = load()
  const match = termFilter(term)
  return terms.map((t, i) => ({ ...t, current: i === 0 })).filter((t) => match({ term: t.term }))
}

export function searchMotions({ query, councillor, term, date_from, date_to, result, limit } = {}) {
  const { motions } = load()
  const q = tokens(query)
  const who = councillor ? resolveCouncillor(councillor) : null
  if (councillor && !who) return { error: `No councillor matching "${councillor}".` }
  const inTerm = termFilter(term)
  const max = Math.min(Number(limit) || 10, 25)

  const scored = []
  for (const m of motions) {
    if (!inTerm(m)) continue
    if (who && m.mover !== who && m.seconder !== who) continue
    if (date_from && (m.date || '') < date_from) continue
    if (date_to && (m.date || '') > date_to) continue
    if (result && m.result.toLowerCase() !== result.toLowerCase()) continue
    let s = 0
    for (const t of q) {
      if (m._title.has(t)) s += 3
      else if (m._text.has(t)) s += 1
    }
    if (q.length && s === 0) continue
    scored.push([s, m])
  }
  scored.sort((a, b) => b[0] - a[0] || (b[1].date || '').localeCompare(a[1].date || ''))
  return {
    totalMatches: scored.length,
    motions: scored.slice(0, max).map(([, m]) => publicMotion(m)),
  }
}

export function getMotion({ date, item }) {
  const m = load().byKey.get(`${date}|${item}`)
  return m ? publicMotion(m, true) : { error: `No motion found for ${date} item ${item}.` }
}

export function getCouncillorRecord({ councillor, term, role, limit } = {}) {
  const who = resolveCouncillor(councillor)
  if (!who) {
    return {
      error: `No councillor matching "${councillor}".`,
      known: [...new Set(load().terms.flatMap((t) => t.councillors.map((c) => c.name)))],
    }
  }
  const inTerm = termFilter(term)
  const mine = load().motions.filter(
    (m) =>
      inTerm(m) &&
      ((role !== 'Seconded' && m.mover === who) || (role !== 'Moved' && m.seconder === who)),
  )
  const max = Math.min(Number(limit) || 10, 25)
  // Spell out this councillor's role on each motion; the model otherwise has
  // to infer it from the mover/seconder names and sometimes swaps them.
  const withRole = (m) => ({ role: m.mover === who ? 'Moved' : 'Seconded', ...publicMotion(m) })
  return {
    councillor: who,
    terms: load()
      .terms.filter((t) => t.councillors.some((c) => c.name === who))
      .map((t) => ({ term: t.term, ward: t.councillors.find((c) => c.name === who).ward })),
    moved: mine.filter((m) => m.mover === who).length,
    seconded: mine.filter((m) => m.seconder === who).length,
    defeatedMoved: mine.filter((m) => m.result === 'Defeated' && m.mover === who).map(withRole),
    defeatedSeconded: mine.filter((m) => m.result === 'Defeated' && m.seconder === who).map(withRole),
    mostSignificant: [...mine]
      .sort((a, b) => b.score - a.score || (b.date || '').localeCompare(a.date || ''))
      .slice(0, 5)
      .map(withRole),
    mostRecent: mine.slice(0, max).map(withRole),
  }
}

export function dataSummary() {
  const { terms, motions } = load()
  return {
    terms: terms.map((t) => `${t.term} (from ${t.start}${t.end ? ` to ${t.end}` : ''})`),
    currentCouncil: terms[0].councillors.map((c) => `${c.name} (Ward ${c.ward})`),
    latestMotion: motions[0]?.date,
  }
}
