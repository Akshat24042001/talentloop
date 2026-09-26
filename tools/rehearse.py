"""Text rehearsal: run an interview by TYPING answers, no voice, no Vapi minutes spent.

Use it to tune prompts and check the flow before real calls. It hits the exact same
endpoint Vapi calls, so behaviour is identical except for speech recognition and timing.

  python -m tools.rehearse                      # creates a sample interview, you type answers
  python -m tools.rehearse --id <interview_id>  # use an interview created in the HR page
  python -m tools.rehearse --script answers.txt # one answer per line, non-interactive

Server must be running (uvicorn backend.main:app --port 8000).
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def sse_text(resp: httpx.Response) -> str:
    out = []
    for line in resp.text.splitlines():
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            d = json.loads(line[6:])["choices"][0]["delta"]
            out.append(d.get("content", ""))
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--id")
    ap.add_argument("--script")
    ap.add_argument("--key", default=os.getenv("ADMIN_KEY", ""))
    a = ap.parse_args()
    h = {"X-Admin-Key": a.key} if a.key else {}
    c = httpx.Client(base_url=a.base, timeout=180, headers=h)

    iid = a.id
    if not iid:
        s = ROOT / "web" / "samples"
        inp = {"company": "Demo Tech Pvt Ltd", "role": "Java Backend Developer", "candidate_name": "Rohan Mehta",
               "duration_min": 15, "jd": (s / "sample_jd.txt").read_text(), "resume": (s / "sample_resume.txt").read_text(),
               "questions": [q for q in (s / "sample_questions.txt").read_text().splitlines() if q.strip()]}
        print("Generating plan...")
        plan = c.post("/api/plan", json=inp).raise_for_status().json()["plan"]
        for q in plan["questions"]:
            print(f"  {q['id']} [{q['type']}] {q['ask']}")
        iid = c.post("/api/interviews", json={"plan": plan, "inputs": inp}).raise_for_status().json()["id"]
        print(f"Interview id: {iid}\n")

    r = c.post(f"/api/interviews/{iid}/assistant")
    if r.status_code != 200:
        sys.exit(f"Cannot start: {r.text}  (PUBLIC_URL and VAPI_PUBLIC_KEY must be set even for rehearsal)")
    first = r.json()["assistant"]["firstMessage"]
    llm_path = "/llm/" + r.json()["assistant"]["model"]["url"].split("/llm/", 1)[1] + "/chat/completions"
    messages = [{"role": "system", "content": "x"}, {"role": "assistant", "content": first}]
    print(f"AI: {first}\n")

    scripted = Path(a.script).read_text().splitlines() if a.script else None
    while True:
        if scripted is not None:
            if not scripted:
                break
            ans = scripted.pop(0)
            print(f"YOU: {ans}")
        else:
            ans = input("YOU: ").strip()
            if ans in ("/quit", "/q"):
                break
        messages.append({"role": "user", "content": ans})
        resp = c.post(llm_path, json={"messages": messages, "stream": True})
        say = sse_text(resp)
        messages.append({"role": "assistant", "content": say})
        print(f"AI: {say}\n")
        if "concludes our interview" in say.lower():
            break

    c.post(f"/api/interviews/{iid}/complete")
    print("Scoring...")
    c.post(f"/api/interviews/{iid}/score").raise_for_status()
    import time
    for _ in range(120):
        rec = c.get(f"/api/interviews/{iid}").json()
        if rec.get("report") or (rec.get("scoring") or {}).get("state") == "failed":
            break
        time.sleep(2)
    if not rec.get("report"):
        sys.exit(f"Scoring failed: {(rec.get('scoring') or {}).get('error')}")
    rep = rec["report"]
    print(json.dumps({k: rep.get(k) for k in ("recommendation", "confidence", "summary", "computed",
                                                "human_review_reasons")}, indent=2))
    print(f"\nFull report: {a.base}/report.html?id={iid}")


if __name__ == "__main__":
    main()
