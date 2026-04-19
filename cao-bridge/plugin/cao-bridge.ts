/**
 * CAO Bridge — OpenCode Plugin (event-driven variant).
 *
 * Automatically registers with CAO Hub, polls for tasks, injects them via
 * the TUI API (appendPrompt + submitPrompt), and reports results back.
 *
 * Install:
 *   Copy to .opencode/plugins/cao-bridge.ts (project) or
 *   ~/.config/opencode/plugins/cao-bridge.ts (global)
 *
 * Environment:
 *   CAO_BRIDGE_ENABLED   — "0" or "false" to disable (default: "1")
 *   CAO_HUB_URL          — Hub URL (default: http://127.0.0.1:9889)
 *   CAO_AGENT_PROFILE    — Profile name (default: remote-opencode)
 *   CAO_TERMINAL_ID      — Pre-assigned terminal ID (skip auto-register)
 *   CAO_POLL_INTERVAL    — Polling interval in ms (default: 5000)
 *   CAO_DEBUG            — "1" to enable file-based debug logging
 *   CAO_HEARTBEAT_ENABLED — "0" to disable heartbeat injection (default: "1")
 *   CAO_FEEDBACK_ENABLED  — "1" to auto-fetch human feedback on idle (default: "0")
 */

import type { Plugin } from "@opencode-ai/plugin"

export default (async ({ client }) => {
  const enabled = process.env.CAO_BRIDGE_ENABLED ?? "1"
  if (enabled === "0" || enabled === "false") return {}

  const HUB = (process.env.CAO_HUB_URL || "http://127.0.0.1:9889").replace(/\/$/, "")
  const PROFILE = process.env.CAO_AGENT_PROFILE || "remote-opencode"
  const POLL_MS = parseInt(process.env.CAO_POLL_INTERVAL || "5000", 10)
  const DEBUG = process.env.CAO_DEBUG === "1"
  const HEARTBEAT = (process.env.CAO_HEARTBEAT_ENABLED ?? "1") !== "0"
  const FEEDBACK = process.env.CAO_FEEDBACK_ENABLED === "1"

  let terminalId: string | null = process.env.CAO_TERMINAL_ID || null
  let awaitingResult = false
  let lastOutput = ""
  let currentTaskId: string | null = null
  let pendingHeartbeats: Array<{ name: string; prompt: string }> = []

  // ── Agent-side git sync ────────────────────────────────────────────
  const GIT_REMOTE = process.env.CAO_GIT_REMOTE || ""
  const SCRIPT_DIR = __dirname + "/.."  // cao-bridge/ directory
  let CLIENT_DIR = process.env.CAO_CLIENT_DIR || ""

  function initSession(): string {
    if (CLIENT_DIR) return CLIENT_DIR  // explicit override
    if (!GIT_REMOTE) return process.env.HOME + "/.cao-evolution-client"  // legacy fallback
    try {
      const { spawnSync } = require("child_process")
      const result = spawnSync("python3", [
        "-c",
        "import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR']); " +
        "from session_manager import create_session; " +
        "print(create_session(os.environ['_CAO_REMOTE'], agent_profile=os.environ['_CAO_PROFILE']))",
      ], {
        timeout: 60000, stdio: "pipe",
        env: { ...process.env, _CAO_SCRIPT_DIR: SCRIPT_DIR, _CAO_REMOTE: GIT_REMOTE, _CAO_PROFILE: PROFILE },
      })
      const out = result.stdout?.toString().trim()
      if (result.status === 0 && out) {
        dbg("session dir: " + out)
        return out
      }
    } catch (e: any) {
      dbg("session init failed: " + (e.message || e))
    }
    return process.env.HOME + "/.cao-evolution-client"  // fallback
  }

  CLIENT_DIR = initSession()

  function pySessionCmd(code: string, extraEnv: Record<string, string> = {}): boolean {
    const { spawnSync } = require("child_process")
    const r = spawnSync("python3", ["-c", code], {
      timeout: 10000, stdio: "pipe",
      env: { ...process.env, _CAO_SCRIPT_DIR: SCRIPT_DIR, _CAO_DIR: CLIENT_DIR, ...extraEnv },
    })
    return r.status === 0
  }

  function gitSync(): boolean {
    const { execSync } = require("child_process")
    if (!GIT_REMOTE) {
      dbg("git sync skipped: CAO_GIT_REMOTE not set")
      return false
    }
    try {
      const { existsSync } = require("fs")
      if (existsSync(CLIENT_DIR + "/.git")) {
        const branch = (() => {
          try {
            const b = execSync("git rev-parse --abbrev-ref HEAD", {
              cwd: CLIENT_DIR, timeout: 5000, stdio: "pipe",
            }).toString().trim()
            return b && b !== "HEAD" ? b : "main"
          } catch { return "main" }
        })()
        execSync(`git fetch --all && git pull --rebase origin ${branch}`, {
          cwd: CLIENT_DIR, timeout: 30000, stdio: "pipe",
        })
        dbg("git pull ok")
        try {
          pySessionCmd(
            "import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR']); " +
            "from pathlib import Path; from session_manager import touch_session; " +
            "touch_session(Path(os.environ['_CAO_DIR']))"
          )
        } catch {}
      } else {
        const { spawnSync } = require("child_process")
        spawnSync("git", ["clone", "--filter=blob:none", GIT_REMOTE, CLIENT_DIR], {
          timeout: 60000, stdio: "pipe",
        })
        spawnSync("git", ["config", "user.name", "cao-agent"], { cwd: CLIENT_DIR, stdio: "pipe" })
        spawnSync("git", ["config", "user.email", "cao-agent@local"], { cwd: CLIENT_DIR, stdio: "pipe" })
        dbg("git clone ok")
        try {
          pySessionCmd(
            "import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR']); " +
            "from pathlib import Path; from session_manager import touch_session; " +
            "touch_session(Path(os.environ['_CAO_DIR']))"
          )
        } catch {}
      }
      return true
    } catch (e: any) {
      dbg("git sync error: " + (e.message || e))
      return false
    }
  }

  function gitPush(message: string = "agent sync"): boolean {
    const { execSync, spawnSync } = require("child_process")
    const { existsSync } = require("fs")
    if (!GIT_REMOTE || !existsSync(CLIENT_DIR + "/.git")) return false
    try {
      const branch = (() => {
        try {
          const b = execSync("git rev-parse --abbrev-ref HEAD", {
            cwd: CLIENT_DIR, timeout: 5000, stdio: "pipe",
          }).toString().trim()
          return b && b !== "HEAD" ? b : "main"
        } catch { return "main" }
      })()
      // Stage, commit (no-op if clean), pull --rebase, push
      execSync("git add -A", { cwd: CLIENT_DIR, timeout: 10000, stdio: "pipe" })
      try {
        execSync(`git diff --cached --quiet`, { cwd: CLIENT_DIR, stdio: "pipe" })
        dbg("git push: nothing to commit")
        return true
      } catch {
        // diff --cached returns 1 when there are staged changes
      }
      // Use spawnSync to avoid shell injection via message
      const commitResult = spawnSync("git", ["commit", "-m", `[agent] ${message}`], {
        cwd: CLIENT_DIR, timeout: 10000, stdio: "pipe",
      })
      if (commitResult.status !== 0) {
        dbg("git commit failed: " + (commitResult.stderr?.toString() || ""))
        return false
      }
      execSync(`git pull --rebase origin ${branch}`, {
        cwd: CLIENT_DIR, timeout: 30000, stdio: "pipe",
      })
      execSync(`git push origin ${branch}`, {
        cwd: CLIENT_DIR, timeout: 30000, stdio: "pipe",
      })
      dbg("git push ok")
      return true
    } catch (e: any) {
      dbg("git push error: " + (e.message || e))
      return false
    }
  }

  function pullSkillsFromClone() {
    const { existsSync, readdirSync, mkdirSync, cpSync } = require("fs")
    const srcDir = CLIENT_DIR + "/skills"
    const oc1 = (process.env.HOME || "") + "/.config/opencode/skills"
    const tgtDir = existsSync(oc1) ? oc1 : oc1  // default opencode
    if (!existsSync(srcDir)) return
    try {
      mkdirSync(tgtDir, { recursive: true })
      for (const name of readdirSync(srcDir)) {
        const skillMd = srcDir + "/" + name + "/SKILL.md"
        if (existsSync(skillMd)) {
          cpSync(srcDir + "/" + name, tgtDir + "/" + name, { recursive: true })
          dbg("synced skill: " + name)
        }
      }
    } catch (e: any) {
      dbg("skill pull error: " + (e.message || e))
    }
  }

  // Initial skill sync (git clone handled by initSession)
  pullSkillsFromClone()

  function dbg(msg: string) {
    if (!DEBUG) return
    const { appendFileSync } = require("fs")
    appendFileSync("/tmp/cao-bridge-debug.log", new Date().toISOString() + " " + msg + "\n")
  }

  async function hub(path: string, opts?: RequestInit): Promise<any> {
    const r = await fetch(HUB + path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...opts?.headers },
    })
    if (!r.ok) throw new Error("Hub " + path + ": " + r.status)
    return r.json()
  }

  async function report(st: string, output?: string) {
    if (!terminalId) return
    const body: Record<string, string> = { status: st }
    if (output !== undefined) body.output = output
    await hub("/remotes/" + terminalId + "/report", {
      method: "POST",
      body: JSON.stringify(body),
    })
  }

  // ── Evolution helpers ──────────────────────────────────────────────

  async function reportScore(taskId: string, score: number, title = "", feedback = "") {
    return hub("/evolution/" + taskId + "/scores", {
      method: "POST",
      body: JSON.stringify({
        agent_id: terminalId || "plugin",
        score, title, feedback,
      }),
    })
  }

  async function getTaskInfo(taskId: string): Promise<{ grader_skill?: string; task_yaml?: string } | null> {
    try {
      return await hub("/evolution/" + taskId)
    } catch { return null }
  }

  async function shareNote(title: string, content: string, tags: string[] = []) {
    return hub("/evolution/knowledge/notes", {
      method: "POST",
      body: JSON.stringify({
        title, content, tags,
        agent_id: terminalId || "plugin",
      }),
    })
  }

  async function injectHeartbeat() {
    if (!HEARTBEAT || pendingHeartbeats.length === 0 || awaitingResult) return
    const hb = pendingHeartbeats.shift()!
    dbg("heartbeat inject: " + hb.name)
    awaitingResult = true
    await client.tui.appendPrompt({ body: { text: hb.prompt } })
    await client.tui.submitPrompt()
  }

  async function fetchFeedback(taskId: string): Promise<string | null> {
    if (!FEEDBACK || !terminalId) return null
    try {
      const data = await hub(
        "/evolution/" + taskId + "/reports?terminal_id=" + terminalId + "&status=annotated"
      )
      if (!Array.isArray(data) || data.length === 0) return null
      const lines = data.map((r: any) => {
        const tp = (r.human_labels || []).filter((l: any) => l.verdict === "tp").length
        const fp = (r.human_labels || []).filter((l: any) => l.verdict === "fp").length
        return `Report ${r.report_id}: human_score=${r.human_score ?? "?"}, tp=${tp}, fp=${fp}`
      })
      dbg("feedback fetched: " + data.length + " reports")
      return `[Human Feedback — ${data.length} reports annotated]\n` + lines.join("\n") +
        "\nReview the feedback and adjust your scanning strategy accordingly."
    } catch {
      return null
    }
  }

  async function pollAndInject() {
    if (!terminalId || awaitingResult) return
    try {
      dbg("polling")
      const data = await hub("/remotes/" + terminalId + "/poll")
      if (data.has_input) {
        awaitingResult = true
        await report("processing")
        const task = String(data.input || "")
        // Extract task_id from [CAO Task ID: xxx] in the prompt
        const tidMatch = task.match(/\[CAO Task ID:\s*([^\]]+)\]/)
        currentTaskId = data.task_id || (tidMatch ? tidMatch[1].trim() : null)
        dbg("injecting task=" + (currentTaskId || "?") + ": " + task.substring(0, 80))
        if (terminalId) writeCachedTerminalId(terminalId)
        await client.tui.appendPrompt({ body: { text: task } })
        await client.tui.submitPrompt()
      } else {
        // No hub task — try heartbeat injection
        await injectHeartbeat()
      }
    } catch {
      // Silently retry on next interval
    }
  }

  // ── Stable state file at $CAO_CLIENT_BASE_DIR/state/opencode-<profile>.json
  //     Lets OpenCode reattach to its Hub terminal across restarts.
  const STATE_BASE = process.env.CAO_CLIENT_BASE_DIR || (process.env.HOME + "/.cao-evolution-client")
  const STATE_DIR = STATE_BASE + "/state"
  const STATE_FILE = STATE_DIR + "/opencode-" + PROFILE + ".json"

  function readCachedTerminalId(): string {
    try {
      const { existsSync, readFileSync } = require("fs")
      if (!existsSync(STATE_FILE)) return ""
      const data = JSON.parse(readFileSync(STATE_FILE, "utf-8"))
      // Restore in-flight task state from previous session
      if (data.awaiting_task_id && !currentTaskId) {
        currentTaskId = data.awaiting_task_id
        awaitingResult = true
        dbg("restored in-flight task: " + currentTaskId)
      }
      return String(data.terminal_id || "")
    } catch { return "" }
  }

  function writeCachedTerminalId(tid: string) {
    try {
      const { existsSync, mkdirSync, writeFileSync } = require("fs")
      if (!existsSync(STATE_DIR)) mkdirSync(STATE_DIR, { recursive: true })
      writeFileSync(STATE_FILE, JSON.stringify({
        terminal_id: tid,
        session_dir: CLIENT_DIR,
        awaiting_task_id: currentTaskId || "",
      }))
    } catch (e: any) {
      dbg("state write failed: " + (e.message || e))
    }
  }

  // Reattach-first: cold start of OpenCode should try to resume the
  // Hub-side terminal that previous runs created before falling back to
  // register (which would strand any queued tasks under a dead id).
  if (!terminalId) {
    const cached = readCachedTerminalId()
    if (cached) {
      try {
        const r = await fetch(HUB + "/remotes/" + cached + "/reattach", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
        if (r.ok) {
          const data = await r.json() as any
          terminalId = data.terminal_id || cached
          dbg("reattached: " + terminalId)
        } else if (r.status === 404) {
          dbg("reattach 404, cached id " + cached + " is stale")
        } else {
          dbg("reattach http " + r.status)
        }
      } catch (e: any) {
        dbg("reattach failed: " + (e.message || e))
      }
    }
  }

  if (!terminalId) {
    try {
      const data = await hub("/remotes/register", {
        method: "POST",
        body: JSON.stringify({ agent_profile: PROFILE }),
      })
      terminalId = data.terminal_id
      dbg("registered: " + terminalId)
    } catch {
      dbg("register failed")
    }
  }

  if (terminalId) {
    writeCachedTerminalId(terminalId)
  }

  // Start periodic polling immediately (no event dependency)
  setInterval(pollAndInject, POLL_MS)
  dbg("timer started, interval=" + POLL_MS)

  // Deactivate session on process exit
  if (CLIENT_DIR && GIT_REMOTE && !process.env.CAO_CLIENT_DIR) {
    process.on("beforeExit", () => {
      try {
        gitPush("session end")
        pySessionCmd(
          "import sys, os; sys.path.insert(0, os.environ['_CAO_SCRIPT_DIR']); " +
          "from pathlib import Path; from session_manager import deactivate_session; " +
          "deactivate_session(Path(os.environ['_CAO_DIR']))"
        )
        dbg("session deactivated")
      } catch {}
    })
  }

  let pendingGraderTaskId: string | null = null

  return {
    event: async (input: any) => {
      const e = input.event

      // Accumulate assistant output via streaming deltas
      if (e.type === "message.part.delta" && awaitingResult) {
        const delta = e.properties?.delta || ""
        if (delta) lastOutput += String(delta)
      }

      // Session idle → report result, check heartbeat triggers
      if (e.type === "session.idle" && awaitingResult && terminalId) {
        dbg("completed, output len=" + lastOutput.length)

        // ── Grader score extraction ──────────────────────────────────
        // If we just ran a grader skill, extract CAO_SCORE from output
        if (pendingGraderTaskId) {
          const scoreMatch = lastOutput.match(/CAO_SCORE\s*=\s*(\d*\.?\d+)/)
          const score = scoreMatch ? parseFloat(scoreMatch[1]) : 0
          dbg("grader result: score=" + score + " for task=" + pendingGraderTaskId)
          try {
            const resp = await reportScore(
              pendingGraderTaskId, score,
              "grader-skill", lastOutput.substring(0, 500),
            )
            if (HEARTBEAT && resp.heartbeat_prompts?.length) {
              pendingHeartbeats.push(...resp.heartbeat_prompts)
              dbg("heartbeat queued: " + resp.heartbeat_prompts.map((h: any) => h.name).join(","))
            }
            // Fetch human feedback
            const feedbackMsg = await fetchFeedback(pendingGraderTaskId)
            if (feedbackMsg) {
              pendingHeartbeats.unshift({ name: "human-feedback", prompt: feedbackMsg })
            }
          } catch (e) {
            dbg("grader score report failed: " + e)
          }
          pendingGraderTaskId = null
          awaitingResult = false
          lastOutput = ""
          currentTaskId = null
          if (terminalId) writeCachedTerminalId(terminalId)

          gitPush("grader: score submitted")
          if (gitSync()) pullSkillsFromClone()
          if (pendingHeartbeats.length > 0) {
            await injectHeartbeat()
          } else {
            await pollAndInject()
          }
          return
        }

        // ── Normal task completion → trigger grader skill ────────────
        await report("completed", lastOutput)

        if (currentTaskId) {
          try {
            const taskInfo = await getTaskInfo(currentTaskId)
            const graderSkill = taskInfo?.grader_skill || ""

            if (graderSkill) {
              // Inject grader skill prompt — agent will evaluate its own output
              dbg("injecting grader skill: " + graderSkill)
              pendingGraderTaskId = currentTaskId
              const skillPath = (process.env.HOME || "") + "/.config/opencode/skills/" + graderSkill + "/SKILL.md"
              const graderPrompt =
                `You just completed a task. Now grade your own output using the grader skill.\n\n` +
                `## Instructions\n` +
                `Read and follow ${skillPath} to evaluate the output below.\n\n` +
                `## Task ID\n${currentTaskId}\n\n` +
                `## Your Output to Grade\n` +
                `${lastOutput.substring(0, 3000)}\n\n` +
                `## Required Output Format\n` +
                `After evaluation, print exactly one line: CAO_SCORE=<integer 0-100>\n` +
                `Then state Feasibility: FEASIBLE or INFEASIBLE, followed by a brief rationale.`
              awaitingResult = true
              lastOutput = ""
              currentTaskId = null
              await client.tui.appendPrompt({ body: { text: graderPrompt } })
              await client.tui.submitPrompt()
              return
            } else {
              // No grader skill configured — report score=0 as fallback
              dbg("no grader_skill for task " + currentTaskId + ", reporting score=0")
              const resp = await reportScore(currentTaskId, 0, "no-grader", lastOutput.substring(0, 500))
              if (HEARTBEAT && resp.heartbeat_prompts?.length) {
                pendingHeartbeats.push(...resp.heartbeat_prompts)
              }
            }
          } catch (e) {
            dbg("grader trigger failed: " + e)
          }
          // Fetch human feedback
          const feedbackMsg = await fetchFeedback(currentTaskId)
          if (feedbackMsg) {
            pendingHeartbeats.unshift({ name: "human-feedback", prompt: feedbackMsg })
          }
        }

        awaitingResult = false
        lastOutput = ""
        currentTaskId = null
        if (terminalId) writeCachedTerminalId(terminalId)

        // Push local changes (notes, skills) then pull latest
        gitPush("task completed")
        if (gitSync()) pullSkillsFromClone()

        // Try heartbeat injection or re-poll
        if (pendingHeartbeats.length > 0) {
          await injectHeartbeat()
        } else {
          await pollAndInject()
        }
      }
    },
  }
}) satisfies Plugin
