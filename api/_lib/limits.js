// Rate limits for the chat endpoint: per-visitor hourly/daily caps plus a
// site-wide daily cap that keeps usage inside the model's free quota.
// Uses Upstash Redis (REST API) when its URL and token are set, so counts are
// shared across serverless instances; otherwise falls back to an in-memory
// counter, which is fine for local testing. Vercel's Upstash integration
// names the variables KV_REST_API_URL/TOKEN; Upstash's own docs use
// UPSTASH_REDIS_REST_URL/TOKEN. Either works.

const LIMITS = {
  ipHour: Number(process.env.CHAT_LIMIT_PER_IP_HOUR || 10),
  ipDay: Number(process.env.CHAT_LIMIT_PER_IP_DAY || 30),
  globalDay: Number(process.env.CHAT_LIMIT_GLOBAL_DAY || 100),
}

const memory = new Map()

async function incr(key, ttlSeconds) {
  const url = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN
  if (url && token) {
    const res = await fetch(`${url}/pipeline`, {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify([
        ['INCR', key],
        ['EXPIRE', key, String(ttlSeconds), 'NX'],
      ]),
    })
    const [first] = await res.json()
    return Number(first.result)
  }
  const now = Date.now()
  const entry = memory.get(key)
  if (!entry || entry.resetAt <= now) {
    memory.set(key, { count: 1, resetAt: now + ttlSeconds * 1000 })
    return 1
  }
  entry.count += 1
  return entry.count
}

// Returns null when the request may proceed, or a user-facing message when not.
export async function checkLimits(ip) {
  const day = new Date().toISOString().slice(0, 10)
  const hour = new Date().toISOString().slice(0, 13)

  // Per-visitor checks come first so one visitor going over their own limit
  // doesn't use up the site-wide allowance.
  if ((await incr(`chat:ip:${ip}:${hour}`, 3600)) > LIMITS.ipHour) {
    return "You've asked a lot of questions this hour. Please try again a bit later."
  }
  if ((await incr(`chat:ip:${ip}:${day}`, 26 * 3600)) > LIMITS.ipDay) {
    return "You've reached today's question limit. Please come back tomorrow."
  }
  if ((await incr(`chat:global:${day}`, 26 * 3600)) > LIMITS.globalDay) {
    return 'The assistant has answered all the questions it can for today. Please check back tomorrow, or browse the councillor pages above.'
  }
  return null
}
