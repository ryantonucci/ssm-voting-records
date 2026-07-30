#!/usr/bin/env python3
"""Chatbot backend for the council voting-records dashboard.

Uses Groq's free tier (OpenAI-compatible API) with tool calling instead of
stuffing the whole dataset into every prompt: the model gets a handful of
narrow query tools, decides what it needs, and only the matching rows come
back into the conversation. That keeps each turn to a few hundred tokens
instead of the ~1MB dataset, which matters on Groq's free-tier
tokens-per-minute limit.

Reads web/public/data.json (the same file the React site fetches) rather
than querying council.db or the PDFs directly -- it's already deduped,
normalized, and scored, so there's no reason to redo that work per request.

Setup:
    pip install -r chatbot/requirements.txt
    cp chatbot/.env.example chatbot/.env   # then paste your key into chatbot/.env
    python3 chatbot/server.py
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent / ".env")

DATA_PATH = Path(__file__).resolve().parent.parent / "web" / "public" / "data.json"
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_TOOL_ITERATIONS = 6
FULL_TEXT_TRIM = 300

SYSTEM_PROMPT = """You are a research assistant for a public dashboard of Sault Ste. Marie, \
Ontario city council voting records, covering the current council term (Nov 2022 - present). \
Answer questions about what councillors have moved, seconded, or voted on using ONLY the tools \
provided -- never guess or make up a motion, date, or outcome from memory. Always cite the \
meeting date and item number when referencing a specific motion. If an item's result is \
"Pending", say plainly that minutes haven't been posted yet for that meeting and the outcome \
isn't final. Keep answers concise and factual."""


def load_data():
    return json.loads(DATA_PATH.read_text())


DATA = load_data()


def trim_item(item):
    full_text = item.get("fullText") or ""
    if len(full_text) > FULL_TEXT_TRIM:
        full_text = full_text[:FULL_TEXT_TRIM] + "…"
    return {
        "date": item["date"],
        "number": item["number"],
        "description": item["description"],
        "fullText": full_text,
        "role": item["role"],
        "result": item["result"],
    }


def find_councillor(short_name):
    if not short_name:
        return None
    short_name = short_name.strip().lower()
    for c in DATA["councillors"]:
        if c["shortName"].lower() == short_name:
            return c
    # fall back to a loose substring match (e.g. just a last name)
    matches = [c for c in DATA["councillors"] if short_name in c["shortName"].lower()]
    return matches[0] if len(matches) == 1 else None


def tool_list_councillors():
    return [
        {
            "shortName": c["shortName"],
            "itemCount": c["count"],
            "movedCount": c["movedCount"],
            "secondedCount": c["secondedCount"],
        }
        for c in DATA["councillors"]
    ]


def tool_get_councillor_record(shortName, role=None, result=None, limit=20):
    c = find_councillor(shortName)
    if not c:
        return {
            "error": f"No councillor matching '{shortName}'.",
            "validNames": [x["shortName"] for x in DATA["councillors"]],
        }
    items = c["items"]
    if role:
        items = [i for i in items if i["role"].lower() == role.lower()]
    if result:
        items = [i for i in items if i["result"].lower() == result.lower()]
    limit = min(int(limit or 20), 50)
    return {
        "councillor": c["shortName"],
        "totalMatching": len(items),
        "items": [trim_item(i) for i in items[:limit]],
    }


def tool_search_items(keyword, councillor=None, limit=20):
    keyword = (keyword or "").lower().strip()
    if not keyword:
        return {"error": "keyword is required"}

    councillors = DATA["councillors"]
    if councillor:
        c = find_councillor(councillor)
        if not c:
            return {"error": f"No councillor matching '{councillor}'."}
        councillors = [c]

    seen = set()
    results = []
    for c in councillors:
        for it in c["items"]:
            key = (it["date"], it["number"])
            if key in seen:
                continue
            haystack = f"{it['description']} {it['fullText']}".lower()
            if keyword in haystack:
                seen.add(key)
                results.append({**trim_item(it), "councillor": c["shortName"]})

    results.sort(key=lambda r: r["date"] or "", reverse=True)
    limit = min(int(limit or 20), 50)
    return {"matchCount": len(results), "items": results[:limit]}


def tool_get_top_items(shortName, limit=10):
    c = find_councillor(shortName)
    if not c:
        return {
            "error": f"No councillor matching '{shortName}'.",
            "validNames": [x["shortName"] for x in DATA["councillors"]],
        }
    limit = min(int(limit or 10), 10)
    return {"councillor": c["shortName"], "items": [trim_item(i) for i in c["top10"][:limit]]}


def tool_get_stats():
    return {
        "meetingCount": DATA["meetingCount"],
        "itemCount": DATA["itemCount"],
        "termStart": DATA["termStart"],
        "latestMeetingDate": DATA["latestMeetingDate"],
        "pendingCount": DATA["pendingCount"],
        "councillors": [c["shortName"] for c in DATA["councillors"]],
    }


TOOL_IMPL = {
    "list_councillors": tool_list_councillors,
    "get_councillor_record": tool_get_councillor_record,
    "search_items": tool_search_items,
    "get_top_items": tool_get_top_items,
    "get_stats": tool_get_stats,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_councillors",
            "description": "List all councillors with their total item/moved/seconded counts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_councillor_record",
            "description": (
                "Get a councillor's moved/seconded agenda items, most recent first. "
                "Use for 'what has X done/moved/seconded' style questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "shortName": {"type": "string", "description": "Councillor's short name, e.g. 'A. Caputo'"},
                    "role": {"type": "string", "enum": ["Moved", "Seconded"], "description": "Optional role filter"},
                    "result": {"type": "string", "description": "Optional outcome filter, e.g. 'Carried', 'Defeated', 'Pending'"},
                    "limit": {"type": ["integer", "string"], "description": "Max items to return (default 20, max 50)"},
                },
                "required": ["shortName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_items",
            "description": "Search all agenda items by keyword in the title or full motion text. Optionally scope to one councillor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "councillor": {"type": "string", "description": "Optional councillor short name to scope the search"},
                    "limit": {"type": ["integer", "string"]},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_items",
            "description": "Get a councillor's algorithmically-ranked most significant items (budget, tax, zoning, defeated votes, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "shortName": {"type": "string"},
                    "limit": {"type": ["integer", "string"]},
                },
                "required": ["shortName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": "Get overall dataset stats: meeting count, item count, date range covered, pending count, and valid councillor names.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

app = Flask(__name__)
CORS(app)


def get_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True) or {}
    user_message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not user_message:
        return jsonify({"error": "message is required"}), 400

    try:
        client = get_client()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": user_message}
    ]

    # Everything below can fail in ways outside our control (the model
    # emitting a malformed tool call that Groq's own schema validator
    # rejects, a transient network error, a rate limit, ...). Catch broadly
    # here so the frontend always gets JSON back -- without this, Flask's
    # debug mode serves an HTML error page instead, which res.json() can't
    # parse, and the browser reports a generic "Load failed" with no hint
    # of the real cause.
    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                new_history = history + [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": msg.content},
                ]
                return jsonify({"reply": msg.content, "history": new_history})

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                }
            )
            for tc in msg.tool_calls:
                fn = TOOL_IMPL.get(tc.function.name)
                if fn is None:
                    result = {"error": f"unknown tool {tc.function.name}"}
                else:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                        result = fn(**args)
                    except Exception as e:
                        result = {"error": str(e)}
                print(f"DEBUG tool_call name={tc.function.name} args={tc.function.arguments} -> result={json.dumps(result)[:400]}", flush=True)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}
                )

        return jsonify({"error": "Too many tool-call iterations"}), 500
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "model": MODEL, "meetingCount": DATA["meetingCount"]})


if __name__ == "__main__":
    app.run(port=5001, debug=True)
