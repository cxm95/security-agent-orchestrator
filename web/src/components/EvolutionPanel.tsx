import { useState, useEffect, useMemo } from 'react'
import { api, EvolutionTask, EvolutionAttempt, EvolutionNote, EvolutionSkill } from '../api'
import { TrendingUp, Trophy, BookOpen, Wrench, Search, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'

// ── Score Chart (pure CSS, no Chart.js dependency) ─────────────────────

function ScoreChart({ attempts }: { attempts: EvolutionAttempt[] }) {
  const scored = attempts.filter(a => a.score !== null).slice(-30)  // last 30
  if (scored.length === 0) return <p className="text-gray-500 text-sm">No scored attempts yet.</p>

  const maxScore = Math.max(...scored.map(a => a.score!))
  const minScore = Math.min(...scored.map(a => a.score!))
  const range = maxScore - minScore || 1

  return (
    <div className="flex items-end gap-1 h-32">
      {scored.map((a, i) => {
        const pct = ((a.score! - minScore) / range) * 100
        const height = Math.max(pct, 5)
        const color = a.status === 'improved' ? 'bg-emerald-500' :
                      a.status === 'regressed' ? 'bg-red-500' : 'bg-blue-500'
        return (
          <div key={a.run_id} className="flex-1 flex flex-col items-center justify-end group relative">
            <div
              className={`w-full rounded-t ${color} transition-all min-w-[4px]`}
              style={{ height: `${height}%` }}
            />
            <div className="absolute bottom-full mb-2 hidden group-hover:block bg-gray-800 text-xs text-white px-2 py-1 rounded shadow-lg whitespace-nowrap z-10">
              <div>{a.agent_id} — {a.score?.toFixed(3)}</div>
              <div className="text-gray-400">{a.title || a.status}</div>
              {a.score_detail && (
                <div className="mt-1 border-t border-gray-700 pt-1">
                  {Object.entries(a.score_detail).map(([k, v]) => (
                    <div key={k}>{k}: {v.toFixed(3)}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Multi-dim Score Radar (CSS-based) ──────────────────────────────────

function ScoreDetailBars({ detail }: { detail: Record<string, number> }) {
  const entries = Object.entries(detail)
  if (entries.length === 0) return null
  const maxVal = Math.max(...entries.map(([, v]) => v), 1)

  return (
    <div className="space-y-1">
      {entries.map(([name, val]) => (
        <div key={name} className="flex items-center gap-2 text-xs">
          <span className="w-20 text-gray-400 truncate text-right">{name}</span>
          <div className="flex-1 h-2 bg-gray-800 rounded overflow-hidden">
            <div
              className="h-full bg-emerald-500 rounded"
              style={{ width: `${(val / maxVal) * 100}%` }}
            />
          </div>
          <span className="w-10 text-gray-400 text-right">{val.toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

// ── Leaderboard Table ──────────────────────────────────────────────────

function Leaderboard({ attempts }: { attempts: EvolutionAttempt[] }) {
  if (attempts.length === 0) return <p className="text-gray-500 text-sm">No attempts yet.</p>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-400 border-b border-gray-800">
            <th className="py-2 pr-3">#</th>
            <th className="py-2 pr-3">Score</th>
            <th className="py-2 pr-3">Agent</th>
            <th className="py-2 pr-3">Title</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2">Time</th>
          </tr>
        </thead>
        <tbody>
          {attempts.map((a, i) => (
            <tr key={a.run_id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
              <td className="py-2 pr-3 text-gray-500">{i + 1}</td>
              <td className="py-2 pr-3 font-mono text-emerald-400">{a.score?.toFixed(4) ?? '—'}</td>
              <td className="py-2 pr-3 text-white">{a.agent_id}</td>
              <td className="py-2 pr-3 text-gray-300 max-w-[200px] truncate">{a.title || '—'}</td>
              <td className="py-2 pr-3">
                <StatusPill status={a.status} />
              </td>
              <td className="py-2 text-gray-500 text-xs">{formatTime(a.timestamp)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    improved: 'bg-emerald-900/50 text-emerald-400 border-emerald-800',
    baseline: 'bg-blue-900/50 text-blue-400 border-blue-800',
    regressed: 'bg-red-900/50 text-red-400 border-red-800',
    crashed: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${colors[status] || 'bg-gray-800 text-gray-400 border-gray-700'}`}>
      {status}
    </span>
  )
}

function formatTime(ts: string) {
  try {
    const d = new Date(ts)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch { return ts?.slice(0, 16) || '—' }
}

// ── Knowledge Browser ──────────────────────────────────────────────────

function KnowledgeBrowser({ notes, skills }: { notes: EvolutionNote[]; skills: EvolutionSkill[] }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
          <BookOpen size={14} /> Notes ({notes.length})
        </h4>
        {notes.length === 0 && <p className="text-gray-600 text-sm">No notes shared yet.</p>}
        {notes.map(n => (
          <div key={n.filename} className="mb-2">
            <button
              onClick={() => setExpanded(expanded === n.filename ? null : n.filename)}
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800/50 hover:bg-gray-800 text-sm"
            >
              {expanded === n.filename ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span className="text-white">{n.meta.title || n.filename}</span>
              {n.meta.tags && (
                <span className="ml-auto text-xs text-gray-500">{n.meta.tags}</span>
              )}
            </button>
            {expanded === n.filename && (
              <div className="ml-6 mt-1 p-3 bg-gray-900 rounded text-sm text-gray-300 whitespace-pre-wrap">
                {n.content}
              </div>
            )}
          </div>
        ))}
      </div>
      <div>
        <h4 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
          <Wrench size={14} /> Skills ({skills.length})
        </h4>
        {skills.length === 0 && <p className="text-gray-600 text-sm">No skills shared yet.</p>}
        {skills.map(s => (
          <div key={s.name} className="mb-2">
            <button
              onClick={() => setExpanded(expanded === `skill:${s.name}` ? null : `skill:${s.name}`)}
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800/50 hover:bg-gray-800 text-sm"
            >
              {expanded === `skill:${s.name}` ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <span className="text-white">{s.name}</span>
              {s.meta.tags && (
                <span className="ml-auto text-xs text-gray-500">{s.meta.tags}</span>
              )}
            </button>
            {expanded === `skill:${s.name}` && (
              <div className="ml-6 mt-1 p-3 bg-gray-900 rounded text-sm text-gray-300 whitespace-pre-wrap">
                {s.content}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main Panel ─────────────────────────────────────────────────────────

export function EvolutionPanel() {
  const [tasks, setTasks] = useState<EvolutionTask[]>([])
  const [selectedTask, setSelectedTask] = useState<string | null>(null)
  const [leaderboard, setLeaderboard] = useState<EvolutionAttempt[]>([])
  const [attempts, setAttempts] = useState<EvolutionAttempt[]>([])
  const [notes, setNotes] = useState<EvolutionNote[]>([])
  const [skills, setSkills] = useState<EvolutionSkill[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])

  const refresh = async () => {
    setLoading(true)
    try {
      const [t, n, s] = await Promise.all([
        api.listTasks(),
        api.listNotes(),
        api.listSkills(),
      ])
      setTasks(t)
      setNotes(n)
      setSkills(s)
      if (t.length > 0 && !selectedTask) {
        setSelectedTask(t[0].task_id)
      }
    } catch (e) {
      console.error('Failed to load evolution data:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])

  useEffect(() => {
    if (!selectedTask) return
    Promise.all([
      api.getLeaderboard(selectedTask),
      api.getAttempts(selectedTask),
    ]).then(([lb, att]) => {
      setLeaderboard(lb)
      setAttempts(att)
    }).catch(console.error)
  }, [selectedTask])

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      const r = await api.searchKnowledge(searchQuery)
      setSearchResults(r)
    } catch (e) {
      console.error('Search failed:', e)
    }
  }

  // Best attempt with score_detail for the multi-dim display
  const bestAttempt = useMemo(() => {
    return leaderboard.find(a => a.score_detail && Object.keys(a.score_detail).length > 0)
  }, [leaderboard])

  if (loading) {
    return <div className="text-gray-500 text-sm py-12 text-center">Loading evolution data...</div>
  }

  return (
    <div className="space-y-6">
      {/* Task Selector + Refresh */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <TrendingUp size={18} className="text-emerald-400" />
          <h2 className="text-lg font-bold text-white">Evolution</h2>
        </div>
        <select
          value={selectedTask || ''}
          onChange={e => setSelectedTask(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white"
        >
          {tasks.length === 0 && <option value="">No tasks</option>}
          {tasks.map(t => (
            <option key={t.task_id} value={t.task_id}>
              {t.name || t.task_id} ({t.attempt_count} attempts, best: {t.best_score?.toFixed(3) ?? '—'})
            </option>
          ))}
        </select>
        <button
          onClick={refresh}
          className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-white transition"
          title="Refresh"
        >
          <RefreshCw size={16} />
        </button>
        <div className="ml-auto text-xs text-gray-500">
          {tasks.length} task{tasks.length !== 1 ? 's' : ''} · {notes.length} note{notes.length !== 1 ? 's' : ''} · {skills.length} skill{skills.length !== 1 ? 's' : ''}
        </div>
      </div>

      {/* Score Chart + Multi-dim */}
      {selectedTask && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
            <h3 className="text-sm font-medium text-gray-400 mb-3">Score History</h3>
            <ScoreChart attempts={attempts} />
          </div>
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
            <h3 className="text-sm font-medium text-gray-400 mb-3">Score Dimensions</h3>
            {bestAttempt?.score_detail ? (
              <ScoreDetailBars detail={bestAttempt.score_detail} />
            ) : (
              <p className="text-gray-600 text-sm">No multi-dim scores yet.</p>
            )}
          </div>
        </div>
      )}

      {/* Leaderboard */}
      {selectedTask && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <h3 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
            <Trophy size={14} className="text-yellow-400" /> Leaderboard
          </h3>
          <Leaderboard attempts={leaderboard} />
        </div>
      )}

      {/* Knowledge Search */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3 flex items-center gap-2">
          <Search size={14} /> Knowledge Search
        </h3>
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="Search notes & skills..."
            className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white placeholder-gray-500"
          />
          <button
            onClick={handleSearch}
            className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm transition"
          >
            Search
          </button>
        </div>
        {searchResults.length > 0 && (
          <div className="space-y-2">
            {searchResults.map((r, i) => (
              <div key={i} className="px-3 py-2 bg-gray-800/50 rounded text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">{r.type}</span>
                  <span className="text-white">{r.name}</span>
                  {r.tags && <span className="text-gray-500 text-xs ml-auto">{r.tags}</span>}
                </div>
                <p className="text-gray-400 text-xs mt-1 line-clamp-2">{r.snippet}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Knowledge Browser */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Knowledge Base</h3>
        <KnowledgeBrowser notes={notes} skills={skills} />
      </div>
    </div>
  )
}
