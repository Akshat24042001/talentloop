# Interview scheduling

## Human interviews (a person interviews)

**HR**
* Adds slots in the job's hiring flow (Hiring flow > the interview round > Slots). One interviewer can't offer two
  overlapping times, across all jobs; overlapping slots are skipped and the count is shown.
* When new slots are added, candidates still waiting to book are emailed "New interview times" (at most once a day).
* From the application drawer: **Book a time for them** (any open slot), **Change the time**, **Cancel booking** (with a
  reason the candidate sees). An HR booking does not use up the candidate's changes. Booking history is kept.
* Sees "None of the open times work for them" with the candidate's suggested times. HR and interviewers are emailed.

**Candidate** (from the link in their email, their status page, or signed in at `/me`)
* Picks a day, then a time. Times are shown in their own time zone.
* Gets a confirmation email with: date and time in the company's time zone, length, video/phone/in person,
  interviewer, join link (or venue), a link to change or cancel, an add-to-calendar link, their status page,
  `/me`, and a calendar invite attached.
* Can **change the time** or **cancel** up to 3 times (setting) and until 2 hours before (setting). The old slot is
  freed immediately for other candidates. After the limit or inside the cut-off, the page explains why and says to
  contact the hiring team.
* Can say **None of these times work** and suggest times.
* Reminders: a day before and an hour before, with the join link and the change link. A no-show is marked 30 minutes
  after the end if they never opened the join link.

**Calendar invites** use one event per interview: a reschedule updates it (same UID, higher SEQUENCE) and a
cancellation removes it (METHOD:CANCEL). The interviewer gets the same, and is told when a candidate moves away from
their slot or cancels.

## AI interviews (run by the platform)

* The candidate can **start now**, or **book a start time** (30-minute steps, inside the company's hours, default
  08:00 to 22:00, before their deadline). Setting: "Candidates can book a time".
* Capacity: a time is only offered while fewer than `AI_SLOT_CAPACITY` (env, default 10) booked AI interviews
  overlap it, across every company on this server, because the voice provider limits calls running at once.
  Set it to your Vapi plan's concurrent-call limit.
* Confirmation email with the interview link, calendar invite, change/cancel link; reminders a day before, an hour
  before and at the start time. Change or cancel up to 5 times (setting), until 30 minutes before.
* The candidate can still start earlier. A booked time missed by 2 hours is released and they are emailed to pick a
  new time or start before their deadline. The interview link stays valid past the booked time.
* HR can book, move or cancel the time from the drawer.

## Time zones

Every time in an email, WhatsApp message or reminder is in the company's time zone (Settings > time zone, default
Asia/Kolkata) with its label, for example "Tue 06 Oct 2026, 03:00 PM IST". The server runs in UTC; before this,
emails showed UTC times. Web pages show the viewer's own time zone.

## Candidate sign-in (`/me`)

Candidates type the email they applied with and get a 6-digit code (valid about 10 minutes, works once). They then
see every application made with that email, at any company on this server, with the current step, interview time
and links to act. The code is never shown in a company's outbox. The session lasts 30 days on that browser.

Tests: `python -m tests.test_scheduling` (70 checks) and `python -m tests.e2e_scheduling` (browser).
