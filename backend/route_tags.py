"""OpenAPI tags for every endpoint, so /docs groups them by area (first matching rule wins).

Paths are matched with their parameters as written, e.g. /api/jobs/{job_id}/flow. Anything not covered falls into
"Other" (a new endpoint shows up there until it gets a rule)."""
from fastapi.routing import APIRoute

RULES: list[tuple[tuple[str, ...], str]] = [
    (("/api/health", "/api/ping", "/healthz"), "Health"),
    (("/api/auth",), "Auth and session"),
    (("/api/me",), "Candidate and placement-officer sign-in (/me)"),
    (("/api/public/",), "Public: careers page, job posts, logos"),
    (("/api/r/", "/api/status/", "/api/decide/", "/api/feedback/", "/api/ref/", "/api/results/", "/api/drive/"), "Guest links: candidates, approvers, interviewers, referees, placement officers"),
    (("/api/platform", "/api/admin", "/api/console", "/api/demo"), "Platform admin"),
    (("/api/org",), "Company settings"),
    (("/api/team", "/api/invites", "/api/invite", "/api/members", "/api/memberships", "/api/switch"), "Team and roles"),
    (("/api/drives", "/api/jobs/{job_id}/drives"), "Campus drives"),
    (("/api/questions",), "Question bank"),
    (("/api/jobs/{job_id}/insights", "/api/jobs/{job_id}/calibration", "/api/jobs/{job_id}/integrity-scan", "/api/jobs/{job_id}/compare"), "Job insights"),
    (("/api/jobs/{job_id}/flow", "/api/flow-meta", "/api/flow-templates", "/api/round-results", "/api/applications", "/api/jobs/{job_id}/pipeline",
      "/api/jobs/{job_id}/rounds", "/api/slots", "/api/my-interviews", "/api/jobs/{job_id}/applications"), "Hiring flows, pipeline and scheduling"),
    (("/api/match", "/api/jobs/{job_id}/match"), "Matching and match reports"),
    (("/api/jobs",), "Jobs"),
    (("/api/candidates",), "Candidates and resume checks"),
    (("/api/interviews", "/api/calibration", "/api/plan", "/api/extract"), "AI interviews"),
    (("/api/messages", "/api/requests", "/api/outbox"), "Messages and requests"),
    (("/api/dashboard",), "Dashboard"),
    (("/api/reports", "/api/audit", "/api/exports", "/api/hrone"), "Reports, exports and audit"),
    (("/llm/", "/webhook/", "/api/vapi"), "Voice provider callbacks (Vapi)"),
    (("/media/",), "Media files"),
]
DESCRIPTIONS = {
    "Health": "Liveness checks. /api/ping is free (no database): use it for uptime monitors and keep-awake cron jobs.",
    "Guest links": "No sign-in: a long random token in the link is the permission.",
}


def tag_for(path: str) -> str:
    for prefixes, tag in RULES:
        if any(path == p.rstrip("/") or path.startswith(p) for p in prefixes):
            return tag
    return "Other"


def apply(*routers) -> None:
    for r in routers:
        for route in getattr(r, "routes", []):
            if isinstance(route, APIRoute):
                route.tags = [tag_for(route.path)]
                if route.path.startswith(("/app", "/login", "/forgot", "/signup", "/careers/", "/r/", "/status/", "/decide/", "/feedback/", "/ref/",
                                          "/results/", "/drive/", "/invite/", "/me", "/admin", "/dashboard.html", "/hr.html", "/report.html")) \
                        and not route.path.startswith("/api/"):
                    route.include_in_schema = False          # web pages, not API endpoints


def openapi_tags() -> list[dict]:
    seen = []
    for _, t in RULES:
        if t not in seen:
            seen.append(t)
    return [{"name": t, **({"description": DESCRIPTIONS[t.split(":")[0]]} if t.split(":")[0] in DESCRIPTIONS else {})} for t in seen + ["Other"]]
