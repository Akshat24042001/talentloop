# What sets TalentLoop apart

What most AI interview and assessment platforms already offer (so it is table stakes, not a differentiator): voice AI
interviews with follow-up questions, proctoring (tab switches, faces, second screens), identity checks, coding
assessments, self-scheduling, ATS integrations and talent rediscovery.

Sources checked (October 2026): goodfit.so/guides/best-ai-interview-platforms,
herohunt.ai/blog/best-ai-candidate-interviewers-2026, talview.com/en/talview-vs-hirevue, glider.ai. "Not found" below
means we did not see it on those pages; a competitor may still have it. Verify before using any claim in marketing.

| # | Feature | Where in the app | Why it matters | Seen elsewhere? |
|---|---------|------------------|----------------|-----------------|
| 1 | **Evidence-locked interview scores.** A competency is scored only when a verbatim quote from the candidate backs it; unanswered questions show "not answered" instead of a guess. | AI interview report | Removes the most common complaint about AI interviews: scores the candidate never earned. | Not found |
| 2 | **Interview plan grounding and turn guards.** Questions come only from the JD and resume; every AI line is checked before it is spoken (no invented facts, no drifting, no early endings, safe fallback line on any error). See `docs/AI_INTERVIEW_RELIABILITY.md`. | AI interview | The "random direction / ends suddenly / hallucinates" failure modes. | Others claim reliability; no per-turn guard design found |
| 3 | **Live task with screen sharing.** Timed coding, design or spreadsheet work while sharing the whole screen; server clock, autosave, auto-submit. AI reviews the result and, with `VISION_MODEL` set, screenshots of how they worked. | Hiring flow: Live task round | Shows how someone works, not just the final answer. | Coding tests are common; AI review of the process across any tool not found |
| 4 | **Copied answers across candidates.** Shared wording in interview answers and live-task work (boilerplate removed), the same wrong test options, one phone on two records, each with evidence. | Job, Insights tab | Single-candidate proctoring cannot see collusion or leaked answers, which are common in campus hiring. | Not found |
| 5 | **AI vs your team.** Agreement between people's decisions and the AI per round, score gap, biggest disagreements, and a pass-mark suggestion. | Job, Insights tab | Lets a company check the AI with its own decisions; the evidence a bias or AI audit asks for. | Not found as a built-in report |
| 6 | **Reference checks with fake-reference flags.** No-login referee form, score from ratings only, AI summary with quotes, flags for same network as the candidate, two referees on one network, forms filled in seconds. | Hiring flow: Reference check round | References are usually skipped or done by phone; fakes are common. | Dedicated tools (for example Crosschq) do references; inside an interview platform not found |
| 7 | **Answer-key verification for AI-drafted questions.** A second AI pass solves each drafted question; disagreements are flagged before the question enters the bank. Questions can be drafted from a job's JD. | Question bank | AI-written MCQs with wrong answer keys silently fail good candidates. | Not found |
| 8 | **Communication signals without emotion AI.** Talk share, answer length, fillers, hedges, specifics, I/we ownership and tone words, all computed from the transcript. No face or voice emotion inference (prohibited for hiring in the EU, AI Act art. 5(1)(f)). | AI interview report | "Sentiment" that is explainable and legal. | Several vendors sell facial or voice emotion scoring; the text-only, explainable approach not found |
| 9 | **Feedback every candidate can use.** AI drafts specific feedback from completed rounds only (never integrity flags or private notes); a person edits and sends. | Application drawer | Candidate experience and employer brand, especially at campuses. | Not found as a one-click draft |
| 10 | **India-first campus hiring.** Hinglish and 8 Indian languages in AI interviews, multi-role campus drives with QR registration, and live results for placement officers. | Campus drives, AI interview | Most tools are built for the US or EU market. | Partial elsewhere |

Also built in: side-by-side comparison of 2-5 candidates, transparency notes on every candidate step ("How this step
works"), a way for candidates to ask for a human interviewer, and accommodations with extra time.

## Not built, and why

* **AI watching the screen in real time during the voice interview.** Streaming screen frames to a vision model while
  it also speaks adds seconds of delay per turn and a large cost per minute. The Live task round covers the need with an
  after-the-fact review of the screenshots instead.
* **Facial emotion or voice stress analysis.** Unreliable, and banned for recruitment in the EU (AI Act art. 5(1)(f)).
* **Fully automatic rejection on integrity flags.** Flags always go to a person.
