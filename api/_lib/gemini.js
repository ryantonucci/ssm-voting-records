// Thin client for the Gemini generateContent REST endpoint. Kept separate from
// the chat loop so another provider (e.g. Claude Haiku) can be swapped in by
// replacing this one module.

const API = 'https://generativelanguage.googleapis.com/v1beta/models'

export class ModelBusyError extends Error {}

export async function generate(args, retried = false) {
  try {
    return await request(args)
  } catch (e) {
    // The free tier has a low per-minute cap; one short wait usually clears it.
    if (e instanceof ModelBusyError && !retried) {
      await new Promise((r) => setTimeout(r, 3000))
      return generate(args, true)
    }
    throw e
  }
}

async function request({ model, system, contents, tools, allowTools = true }) {
  const res = await fetch(`${API}/${model}:generateContent`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-goog-api-key': process.env.GEMINI_API_KEY,
    },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: system }] },
      contents,
      tools: [{ functionDeclarations: tools }],
      toolConfig: { functionCallingConfig: { mode: allowTools ? 'AUTO' : 'NONE' } },
      generationConfig: { maxOutputTokens: 1500 },
    }),
  })

  if (res.status === 429 || res.status === 503) {
    throw new ModelBusyError(`Gemini returned ${res.status}`)
  }
  const body = await res.json()
  if (!res.ok) {
    throw new Error(`Gemini error ${res.status}: ${body.error?.message || 'unknown'}`)
  }

  const content = body.candidates?.[0]?.content || { role: 'model', parts: [] }
  const parts = content.parts || []
  return {
    // Returned verbatim so the next turn can echo it back, thought signatures included.
    content,
    calls: parts.filter((p) => p.functionCall).map((p) => p.functionCall),
    text: parts
      .filter((p) => p.text && !p.thought)
      .map((p) => p.text)
      .join('')
      .trim(),
    usage: {
      input: body.usageMetadata?.promptTokenCount || 0,
      output:
        (body.usageMetadata?.candidatesTokenCount || 0) +
        (body.usageMetadata?.thoughtsTokenCount || 0),
    },
  }
}
