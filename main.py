import os
import json
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

app = FastAPI()

# ===== ENV =====
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Base URL nội bộ của n8n (private network)
# Ví dụ: http://primary.railway.internal:5678
N8N_TOOL_BASE_URL = os.getenv("N8N_TOOL_BASE_URL", "").rstrip("/")

# Vì bạn dùng private network, có thể để trống (không auth).
# Nếu bạn muốn bảo mật thêm, set N8N_TOOL_KEY và n8n kiểm tra header X-TOOL-KEY.
N8N_TOOL_KEY = os.getenv("N8N_TOOL_KEY", "").strip()

# Tool paths (để bạn đổi dễ dàng mà không sửa code)
TOOL_SEARCH_PATH = os.getenv("TOOL_SEARCH_PATH", "/webhook/tool_search_docs")
TOOL_GET_TEXT_PATH = os.getenv("TOOL_GET_TEXT_PATH", "/webhook/tool_get_doc_text")

# Gemini model
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

# ===== Schemas =====
class ChatReq(BaseModel):
    message: str = Field(..., description="User message")
    chat_history: Optional[List[Dict[str, Any]]] = Field(default=None, description="Last turns, optional")
    attachments_context: Optional[Dict[str, Any]] = Field(default=None, description="Extracted context from pdf/excel/image, optional")
    max_steps: int = Field(default=3, ge=1, le=6, description="Max agent steps (tool loops)")

class ChatResp(BaseModel):
    answer: str
    steps: List[Dict[str, Any]]


# ===== Helpers =====
def gemini_generate(text: str, temperature: float = 0.2, max_output_tokens: int = 2048) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY in Railway variables")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        }
    }
    r = requests.post(url, json=payload, timeout=90)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    data = r.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        # fallback: return raw json for debugging
        return json.dumps(data, ensure_ascii=False)


def call_n8n_tool(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if not N8N_TOOL_BASE_URL:
        raise HTTPException(status_code=500, detail="Missing N8N_TOOL_BASE_URL in Railway variables")

    url = f"{N8N_TOOL_BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if N8N_TOOL_KEY:
        headers["X-TOOL-KEY"] = N8N_TOOL_KEY

    r = requests.post(url, json=body, headers=headers, timeout=180)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


def safe_json_from_text(txt: str) -> Dict[str, Any]:
    """
    Gemini đôi khi trả thêm text ngoài JSON.
    Hàm này cố cắt đoạn {...} để parse JSON.
    """
    txt = txt.strip()
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"action": "final", "answer": txt}

    try:
        return json.loads(txt[start:end+1])
    except Exception:
        return {"action": "final", "answer": txt}


# ===== API =====
@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "agent0-wrapper",
        "model": GEMINI_MODEL,
        "n8n_base": N8N_TOOL_BASE_URL or None
    }


@app.post("/chat", response_model=ChatResp)
def chat(req: ChatReq):
    steps: List[Dict[str, Any]] = []

    # Context packing (giới hạn để tránh prompt quá dài)
    history = req.chat_history or []
    attach = req.attachments_context or {}

    # Agent loop: plan -> (tool?) -> observe -> answer
    tool_observation: Optional[Dict[str, Any]] = None

    for i in range(req.max_steps):
        planner_prompt = f"""
You are an agent. Decide the next action.

You have tools:
1) search_docs: retrieve relevant snippets from user's documents.
   args: {{"query": "...", "top_k": 5}}
2) get_doc_text: fetch detailed text for a specific document.
   args: {{"drive_file_id": "..."}}  (or another id your n8n expects)

Return ONLY JSON in one of forms:
- {{"action":"search_docs","args":{{...}},"reason":"..."}}
- {{"action":"get_doc_text","args":{{...}},"reason":"..."}}
- {{"action":"final","answer":"...","reason":"..."}}

User message: {req.message}

Chat history (recent): {json.dumps(history, ensure_ascii=False)[:6000]}
Attachments context: {json.dumps(attach, ensure_ascii=False)[:6000]}
Tool observation so far: {json.dumps(tool_observation or {{}}, ensure_ascii=False)[:6000]}
"""
        raw = gemini_generate(planner_prompt, temperature=0.0, max_output_tokens=1024)
        action = safe_json_from_text(raw)

        steps.append({"step": i+1, "planner_raw": raw, "action": action})

        if action.get("action") == "final":
            answer = action.get("answer") or raw
            return {"answer": answer, "steps": steps}

        if action.get("action") == "search_docs":
            args = action.get("args") or {}
            # default top_k
            args.setdefault("top_k", 5)
            obs = call_n8n_tool(TOOL_SEARCH_PATH, args)
            tool_observation = {"tool": "search_docs", "args": args, "result": obs}
            steps.append({"step": i+1, "tool_call": tool_observation})
            continue

        if action.get("action") == "get_doc_text":
            args = action.get("args") or {}
            obs = call_n8n_tool(TOOL_GET_TEXT_PATH, args)
            tool_observation = {"tool": "get_doc_text", "args": args, "result": obs}
            steps.append({"step": i+1, "tool_call": tool_observation})
            continue

        # Unknown action -> fallback to final answer
        final_prompt = f"""
Answer the user. If missing info, ask a concise clarifying question.

User: {req.message}
Chat history: {json.dumps(history, ensure_ascii=False)[:6000]}
Attachments: {json.dumps(attach, ensure_ascii=False)[:6000]}
Tool observation: {json.dumps(tool_observation or {{}}, ensure_ascii=False)[:6000]}
"""
        answer = gemini_generate(final_prompt, temperature=0.2, max_output_tokens=2048)
        steps.append({"step": i+1, "fallback_answer": answer})
        return {"answer": answer, "steps": steps}

    # If loop ends without final, produce answer using whatever we have
    final_prompt = f"""
Provide the best possible answer using available context and tool results.

User: {req.message}
Attachments: {json.dumps(attach, ensure_ascii=False)[:6000]}
Tool observation: {json.dumps(tool_observation or {{}}, ensure_ascii=False)[:8000]}
"""
    answer = gemini_generate(final_prompt, temperature=0.2, max_output_tokens=2048)
    steps.append({"final_fallback": True, "answer": answer})
    return {"answer": answer, "steps": steps}
