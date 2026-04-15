const BASE = ''  // Vite proxy handles routing to backend

async function fetchJSON<T>(url: string, opts?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), opts?.timeoutMs ?? 10000)
  try {
    const res = await fetch(`${BASE}${url}`, { ...opts, signal: controller.signal })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json()
  } finally {
    clearTimeout(timeout)
  }
}

export interface Session {
  id: string
  name: string
  status: string
}

export interface Terminal {
  id: string
  name: string
  provider: string
  session_name: string
  agent_profile: string | null
  status: string | null
  last_active: string | null
}

export interface SessionDetail {
  session: Session
  terminals: TerminalMeta[]
}

export interface TerminalMeta {
  id: string
  tmux_session: string
  tmux_window: string
  provider: string
  agent_profile: string | null
  last_active: string | null
}

export interface AgentProfileInfo {
  name: string
  description: string
  source: 'built-in' | 'local' | 'claude_code' | 'codex' | 'installed' | 'custom'
}

export interface AgentDirsSettings {
  agent_dirs: Record<string, string>
  extra_dirs: string[]
}

export interface InboxMessage {
  id: string
  sender_id: string
  receiver_id: string
  message: string
  status: 'pending' | 'delivered' | 'failed'
  created_at: string | null
}

export interface Flow {
  name: string
  file_path: string
  schedule: string
  agent_profile: string
  provider: string
  script: string | null
  last_run: string | null
  next_run: string | null
  enabled: boolean
  prompt_template: string | null
}

export interface EvolutionTask {
  task_id: string
  name: string
  description: string
  attempt_count: number
  best_score: number | null
}

export interface EvolutionAttempt {
  run_id: string
  agent_id: string
  task_id: string
  title: string
  score: number | null
  status: string
  timestamp: string
  feedback: string
  score_detail?: Record<string, number>
}

export interface EvolutionNote {
  filename: string
  meta: Record<string, string>
  content: string
}

export interface EvolutionSkill {
  name: string
  meta: Record<string, string>
  content: string
}

export interface EvolutionKnowledgeResult {
  type: string
  name: string
  snippet: string
  tags: string
}

export interface RecallResult {
  doc_id: string
  type: string
  title: string
  tags: string[]
  score: number
  snippet: string
  meta: Record<string, string>
  content?: string
}

export interface ReportFinding {
  finding_id: string
  description: string
  severity: string
  file_path: string
  line: number | null
  category: string
}

export interface HumanLabel {
  finding_id: string
  verdict: 'tp' | 'fp' | 'uncertain'
  severity_override?: string
  comment: string
  annotated_by: string
}

export interface Report {
  report_id: string
  task_id: string
  agent_id: string
  terminal_id: string
  findings: ReportFinding[]
  auto_score: number | null
  human_score: number | null
  human_labels: HumanLabel[]
  status: 'pending' | 'annotated'
  submitted_at: string
  annotated_at: string | null
}

export interface ReportStats {
  total: number
  pending: number
  annotated: number
  tp: number
  fp: number
  uncertain: number
  precision: number | null
}

export interface ProviderInfo {
  name: string
  binary: string
  installed: boolean
}

export const api = {
  // Agent Profiles & Providers
  listProfiles: () => fetchJSON<AgentProfileInfo[]>('/agents/profiles'),
  listProviders: () => fetchJSON<ProviderInfo[]>('/agents/providers'),

  // Settings
  getAgentDirs: () => fetchJSON<AgentDirsSettings>('/settings/agent-dirs'),
  setAgentDirs: (data: { agent_dirs?: Record<string, string>; extra_dirs?: string[] }) =>
    fetchJSON<AgentDirsSettings>('/settings/agent-dirs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Sessions
  listSessions: () => fetchJSON<Session[]>('/sessions'),
  getSession: (name: string) => fetchJSON<SessionDetail>(`/sessions/${name}`),
  createSession: (provider: string, agentProfile: string, sessionName?: string, workingDirectory?: string) =>
    fetchJSON<Terminal>(`/sessions?provider=${provider}&agent_profile=${agentProfile}${sessionName ? `&session_name=${sessionName}` : ''}${workingDirectory ? `&working_directory=${encodeURIComponent(workingDirectory)}` : ''}`, { method: 'POST', timeoutMs: 90000 }),
  deleteSession: (name: string) => fetchJSON<{ success: boolean; deleted: string[]; errors: any[] }>(`/sessions/${name}`, { method: 'DELETE' }),

  // Terminals
  getTerminalStatus: (id: string) =>
    fetchJSON<Terminal>(`/terminals/${id}`).then(t => t.status),
  getTerminalOutput: (id: string, mode: 'full' | 'last' = 'full') =>
    fetchJSON<{ output: string; mode: string }>(`/terminals/${id}/output?mode=${mode}`),
  sendInput: (id: string, message: string) =>
    fetchJSON<{ success: boolean }>(`/terminals/${id}/input?message=${encodeURIComponent(message)}`, { method: 'POST' }),
  exitTerminal: (id: string) =>
    fetchJSON<{ success: boolean }>(`/terminals/${id}/exit`, { method: 'POST' }),
  deleteTerminal: (id: string) => fetchJSON<{ success: boolean }>(`/terminals/${id}`, { method: 'DELETE' }),
  getWorkingDirectory: (id: string) =>
    fetchJSON<{ working_directory: string | null }>(`/terminals/${id}/working-directory`),
  addTerminalToSession: (sessionName: string, provider: string, agentProfile: string, workingDirectory?: string) =>
    fetchJSON<Terminal>(`/sessions/${sessionName}/terminals?provider=${provider}&agent_profile=${agentProfile}${workingDirectory ? `&working_directory=${encodeURIComponent(workingDirectory)}` : ''}`, { method: 'POST', timeoutMs: 90000 }),

  // Inbox
  getInboxMessages: (terminalId: string, limit?: number, status?: string) =>
    fetchJSON<InboxMessage[]>(`/terminals/${terminalId}/inbox/messages?limit=${limit || 50}${status ? `&status=${status}` : ''}`),
  sendInboxMessage: (receiverId: string, senderId: string, message: string) =>
    fetchJSON<{ success: boolean }>(`/terminals/${receiverId}/inbox/messages?sender_id=${senderId}&message=${encodeURIComponent(message)}`, { method: 'POST' }),

  // Flows
  listFlows: () => fetchJSON<Flow[]>('/flows'),
  createFlow: (data: { name: string; schedule: string; agent_profile: string; provider?: string; prompt_template: string }) =>
    fetchJSON<Flow>('/flows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      timeoutMs: 30000,
    }),
  deleteFlow: (name: string) => fetchJSON<{ success: boolean }>(`/flows/${name}`, { method: 'DELETE' }),
  enableFlow: (name: string) => fetchJSON<{ success: boolean }>(`/flows/${name}/enable`, { method: 'POST' }),
  disableFlow: (name: string) => fetchJSON<{ success: boolean }>(`/flows/${name}/disable`, { method: 'POST' }),
  runFlow: (name: string) => fetchJSON<{ executed: boolean }>(`/flows/${name}/run`, { method: 'POST', timeoutMs: 90000 }),

  // Evolution
  listTasks: () => fetchJSON<EvolutionTask[]>('/evolution/tasks'),
  getLeaderboard: (taskId: string, topN = 20) =>
    fetchJSON<EvolutionAttempt[]>(`/evolution/${taskId}/leaderboard?top_n=${topN}`),
  getAttempts: (taskId: string) =>
    fetchJSON<EvolutionAttempt[]>(`/evolution/${taskId}/attempts`),
  listNotes: (tags = '') =>
    fetchJSON<EvolutionNote[]>(`/evolution/knowledge/notes${tags ? `?tags=${encodeURIComponent(tags)}` : ''}`),
  listSkills: () => fetchJSON<EvolutionSkill[]>('/evolution/knowledge/skills'),
  searchKnowledge: (query: string, tags = '', topK = 10) =>
    fetchJSON<EvolutionKnowledgeResult[]>(`/evolution/knowledge/search?query=${encodeURIComponent(query)}&tags=${encodeURIComponent(tags)}&top_k=${topK}`),
  recallKnowledge: (query: string, tags = '', topK = 10, includeContent = false) =>
    fetchJSON<RecallResult[]>(`/evolution/knowledge/recall?query=${encodeURIComponent(query)}&tags=${encodeURIComponent(tags)}&top_k=${topK}&include_content=${includeContent}`),
  getDocument: (docId: string) =>
    fetchJSON<RecallResult>(`/evolution/knowledge/document/${encodeURIComponent(docId)}`),

  // Reports / Human Feedback
  listReports: (taskId: string, terminalId = '', status = '') =>
    fetchJSON<Report[]>(`/evolution/${taskId}/reports?terminal_id=${encodeURIComponent(terminalId)}&status=${encodeURIComponent(status)}`),
  getReportStats: (taskId: string) =>
    fetchJSON<ReportStats>(`/evolution/${taskId}/reports/stats`),
  annotateReport: (taskId: string, reportId: string, body: { human_score?: number | null; labels: Array<{ finding_id: string; verdict: string; comment?: string }>; annotated_by?: string }) =>
    fetchJSON<{ status: string; report_id: string }>(`/evolution/${taskId}/reports/${reportId}/annotate`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}
