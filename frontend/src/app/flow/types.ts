// Shared shapes and labels for hiring flows (see backend/flows.py).
import type { Tone } from '../../lib/format'

export type RoundType = 'application' | 'cv_screening' | 'test' | 'video_intro' | 'role_task' | 'practical_task' | 'live_task' | 'ai_interview' | 'human_interview' | 'manager_approval'
export interface Round {
  id: string; type: RoundType; name: string; pass_rule: { mode: 'min_score' | 'top_n' | 'hr_review' | 'auto_pass'; value: number }
  advance: 'auto' | 'hr'; deadline_days: number | null; message: string; config: Record<string, any>
}
export interface FlowMeta {
  round_types: { type: RoundType; label: string; description: string; stage: string; candidate: boolean }[]
  pass_modes: string[]; statuses: Record<string, string>; default_config: Record<string, any>; default_rule: Record<string, { mode: string; value: number }>
  templates: { id: string; name: string; description: string; rounds: number; custom: boolean }[]
  sections: { id: string; label: string }[]; messages: Record<string, any>
}
export interface TeamMember { id: string; name: string; email: string; role: string; title: string }
export interface RoundSummary {
  id: string; round_id: string; type: RoundType; status: string; status_label: string; score: number | null; decision: string; decided_by: string; reason: string
  suggestion?: string | null; deadline_at: number | null; started_at: number | null; completed_at: number | null; flagged: boolean; integrity: Record<string, any>
  updated_at: number; candidate_link: string; manager_link: string
}

export const PASS_LABEL: Record<string, string> = { min_score: 'Minimum score', top_n: 'Top N by score', hr_review: 'HR reviews each', auto_pass: 'Everyone passes' }
export const SHORT_LABEL: Record<RoundType, string> = {
  application: 'Application', cv_screening: 'CV screening', test: 'Test', video_intro: 'Video intro', role_task: 'Role task',
  practical_task: 'Practical task', live_task: 'Live task', ai_interview: 'AI interview', human_interview: 'Human interview', manager_approval: 'Manager approval',
}
export const STATUS_TONE: Record<string, Tone> = {
  pending: 'neutral', setting_up: 'neutral', invited: 'brand', in_progress: 'brand', booked: 'violet', submitted: 'warning', on_hold: 'warning',
  passed: 'success', failed: 'danger', expired: 'danger', no_show: 'danger', skipped: 'neutral',
}
export const LANGUAGES: [string, string][] = [['en', 'English'], ['hi', 'Hindi'], ['hi-en', 'Hinglish (Hindi + English)'], ['ta', 'Tamil'], ['te', 'Telugu'],
  ['kn', 'Kannada'], ['mr', 'Marathi'], ['bn', 'Bengali'], ['gu', 'Gujarati'], ['ml', 'Malayalam']]
export const REC_TONE: Record<string, Tone> = { Strong: 'success', Maybe: 'warning', No: 'danger' }

export function newRound(meta: FlowMeta, type: RoundType): Round {
  const label = meta.round_types.find(t => t.type === type)?.label || type
  const candidate = meta.round_types.find(t => t.type === type)?.candidate
  return {
    id: Math.random().toString(36).slice(2, 8), type, name: label, pass_rule: { ...(meta.default_rule[type] as Round['pass_rule']) },
    advance: type === 'test' ? 'auto' : 'hr', deadline_days: candidate && type !== 'application' ? 3 : null, message: '',
    config: JSON.parse(JSON.stringify(meta.default_config[type] || {})),
  }
}
