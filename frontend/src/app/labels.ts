import type { Tone } from '../lib/format'

export const ACTION_LABEL: Record<string, string> = {
  job_created: 'Job created', job_edited: 'JD edited', job_status: 'Status', job_deleted: 'Job deleted', collaborator_added: 'Access given',
  collaborator_removed: 'Access removed', candidate_added: 'Candidate', candidate_updated: 'Resume updated', candidate_deleted: 'Deleted',
  candidate_added_to_job: 'Added to job', application_received: 'Applied', talent_pool_joined: 'Talent pool', stage_changed: 'Stage',
  ai_reports: 'AI reports', member_invited: 'Invited', member_joined: 'Joined', member_updated: 'Role', member_removed: 'Removed',
  settings_updated: 'Settings', interview_created: 'Interview', demo_seeded: 'Samples', company_created: 'Workspace',
}
export const JOB_STATUS: Record<string, { label: string; tone: Tone }> = {
  draft: { label: 'Draft', tone: 'neutral' }, open: { label: 'Open', tone: 'success' }, paused: { label: 'Paused', tone: 'warning' }, closed: { label: 'Closed', tone: 'neutral' },
}
export const STAGE_TONE: Record<string, Tone> = {
  applied: 'brand', screening: 'violet', shortlisted: 'violet', interview: 'warning', offer: 'success', hired: 'success', rejected: 'danger', withdrawn: 'neutral',
}
export const VERDICT: Record<string, { label: string; tone: Tone }> = {
  strong: { label: 'Strong fit', tone: 'success' }, good: { label: 'Good fit', tone: 'brand' }, possible: { label: 'Possible', tone: 'warning' }, weak: { label: 'Weak fit', tone: 'neutral' },
}
export const SOURCE_LABEL: Record<string, string> = { bulk: 'Resume upload', careers: 'Careers page', talent_pool: 'Talent pool', manual: 'Added by HR', demo: 'Sample data', sourced: 'Sourced' }

/** Who did it: a team member, the candidate (applications), or the system. */
export function actor(a: { action: string; user?: string | null }): string {
  return a.user || (['application_received', 'talent_pool_joined'].includes(a.action) ? 'Candidate' : a.action === 'member_joined' ? 'Invite accepted' : 'TalentLoop')
}
