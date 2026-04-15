import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EvolutionPanel } from '../components/EvolutionPanel'

// Mock the api module
vi.mock('../api', () => ({
  api: {
    listTasks: vi.fn(),
    getLeaderboard: vi.fn(),
    getAttempts: vi.fn(),
    listNotes: vi.fn(),
    listSkills: vi.fn(),
    searchKnowledge: vi.fn(),
    listReports: vi.fn(),
    getReportStats: vi.fn(),
    annotateReport: vi.fn(),
  },
  // Re-export types (they're just interfaces, no runtime value)
  EvolutionTask: undefined,
  EvolutionAttempt: undefined,
  EvolutionNote: undefined,
  EvolutionSkill: undefined,
}))

import { api } from '../api'

const mockTasks = [
  { task_id: 'task-1', name: 'Scan Task', description: 'Test task', attempt_count: 3, best_score: 0.85 },
  { task_id: 'task-2', name: 'Audit Task', description: 'Second', attempt_count: 1, best_score: 0.5 },
]

const mockLeaderboard = [
  {
    run_id: 'r1', agent_id: 'agent-a', task_id: 'task-1', title: 'First attempt',
    score: 0.85, status: 'improved', timestamp: '2025-01-01T12:00:00Z', feedback: 'Good',
    score_detail: { accuracy: 0.9, coverage: 0.8 },
  },
  {
    run_id: 'r2', agent_id: 'agent-b', task_id: 'task-1', title: 'Second attempt',
    score: 0.7, status: 'baseline', timestamp: '2025-01-01T11:00:00Z', feedback: 'OK',
  },
]

const mockAttempts = mockLeaderboard

const mockNotes = [
  { filename: 'note-1.md', meta: { title: 'Finding patterns', tags: 'scan,security' }, content: 'Some note content here' },
]

const mockSkills = [
  { name: 'entry-scan', meta: { tags: 'scanning' }, content: 'Skill content' },
]

const mockReports = [
  {
    report_id: 'rpt-001',
    task_id: 'task-1',
    agent_id: 'agent-a',
    terminal_id: 'term-1',
    findings: [
      { finding_id: 'f-0', description: 'SQL injection in login.py', severity: 'high', file_path: 'login.py', line: 42, category: 'injection' },
      { finding_id: 'f-1', description: 'XSS in template', severity: 'medium', file_path: 'template.html', line: 10, category: 'xss' },
    ],
    auto_score: 0.7,
    human_score: null,
    human_labels: [],
    status: 'pending',
    submitted_at: '2025-01-01T12:00:00Z',
    annotated_at: null,
  },
  {
    report_id: 'rpt-002',
    task_id: 'task-1',
    agent_id: 'agent-b',
    terminal_id: 'term-2',
    findings: [
      { finding_id: 'f-0', description: 'Open redirect', severity: 'medium', file_path: 'redirect.py', line: 5, category: 'redirect' },
    ],
    auto_score: 0.5,
    human_score: 0.8,
    human_labels: [{ finding_id: 'f-0', verdict: 'tp', comment: 'Confirmed', annotated_by: 'user1' }],
    status: 'annotated',
    submitted_at: '2025-01-01T11:00:00Z',
    annotated_at: '2025-01-01T13:00:00Z',
  },
]

const mockStats = {
  total: 2,
  pending: 1,
  annotated: 1,
  tp: 1,
  fp: 0,
  uncertain: 0,
  precision: 1.0,
}

describe('EvolutionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.listTasks as any).mockResolvedValue(mockTasks)
    ;(api.getLeaderboard as any).mockResolvedValue(mockLeaderboard)
    ;(api.getAttempts as any).mockResolvedValue(mockAttempts)
    ;(api.listNotes as any).mockResolvedValue(mockNotes)
    ;(api.listSkills as any).mockResolvedValue(mockSkills)
    ;(api.searchKnowledge as any).mockResolvedValue([])
    ;(api.listReports as any).mockResolvedValue(mockReports)
    ;(api.getReportStats as any).mockResolvedValue(mockStats)
    ;(api.annotateReport as any).mockResolvedValue({ status: 'annotated', report_id: 'rpt-001' })
  })

  it('renders loading state then content', async () => {
    render(<EvolutionPanel />)
    // Initially shows loading
    expect(screen.getByText('Loading evolution data...')).toBeInTheDocument()
    // After data loads
    await waitFor(() => {
      expect(screen.getByText('Evolution')).toBeInTheDocument()
    })
  })

  it('displays tasks in selector', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Evolution')).toBeInTheDocument()
    })
    // Task selector should contain both tasks — find by the select with task options
    const selects = screen.getAllByRole('combobox') as HTMLSelectElement[]
    const taskSelect = selects.find(s => Array.from(s.options).some(o => o.text.includes('Scan Task')))!
    expect(taskSelect).toBeTruthy()
    expect(Array.from(taskSelect.options).some(o => o.text.includes('Scan Task'))).toBe(true)
    expect(Array.from(taskSelect.options).some(o => o.text.includes('Audit Task'))).toBe(true)
  })

  it('shows leaderboard with scores', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Leaderboard')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('agent-a')).toBeInTheDocument()
    })
    expect(screen.getByText('agent-b')).toBeInTheDocument()
    expect(screen.getByText('0.8500')).toBeInTheDocument()
    expect(screen.getByText('0.7000')).toBeInTheDocument()
  })

  it('displays status pills', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('improved')).toBeInTheDocument()
    })
    expect(screen.getByText('baseline')).toBeInTheDocument()
  })

  it('shows score dimensions for best attempt', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Score Dimensions')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('accuracy')).toBeInTheDocument()
    })
    expect(screen.getByText('coverage')).toBeInTheDocument()
  })

  it('shows knowledge base with notes and skills', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
    })
    expect(screen.getByText('Notes (1)')).toBeInTheDocument()
    expect(screen.getByText('Skills (1)')).toBeInTheDocument()
    expect(screen.getByText('Finding patterns')).toBeInTheDocument()
    expect(screen.getByText('entry-scan')).toBeInTheDocument()
  })

  it('expands note content on click', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Finding patterns')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('Finding patterns'))
    expect(screen.getByText('Some note content here')).toBeInTheDocument()
  })

  it('expands skill content on click', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('entry-scan')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('entry-scan'))
    expect(screen.getByText('Skill content')).toBeInTheDocument()
  })

  it('shows summary stats in header', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText(/2 tasks/)).toBeInTheDocument()
    })
    expect(screen.getByText(/1 note/)).toBeInTheDocument()
    expect(screen.getByText(/1 skill/)).toBeInTheDocument()
  })

  it('performs knowledge search', async () => {
    ;(api.searchKnowledge as any).mockResolvedValue([
      { type: 'note', name: 'result-1', snippet: 'Found something', tags: 'scan' },
    ])
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Knowledge Search')).toBeInTheDocument()
    })
    const input = screen.getByPlaceholderText('Search notes & skills...')
    fireEvent.change(input, { target: { value: 'scan' } })
    fireEvent.click(screen.getByText('Search'))
    await waitFor(() => {
      expect(screen.getByText('result-1')).toBeInTheDocument()
      expect(screen.getByText('Found something')).toBeInTheDocument()
    })
  })

  it('handles empty state gracefully', async () => {
    ;(api.listTasks as any).mockResolvedValue([])
    ;(api.listNotes as any).mockResolvedValue([])
    ;(api.listSkills as any).mockResolvedValue([])
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('No tasks')).toBeInTheDocument()
    })
    expect(screen.getByText('No notes shared yet.')).toBeInTheDocument()
    expect(screen.getByText('No skills shared yet.')).toBeInTheDocument()
  })

  it('calls refresh on button click', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByTitle('Refresh')).toBeInTheDocument()
    })
    // Reset mock counts
    ;(api.listTasks as any).mockClear()
    ;(api.listNotes as any).mockClear()
    ;(api.listSkills as any).mockClear()
    ;(api.listTasks as any).mockResolvedValue(mockTasks)
    ;(api.listNotes as any).mockResolvedValue(mockNotes)
    ;(api.listSkills as any).mockResolvedValue(mockSkills)

    fireEvent.click(screen.getByTitle('Refresh'))
    await waitFor(() => {
      expect(api.listTasks).toHaveBeenCalledTimes(1)
    })
  })

  // ── Reports & Feedback tests ───────────────────────────────────────

  it('shows Reports & Feedback section', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Reports & Feedback')).toBeInTheDocument()
    })
  })

  it('displays report stats', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('Total: 2')).toBeInTheDocument()
    })
    expect(screen.getByText('Pending: 1')).toBeInTheDocument()
    expect(screen.getByText('Annotated: 1')).toBeInTheDocument()
    expect(screen.getByText('TP: 1')).toBeInTheDocument()
    expect(screen.getByText('FP: 0')).toBeInTheDocument()
  })

  it('shows report entries with agent and status', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('rpt-001')).toBeInTheDocument()
    })
    expect(screen.getByText('rpt-002')).toBeInTheDocument()
    expect(screen.getByText('by agent-a')).toBeInTheDocument()
    expect(screen.getByText('by agent-b')).toBeInTheDocument()
  })

  it('expands report to show findings', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('rpt-001')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('rpt-001'))
    await waitFor(() => {
      expect(screen.getByText('SQL injection in login.py')).toBeInTheDocument()
      expect(screen.getByText('XSS in template')).toBeInTheDocument()
    })
  })

  it('shows annotate button on expanded report', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('rpt-001')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('rpt-001'))
    await waitFor(() => {
      expect(screen.getByText('Annotate')).toBeInTheDocument()
    })
  })

  it('shows verdict labels for annotated report', async () => {
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('rpt-002')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('rpt-002'))
    await waitFor(() => {
      expect(screen.getByText('TP')).toBeInTheDocument()
    })
  })

  it('handles empty reports state', async () => {
    ;(api.listReports as any).mockResolvedValue([])
    ;(api.getReportStats as any).mockResolvedValue({ total: 0, pending: 0, annotated: 0, tp: 0, fp: 0, uncertain: 0, precision: null })
    render(<EvolutionPanel />)
    await waitFor(() => {
      expect(screen.getByText('No reports yet.')).toBeInTheDocument()
    })
  })
})
