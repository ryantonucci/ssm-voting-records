// POST /api/chat — answers questions about council votes using Gemini with a
// few narrow lookup tools over data.json (see _lib/motions.js), so only the
// rows a question needs are sent to the model, never the whole dataset.
//
// Request:  { message: string, history?: [{ role: "user"|"assistant", content }] }
// Response: { reply: string, history: [...] }

import { checkLimits, limiterBackend } from './_lib/limits.js'
import { generate, ModelBusyError } from './_lib/gemini.js'
import {
  dataSummary,
  getCouncillorRecord,
  getMotion,
  listCouncillors,
  searchMotions,
} from './_lib/motions.js'

const MODEL = process.env.GEMINI_MODEL || 'gemini-3.5-flash-lite'
const MAX_MESSAGE_CHARS = 500
const MAX_HISTORY_TURNS = 6
const MAX_TOOL_ROUNDS = 4

const TOOLS = [
  {
    name: 'search_motions',
    description:
      'Keyword search over council motions, newest and best matches first. Use for any question about a topic, place, by-law, project or decision. All filters are optional.',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Topic keywords, e.g. "Bellevue Park splash pad" or "tax levy".' },
        councillor: { type: 'string', description: 'Only motions this councillor moved or seconded (surname is enough).' },
        term: { type: 'string', description: 'Council term, e.g. "2022-2026" or "2026-2030".' },
        date_from: { type: 'string', description: 'Earliest meeting date, YYYY-MM-DD.' },
        date_to: { type: 'string', description: 'Latest meeting date, YYYY-MM-DD.' },
        result: { type: 'string', enum: ['Carried', 'Defeated', 'Pending'] },
        limit: { type: 'integer', description: 'Max results, default 10, max 25.' },
      },
    },
  },
  {
    name: 'get_councillor_record',
    description:
      "A councillor's record: wards and terms served, how many motions they moved and seconded, any defeated motions, their most significant and most recent motions.",
    parameters: {
      type: 'object',
      properties: {
        councillor: { type: 'string', description: 'Councillor name; surname is enough.' },
        term: { type: 'string', description: 'Limit to one term, e.g. "2022-2026".' },
        role: { type: 'string', enum: ['Moved', 'Seconded'] },
        limit: { type: 'integer', description: 'How many recent motions to include, default 10.' },
      },
      required: ['councillor'],
    },
  },
  {
    name: 'get_motion',
    description: 'Full text, mover, seconder and result of one motion, by meeting date and item number.',
    parameters: {
      type: 'object',
      properties: {
        date: { type: 'string', description: 'Meeting date, YYYY-MM-DD.' },
        item: { type: 'string', description: 'Agenda item number, e.g. "9.4".' },
      },
      required: ['date', 'item'],
    },
  },
  {
    name: 'list_councillors',
    description: 'Councillors and their wards for each council term, plus how many motions each moved and seconded.',
    parameters: {
      type: 'object',
      properties: { term: { type: 'string', description: 'e.g. "2026-2030"; omit for all terms.' } },
    },
  },
]

const HANDLERS = {
  search_motions: searchMotions,
  get_councillor_record: getCouncillorRecord,
  get_motion: getMotion,
  list_councillors: listCouncillors,
}

function systemPrompt() {
  const s = dataSummary()
  return `You answer questions about Sault Ste. Marie (Ontario) City Council motions for a public website. Today is ${new Date().toISOString().slice(0, 10)}.

Data available: council terms ${s.terms.join('; ')}. Most recent motion on file: ${s.latestMotion}. Current council: ${s.currentCouncil.join(', ')}. The data comes from the City's published agendas and minutes and only covers councillors (not the mayor), and only who moved and seconded each motion and whether it carried. It does not include how each councillor voted except as mover/seconder, and has nothing on meetings outside these dates.

How to answer:
- Look facts up with the tools before answering. Never state a motion, date, name, count or outcome you did not get from a tool result.
- Cite each motion you mention as (meeting date, item number), e.g. (2025-09-22, item 9.4).
- "Pending" means minutes for that meeting have not been posted yet, so the outcome is not final. Say so.
- If the tools don't have the answer, say plainly that the records here don't cover it, and suggest the City's official minutes at saultstemarie.ca.
- Stay neutral: describe what happened, don't judge councillors.
- Only answer questions about this council data; politely decline anything else.
- Be brief: a few sentences, or a short list using "-" bullets. Plain text only, no markdown headings, bold or tables.`
}

function cleanHistory(history) {
  if (!Array.isArray(history)) return []
  return history
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .slice(-MAX_HISTORY_TURNS)
    .map((m) => ({ role: m.role, content: m.content.slice(0, 2000) }))
}

function clientIp(req) {
  const fwd = req.headers['x-forwarded-for']
  return (Array.isArray(fwd) ? fwd[0] : fwd || '').split(',')[0].trim() || req.socket?.remoteAddress || 'unknown'
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('allow', 'POST')
    return res.status(405).json({ error: 'Use POST' })
  }
  if (process.env.CHAT_DISABLED === 'true' || !process.env.GEMINI_API_KEY) {
    return res.status(503).json({ error: 'The assistant is currently turned off.' })
  }

  const message = typeof req.body?.message === 'string' ? req.body.message.trim() : ''
  if (!message) return res.status(400).json({ error: 'Please type a question.' })
  if (message.length > MAX_MESSAGE_CHARS) {
    return res.status(400).json({ error: `Please keep questions under ${MAX_MESSAGE_CHARS} characters.` })
  }

  const history = cleanHistory(req.body?.history)
  const limited = await checkLimits(clientIp(req))
  if (limited) return res.status(429).json({ error: limited })

  const contents = [
    ...history.map((m) => ({ role: m.role === 'user' ? 'user' : 'model', parts: [{ text: m.content }] })),
    { role: 'user', parts: [{ text: message }] },
  ]
  const usage = { input: 0, output: 0, calls: 0 }

  try {
    let reply = ''
    for (let round = 0; round <= MAX_TOOL_ROUNDS; round++) {
      const turn = await generate({
        model: MODEL,
        system: systemPrompt(),
        contents,
        tools: TOOLS,
        allowTools: round < MAX_TOOL_ROUNDS,
      })
      usage.input += turn.usage.input
      usage.output += turn.usage.output
      usage.calls += 1

      if (!turn.calls.length) {
        reply = turn.text
        break
      }
      contents.push(turn.content)
      contents.push({
        role: 'user',
        parts: turn.calls.map((call) => {
          const fn = HANDLERS[call.name]
          let result
          try {
            result = fn ? fn(call.args || {}) : { error: `Unknown tool ${call.name}` }
          } catch (e) {
            result = { error: e.message }
          }
          return { functionResponse: { name: call.name, response: { result } } }
        }),
      })
    }

    console.log(JSON.stringify({ chat: 'ok', model: MODEL, limiter: limiterBackend, ...usage }))
    if (!reply) reply = "Sorry, I couldn't put an answer together for that. Try rephrasing the question."
    return res.status(200).json({
      reply,
      history: [...history, { role: 'user', content: message }, { role: 'assistant', content: reply }].slice(
        -MAX_HISTORY_TURNS,
      ),
    })
  } catch (e) {
    console.error(JSON.stringify({ chat: 'error', model: MODEL, message: e.message, ...usage }))
    if (e instanceof ModelBusyError) {
      return res.status(503).json({ error: 'The assistant is busy right now. Please try again in a minute.' })
    }
    return res.status(500).json({ error: 'Something went wrong answering that. Please try again.' })
  }
}
