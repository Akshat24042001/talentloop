"""AI answers that are empty, cut off or not JSON:  python -m tests.test_llm_answers

A fake OpenRouter server imitates a reasoning model: with a small max_tokens or no reasoning limit it spends the budget
thinking and returns an empty answer (finish_reason "length"), as free OpenRouter models do. A check passes when the
problem does NOT happen."""
import asyncio, json, os, socket, tempfile, threading, time
os.environ.update({"LLM_MOCK": "0", "OPENROUTER_API_KEY": "sk-or-fake", "DATA_DIR": tempfile.mkdtemp(), "DATABASE_URL": ""})
import logging; logging.disable(logging.CRITICAL)
import uvicorn
from fastapi import FastAPI, Request
from backend import llm
from backend.api_hiring import ai_unavailable

RES = []
def check(name, bug_if, detail=""):
    RES.append((name, bool(bug_if))); print(("FAIL " if bug_if else "ok   ") + "no longer: " + name + (f"  [{detail}]" if detail and bug_if else ""))

SEEN = []
fake = FastAPI()
@fake.post("/v1/chat/completions")
async def chat(req: Request):
    b = await req.json(); SEEN.append(b)
    model = b["model"]
    def answer(content, finish="stop"):
        return {"id": "x", "object": "chat.completion", "created": 1, "model": model,
                "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}]}
    if model == "think/model":     # a reasoning model: needs room and a reasoning limit, or it returns nothing
        ok = (b.get("max_tokens") or 0) >= 2000 and (b.get("reasoning") or {}).get("effort") == "low"
        return answer('{"score": 70, "verdict": "good"}' if ok else "", "stop" if ok else "length")
    if model == "prose/model":     # answers in prose, not JSON
        return answer("Sure! The candidate looks good overall.")
    return answer('{"score": 55, "verdict": "possible"}')

port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
threading.Thread(target=uvicorn.Server(uvicorn.Config(fake, port=port, log_level="error")).run, daemon=True).start()
time.sleep(1.5)
llm.PROVIDERS["openrouter"]["base_url"] = f"http://127.0.0.1:{port}/v1"
llm._clients.clear()

def run(model, chain, **kw):
    llm.apply_config({"fast": {"provider": "openrouter", "models": ["fast/model"]}, "smart": {"provider": "openrouter", "models": chain},
                      "vision": {"provider": "openrouter", "models": []}}, "admin")
    llm.PROVIDERS["openrouter"]["base_url"] = f"http://127.0.0.1:{port}/v1"; llm._clients.clear()
    return asyncio.run(llm.complete_json("Output JSON", "Rate this", model, max_tokens=700, **kw))

out = run("think/model", ["think/model"])
check("a reasoning model with a 700-token budget returns nothing", out.get("score") != 70, str(SEEN[-1].get("max_tokens")))
check("reasoning is not limited", (SEEN[-1].get("reasoning") or {}).get("exclude") is not True)
SEEN.clear()
out = run("prose/model", ["prose/model", "plain/model"])
check("a prose answer from the main model isn't replaced by the fallback's", out.get("score") != 55, str([b["model"] for b in SEEN]))
try:
    run("prose/model", ["prose/model"]); err = None
except Exception as e:
    err = e
check("an unusable answer with no fallback doesn't raise", err is None)
msg = ai_unavailable(err) if err else ""
check("the error says 'didn't respond' instead of what happened", "didn't respond" in msg or "prose/model" not in msg, msg)
check("the error doesn't point to the model settings", "AI models" not in msg, msg)
check("a timeout isn't explained", "too long" not in ai_unavailable(TimeoutError("Request timed out.")))
check("a removed model isn't explained", "isn't available" not in ai_unavailable(RuntimeError("Error code: 404 - No endpoints found for x/y")))

bugs = [n for n, b in RES if b]
print(f"\n{'LLM ANSWER CHECKS PASSED' if not bugs else 'LLM ANSWER CHECKS FAILED'} ({len(RES)})")
assert not bugs, bugs
