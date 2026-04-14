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
 *   CAO_HEARTBEAT_ENABLED — "1" to auto-inject heartbeat prompts (default: "0")
 */

import type { Plugin } from "@opencode-ai/plugin"

export default (async ({ client }) => {
  const enabled = process.env.CAO_BRIDGE_ENABLED ?? "1"
  if (enabled === "0" || enabled === "false") return {}

  const HUB = (process.env.CAO_HUB_URL || "http://127.0.0.1:9889").replace(/\/$/, "")
  const PROFILE = process.env.CAO_AGENT_PROFILE || "remote-opencode"
  const POLL_MS = parseInt(process.env.CAO_POLL_INTERVAL || "5000", 10)
  const DEBUG = process.env.CAO_DEBUG === "1"
  const HEARTBEAT = process.env.CAO_HEARTBEAT_ENABLED === "1"

  let terminalId: string | null = process.env.CAO_TERMINAL_ID || null
  let awaitingResult = false
  let lastOutput = ""
  let currentTaskId: string | null = null
  let pendingHeartbeats: Array<{ name: string; prompt: string }> = []

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

  async function getGrader(taskId: string): Promise<string | null> {
    try {
      const data = await hub("/evolution/" + taskId + "/grader")
      return data.grader_code || null
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

  async function pollAndInject() {
    if (!terminalId || awaitingResult) return
    try {
      dbg("polling")
      const data = await hub("/remotes/" + terminalId + "/poll")
      if (data.has_input) {
        awaitingResult = true
        await report("processing")
        const task = String(data.input || "")
        // Extract task_id from metadata if available
        currentTaskId = data.task_id || null
        dbg("injecting: " + task.substring(0, 80))
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

  // Register or use pre-assigned terminal ID
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

  // Start periodic polling immediately (no event dependency)
  setInterval(pollAndInject, POLL_MS)
  dbg("timer started, interval=" + POLL_MS)

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
        await report("completed", lastOutput)

        // Auto-report score if we have a task context and extract heartbeats
        if (currentTaskId) {
          try {
            const resp = await reportScore(currentTaskId, 0, "auto", lastOutput.substring(0, 500))
            if (HEARTBEAT && resp.heartbeat_prompts?.length) {
              pendingHeartbeats.push(...resp.heartbeat_prompts)
              dbg("heartbeat queued: " + resp.heartbeat_prompts.map((h: any) => h.name).join(","))
            }
          } catch (e) {
            dbg("score report failed: " + e)
          }
        }

        awaitingResult = false
        lastOutput = ""
        currentTaskId = null

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
