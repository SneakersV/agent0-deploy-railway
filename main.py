import os
import json
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

app = FastAPI()

# ========= ENV =========
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro").strip()

# Private network base URL của n8n
# vd: http://primary.railway.internal:5678
N8N_TOOL_BASE_URL = os.getenv("N8N_TOOL_BASE_URL", "").strip().rstrip("/")

# Optional header key (bạn có thể bỏ trống nếu chỉ dùng private network)
N8N_TOOL_KEY = os.getenv("N8N_TOOL_KEY", "").strip()

TOOL_SEARCH_PATH = os.getenv("TOOL_SEARCH_PATH", "/webhook/tool_search_docs").strip()
TOOL_GET_TEXT_PATH = os.getenv("TOOL_GET_TEXT_PATH", "/webhook/tool_get_doc_text").strip()

# Limits để tránh prompt quá dài
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "8000"))
MAX_ATTACH_CHARS = int(os.getenv("MAX_ATTACH_CHARS", "8000"))
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "12000"))

# ========= Schemas =========
class ChatReq(BaseModel):
    message: str = Field(..., description="User message")
    chat_history: Optional[List[Dict[str, Any]]] = Field(default=None, description="Recent chat turns")
    attachments_context: Optional[Dict[str, Any]] = Field(default=None, description="Preprocessed text from pdf/excel/image")
    max_steps: int = Field(default=3, ge=1, le=6, description="Max agent iterations")


class ChatResp(BaseModel):
    answer: str
    steps: List[Dict[str, Any]]


# ========= Helpers =========
def _truncate_json(obj: Any, limit: int) -> str:
    """Dump JSON rồi cắt chuỗi để tránh quá dài."""
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return s[:limit]


def gemini_generate(prompt: str, temperature: float = 0.2, max_output_tokens: int = 2048) -> str:
    """Call Gemini API generateContent."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY in Railway variables")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    r = requests.post(url, json=payload, timeout=90)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        # fallback: trả raw json để debug
        return json.dumps(data, ensure_ascii=False)


def safe_parse_json(txt: str) -> Dict[str, Any]:
    """
    Gemini đôi khi trả thêm text ngoài JSON. Cố tìm đoạn {...} để parse.
    Nếu không parse được -> trả action final.
    """
    t = (txt or "").strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"action": "final", "answer": t, "reason": "Planner did not return JSON"}

    chunk = t[start:end + 1]
    try:
        return json.loads(chunk)
    except Exception:
        return {"action": "final", "answer": t, "reason": "Failed to parse planner JSON"}


def call_n8n(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Call n8n tool webhook via private network."""
    if not N8N_TOOL_BASE_URL:
        raise HTTPException(status_code=500, detail="Missing N8N_TOOL_BASE_URL in Railway variables")

    url = f"{N8N_TOOL_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if N8N_TOOL_KEY:
        headers["X-TOOL-KEY"] = N8N_TOOL_KEY

    r = requests.post(url, json=body, headers=headers, timeout=180)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


# ========= API =========
@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "agent0-agentic-wrapper",
        "model": GEMINI_MODEL,
        "n8n_base": N8N_TOOL_BASE_URL or None,
        "tools": {
            "search_path": TOOL_SEARCH_PATH,
            "get_text_path": TOOL_GET_TEXT_PATH,
        },
    }


@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq):
    steps: List[Dict[str, Any]] = []

    user_msg = (req.message or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message is required")

    history = req.chat_history or []
    attach = req.attachments_context or {}

    history_txt = _truncate_json(history, MAX_HISTORY_CHARS)
    attach_txt = _truncate_json(attach, MAX_ATTACH_CHARS)

    tool_observation: Dict[str, Any] = {}  # luôn là dict
    final_answer: Optional[str] = None

    for i in range(req.max_steps):
        tool_obs_txt = _truncate_json(tool_observation, MAX_TOOL_CHARS)

        planner_prompt = f"""
You are an agent. Decide the NEXT action. Return ONLY JSON (no markdown, no extra text).

Available tools:
1) search_docs: Use to retrieve relevant snippets from user's document store.
   args: {{"query":"...","top_k":5}}

2) get_doc_text: Use to fetch detailed extracted text for a specific document.
   args: {{"drive_file_id":"..."}}

If no tool is needed:
{{"action":"final","answer":"...","reason":"..."}}

Rules:
- Prefer search_docs first, then get_doc_text if you need deeper details.
- Keep args minimal.
- Do not hallucinate document IDs; only request get_doc_text if you have an ID from tool results or attachments context.

User message:
{user_msg}

Chat history (recent, JSON):
{history_txt}

Attachments context (JSON):
{attach_txt}

Tool observation so far (JSON):
{tool_obs_txt}
""".strip()

        raw = gemini_generate(planner_prompt, temperature=0.0, max_output_tokens=1024)
        action = safe_parse_json(raw)

        steps.append({
            "step": i + 1,
            "planner_raw": raw,
            "action": action
        })

        act = (action.get("action") or "").strip()

        # ---- final ----
        if act == "final":
            final_answer = (action.get("answer") or "").strip() or raw.strip()
            break

        # ---- search_docs ----
        if act == "search_docs":
            args = action.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            args.setdefault("query", user_msg)
            args.setdefault("top_k", 5)

            obs = call_n8n(TOOL_SEARCH_PATH, args)
            tool_observation = {
                "last_tool": "search_docs",
                "args": args,
                "result": obs,
            }
            steps.append({"step": i + 1, "tool_observation": tool_observation})
            continue

        # ---- get_doc_text ----
        if act == "get_doc_text":
            args = action.get("args") or {}
            if not isinstance(args, dict):
                args = {}

            if not args.get("drive_file_id"):
                # Nếu planner đòi get_doc_text mà không có id -> buộc search trước
                obs = call_n8n(TOOL_SEARCH_PATH, {"query": user_msg, "top_k": 5})
                tool_observation = {
                    "last_tool": "search_docs_for_missing_id",
                    "args": {"query": user_msg, "top_k": 5},
                    "result": obs,
                }
                steps.append({"step": i + 1, "tool_observation": tool_observation})
                continue

            obs = call_n8n(TOOL_GET_TEXT_PATH, args)
            tool_observation = {
                "last_tool": "get_doc_text",
                "args": args,
                "result": obs,
            }
            steps.append({"step": i + 1, "tool_observation": tool_observation})
            continue

        # ---- unknown action fallback: answer directly ----
        tool_obs_txt = _truncate_json(tool_observation, MAX_TOOL_CHARS)
        final_prompt = f"""
Answer the user as best as possible using provided context.
If info is missing, ask 1-2 concise clarifying questions.

User: {user_msg}

Chat history: {history_txt}

Attachments context: {attach_txt}

Tool observation: {tool_obs_txt}
""".strip()

        final_answer = gemini_generate(final_prompt, temperature=0.2, max_output_tokens=2048).strip()
        steps.append({"step": i + 1, "fallback": True})
        break

    # If still no final answer, do a final synthesis
    if not final_answer:
        tool_obs_txt = _truncate_json(tool_observation, MAX_TOOL_CHARS)
        final_prompt = f"""
Provide the best possible answer using all context and tool results.

User: {user_msg}

Chat history: {history_txt}

Attachments context: {attach_txt}

Tool observation: {tool_obs_txt}
""".strip()
        final_answer = gemini_generate(final_prompt, temperature=0.2, max_output_tokens=2048).strip()
        steps.append({"final_synthesis": True})

    return {"answer": final_answer, "steps": steps}