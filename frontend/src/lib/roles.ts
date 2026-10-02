// What each company role can do, in plain words (matches backend/auth.py).
export const ROLE_HELP: Record<string, string> = {
  owner: 'Everything an admin can do, plus managing owners: only an owner can make someone an owner or change or remove one. Every company keeps at least one owner.',
  admin: 'Runs the workspace: team and invites, company settings, careers page, every job and candidate, audit log.',
  recruiter: 'HR: creates and publishes jobs, manages candidates and hiring flows, runs matching and interviews.',
  hiring_manager: 'Sees only the jobs HR assigns, as JD editor or reviewer. E.g. a sales or tech manager.',
  viewer: 'Read-only access to all jobs and candidates.',
}
export const ROLE_CAN: Record<string, string[]> = {
  owner: ['Manage owners', 'Team and invites', 'Company settings', 'All jobs and candidates', 'Hiring flows and interviews', 'Audit log'],
  admin: ['Team and invites', 'Company settings', 'All jobs and candidates', 'Hiring flows and interviews', 'Audit log'],
  recruiter: ['Create and publish jobs', 'All candidates', 'Hiring flows and interviews', 'Matching and reports'],
  hiring_manager: ['Jobs assigned to you', 'Rate and comment on candidates', 'Edit the JD when you are an editor'],
  viewer: ['See all jobs and candidates', 'No changes'],
}
