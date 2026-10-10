# AI interview: how it works, what catches cheating, what does not

Written for people who need to explain this to someone else. Every line says what the code does today, not what we wish it did.
Where something cannot be done from a web page, it says so.

## 1. How an AI interview works, in plain words

Three separate systems run one interview. When something feels wrong, find which of the three it is.

| System | Job | Where the code is |
|---|---|---|
| The candidate's browser | Camera, microphone, screen, all cheating checks, recording | `frontend/src/interview/` |
| Vapi (outside company) | Listens (speech to text), decides when the candidate has finished talking (turn taking), speaks (text to speech) | `backend/vapi_config.py` |
| Our server | Decides every word the interviewer says, keeps the state, scores | `backend/brain.py`, `backend/prompts.py` |

The order of an interview:

1. HR makes the interview: the AI reads the job description and resume and writes a plan (`brain.generate_plan`): warm-up, HR's mandatory questions, resume probes, skill questions.
2. The candidate opens the private link, enters the 6-digit code, ticks consent.
3. System check in the browser: camera, microphone, face, head-turn, earphones, **room scan**, single screen, screen share.
4. The call starts. For each answer, Vapi sends the words to our server. Our code picks the action (next question, follow-up, repeat, answer a question about the role) and the AI model only writes the sentence. This is why the interviewer cannot skip HR's questions or run over time.
5. During the call the browser keeps checking (tab switches, faces, eyes, lips, voices, phones) and sends events. Rule-breaking beyond HR's warning limit ends the call.
6. After the call: transcript, scoring with quotes, and a proctoring report for a human to review.

Nothing in the cheating checks makes a final decision about a person. They produce evidence and flags. A person at the company decides.

## 2. What was wrong, and what is now fixed

| # | Problem you reported | Cause found in the code | Fix |
|---|---|---|---|
| 1 | Room scan passes if you hold the laptop still or wiggle it | It took one picture per second for 12 seconds and only looked for two people at once. It never checked that the camera moved. | `roomscan.ts` measures the camera's rotation from the pictures themselves. It completes only when about 330 degrees of the circle were in view, and the camera was tilted up (ceiling) and down (floor, under the desk). Takes up to 90 s, not 12. Shows live progress and tells the candidate what to do next. Tested on synthetic panoramas and on real Chromium camera frames (a 400 degree turn is measured as 403). |
| 2 | Someone sitting behind or beside you is missed | Same cause. Also the AI photo check saw only 3 photos. | Up to 8 photos spread round the room plus the ceiling and floor go to the AI check. A person detected while the camera faces more than 75 degrees away from the candidate is flagged, sent first, and fails the scan if the AI confirms (or if the AI is off and it is seen twice). A scan that is incomplete or unreadable never passes. The AI is told that the candidate is usually not in room photos, so any real person is "someone else". |
| 3 | Notes, whiteboards, second screens in the room | Not asked | The AI photo check now reports written notes and another screen. They go to HR as flags. |
| 4 | Two voices | Only caught a voice much higher or lower in pitch (man and woman). A helper of the same sex was missed. | `VoiceWatch` now also compares the voice colour (spectrum shape) over 3 second stretches with the candidate's own first 12 seconds. Pitch and colour both different in one stretch, or colour clearly different twice in a row, raises "second voice". Tested on synthetic speakers. **Not tested on real people yet.** |
| 5 | Follow-up questions are weak | The model saw only the last fragment of the answer. Speech to text often cuts one answer into several turns, so a full answer looked thin and a thin one looked complete. It did not know which follow-ups were already asked or which key points were still missing. | The model now gets the whole answer to the current question, the follow-ups already asked, and the key points still missing. The prompt demands that each follow-up goes one level deeper and quotes the candidate's own words. In code: if the model says "move on" but fewer than half the key points were covered and it wrote a probe, the probe is asked (while follow-ups remain). Larger token budget for the live model (it was cutting its own answers). |
| 6 | Turn taking | Could not be reproduced without a live Vapi call. | Safety net: if nobody speaks 9 s after the candidate finished, the browser asks the interviewer for its turn again (event `turn_watchdog`). A `slow_turn` event records every gap over 6 s. Not yet checked on a live call. |
| 7 | Phone numbers without a country flag and code | Plain text boxes in 5 places, and phone display in 3. Numbers from other countries were also corrupted (a 10 digit Singapore number got "91" added). | New `PhoneInput`: flag, dial code, search, formatting as you type, validation per country. Used in the careers form, candidate add and edit, the campus portal and the platform console. Display uses flag plus international format. Flags are bundled, no outside request, and show on Windows. |
| 8 | Name read as "Name: John Doe" | The name guess accepted any capitalised first line, so the label stayed. | `resumes.clean_name` removes labels (Name, Full name, Resume of, Curriculum Vitae, honorifics, degrees), cuts at separators, rejects job titles and section headers, fixes ALL CAPS, prefers a name that agrees with the email. An explicit "Name:" line wins. Used in resume reading, candidate saving and mail intake. |
| 9 | Skills missing | The resume reader knew only a fixed dictionary of about 400 skills. The JD reader put the first 6 skills **alphabetically** into must-have and the next 6 into nice-to-have, whatever the JD said. | Resume: the "Skills" section is read as written (Pinecone, LangChain, anything). JD: skills under Requirements are must-have, under Nice to have are nice-to-have, in the order written. Then an AI pass reads any layout, but nothing it returns is kept unless it is found in the document text (no invented skills). If the AI is off or fails, the free reader still works. |
| 10 | "Write with AI" seems not to work | It exists only for job descriptions (JobEditor). When no AI key is connected it returns canned filler text that looks real. There is no "Write with AI" for resumes or candidate profiles. | The page now says clearly when the text is demo wording. HR can now upload a resume in Add candidate and the details are filled in with AI (careers form already did). |

## 3. Fifty ways to cheat, and what happens

Status words: **Caught** = detected and recorded, warning or flag. **Flag** = detected sometimes, recorded for a human to review, not proof.
**Blind** = a web page cannot see it. The mitigation is stated.

### A. Another person
| # | Method | Status | What handles it |
|---|---|---|---|
| 1 | Helper sits behind the laptop, outside the camera | Caught at start | Room scan now covers the full circle and tilt. During the call only voice and eyes can hint at it (Flag). |
| 2 | Helper stands behind the candidate, in view | Caught | Person detector plus face count, warning counts toward ending |
| 3 | Helper hides behind a door, desk or monitor | Caught at start if visible in the scan. Closed spaces are Blind | Scan up and down, AI photo check |
| 4 | Helper whispers answers | Flag | Second voice (pitch and colour), voice with still lips |
| 5 | Helper shows answers on paper or a screen off camera | Flag | Eyes to the side or down, reading pattern |
| 6 | Helper enters mid-interview | Caught if in view | Person detector in the call, periodic AI photos |
| 7 | Voice from the next room or through a door | Flag | Second voice |
| 8 | Swapping the person mid-interview | Caught | Face match every 45 s, two random "turn your head" checks |
| 9 | Proxy candidate for the whole interview | Flag | Match with the registration photo. No government ID check exists. |

### B. Software and screen
| # | Method | Status | What handles it |
|---|---|---|---|
| 10 | Switch to another app | Caught | Window blur from 0.7 s |
| 11 | Switch to another browser tab | Caught | Tab hidden from 0.3 s |
| 12 | Second monitor | Caught | Display check, can require full screen share |
| 13 | Side by side windows, small window | Caught | Full screen and window size checks |
| 14 | Copy the question to an AI tool | Caught | Copy, cut events |
| 15 | Paste an answer | Caught | Paste event |
| 16 | Print Screen, shortcuts | Caught | Key events |
| 17 | Developer tools | Caught | Shortcuts and docked tools |
| 18 | AI overlay that hides from screen capture and never takes focus | **Blind** | Only indirect: eye movement, answer timing, follow-ups on specifics, human final round |
| 19 | Remote desktop or someone controlling the laptop | **Blind** | Indirect only |
| 20 | Virtual machine | **Blind** | Device details are recorded, no flag |
| 21 | Virtual camera (OBS) replaying video | Caught by device name | Also head-turn checks |
| 22 | Sharing a window instead of the whole screen | Caught | Share type check |
| 23 | Browser extension with an AI side panel | **Blind** | Indirect only |
| 24 | Picture in picture notes | **Blind** | Indirect only |
| 25 | Phone or tablet on the desk with an AI app | Flag | Phone detector, eyes down |
| 26 | Second laptop beside the screen | Flag | Screen detector, eyes to the side |

### C. Audio
| # | Method | Status | What handles it |
|---|---|---|---|
| 27 | Bluetooth earbuds or headphones | Caught | Device name, ear photos, new device mid-call |
| 28 | Tiny hidden earpiece | **Blind** | Only answer timing and lips |
| 29 | Bone conduction headset, smart glasses | **Blind** | Indirect only |
| 30 | AI voice reading answers aloud nearby | Flag | Second voice, and the interviewer's own voice is ignored as an answer |
| 31 | Muting the mic to consult | Caught | Mute events, voice while muted |
| 32 | Pre-recorded or synthetic voice | Flag | Voice with still lips, head turn checks |
| 33 | Voice changer | **Blind** | Indirect only |

### D. Notes and reading
| # | Method | Status | What handles it |
|---|---|---|---|
| 34 | Notes below the camera | Flag | Eyes down |
| 35 | Notes stuck on the monitor or wall | Flag | AI room photo check reports written notes |
| 36 | Reading from a second screen at the side | Flag | Eyes to the side, second screen detector |
| 37 | Text overlay next to the camera | Flag | Reading pattern (line by line eye sweeps) |
| 38 | Whiteboard behind the camera | Flag | Room scan photos, notes flag |
| 39 | A pre-written script | Flag | Long pause then fluent answer pattern, AI "scripted" signal, deeper follow-ups |
| 40 | Leaked questions | Flag | Plan is built from each candidate's resume, probes ask for specifics |

### E. Identity and session
| # | Method | Status | What handles it |
|---|---|---|---|
| 41 | Different person from registration | Flag | Photo match |
| 42 | Photo or video in front of the camera | Caught | Head-turn at start and twice at random |
| 43 | Live face swap | Flag at best | Random head-turn checks |
| 44 | Retrying after being stopped | Caught | Only HR can allow a retake, with a reason |
| 45 | Link open on two devices | Caught | Newest session wins, device change is recorded |
| 46 | Using a phone to avoid the laptop checks | Flag | Camera checks must load, screen share is impossible on a phone, device details are recorded |

### F. Environment
| # | Method | Status | What handles it |
|---|---|---|---|
| 47 | Anything hidden in cupboards, drawers, behind closed doors | **Blind** | Scan shows what is open; ask for the door to be open |
| 48 | Helper shown in a mirror or window reflection | Flag | The AI photo check is told to look at reflections |
| 49 | Filming the screen to share the questions | **Blind** | Unique questions per candidate reduce the damage |
| 50 | Interview in a public or noisy place | Flag | Noise reduction, second voice, room scan |

**What this means.** 19 are caught, 20 are flagged for a person, 10 cannot be seen from a web page, and 1 (hidden behind a door) depends on whether it is visible.
No product can promise "not a single instance". The honest promise is: the common methods are caught, the doubtful ones
are flagged with photos and timestamps, and the rest are made less useful by deep follow-up questions and a human final round.
If a client needs more, the only real upgrades are a proctoring desktop app or a human invigilator for high-stakes roles.

## 4. Turn taking: what I found, what I could not do

I could not run a real Vapi call in this environment. REVIEW.md says the Vapi setup has never been checked against a live call.
So I did not change timing numbers blindly.

What is in the code today (`vapi_config.py`):
- End of speech: a model that guesses if you finished a sentence (LiveKit), 0.8 s base wait, and 5 s patience after phrases like "let me think".
- Backchannels ("okay", "hmm") do not interrupt the interviewer, "wait" and "sorry" do.
- 25 s of silence gets a nudge, 120 s ends the call.
- If our model is slow, a safe spoken line is used after 8 s.

Likely causes of "the interviewer does not take its turn", in order:
1. A slow or failing live model. On free models this is common. Platform admin > System status shows the failure rate. Use a paid `FAST_MODEL`.
2. The end-of-speech model waiting too long for candidates who speak Indian English or mix Hindi. Try `ENDPOINTING_MODE=patient` (fixed wait) or `SMART_ENDPOINTING_PROVIDER=vapi`.
3. Echo: the interviewer hearing itself (headphones fix it).

Each slow turn is now an event (`slow_turn`), so the next live calls will tell us which cause it is. After 5 real calls, read the "How the call ended"
and slow turn events, then tune. I did not add a client-side watchdog that speaks for the interviewer, because a late real answer would then be spoken twice.

## 5. What to check yourself before trusting it

1. Run one real call with a colleague as the candidate, using a paid live model. Do the room scan properly, then try to cheat: whisper from a second person, look at a phone, read from a page.
2. Open the proctoring report for that call. Every attempt should show as an event with a photo.
3. Run `python -m tests.test_parsing`, `tests.test_followups`, `tests.test_behaviour` and `tests.e2e_browser` (the last starts a real Chromium and takes about 8 minutes).

## 6. Not done yet

- **Real-world tuning of the second-voice thresholds.** Synthetic voices are not people. Expect to adjust after the first real calls.
- **Write with AI for resumes and candidate profiles.** It does not exist. Say if you want it.
- **Server-side check of the room scan.** The scan is measured in the candidate's browser, so a technically skilled cheater could fake the frames. The AI photo check on the server is the second layer.
- **A way to reject a candidate whose camera cannot be measured.** Today, after 3 tries on a camera where motion cannot be followed (very dark or plain walls), the interview goes on and HR sees "room scan could not be measured". Decide if you want a stricter rule.
- **Lower priority list from the review that I did not touch:** hours of live Vapi tuning, the rest of the dashboards and reports.
