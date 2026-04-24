"""CAO Remote Bridge — shared HTTP client for all bridge variants.

This module talks to the CAO Hub server's /remotes/ endpoints and
synchronises shared knowledge via git (per-session clone under
~/.cao-evolution-client/sessions/<session_id>/).
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


def _candidate_local_skill_dirs() -> list[Path]:
    """Agent-side skill dirs that may hold `cao-*` skills to push upstream.

    CAO_LOCAL_SKILLS_DIR (colon-separated) overrides the default heuristic;
    otherwise probe the known locations for claude-code, opencode, hermes.
    Non-existent paths are silently dropped by import_local_skills.
    """
    override = os.environ.get("CAO_LOCAL_SKILLS_DIR", "")
    if override:
        return [Path(p).expanduser() for p in override.split(":") if p]
    home = Path.home()
    return [
        home / ".claude" / "skills",
        home / ".config" / "opencode" / "skills",
        home / ".hermes" / "skills",
    ]


class CaoBridge:
    """HTTP client that registers with CAO Hub and exchanges input/output.

    Also manages a local git clone (per-session directory under
    ``~/.cao-evolution-client/sessions/<session_id>/``) for bi-directional
    knowledge sync with the Hub's evolution repo.
    """

    def __init__(self, hub_url: str = "http://127.0.0.1:9889",
                 agent_profile: str = "remote-agent",
                 git_remote: str = ""):
        self.hub_url = hub_url.rstrip("/")
        self.agent_profile = agent_profile
        self.terminal_id: Optional[str] = None
        self._git_remote = git_remote  # explicit override; env fallback in git_sync
        self._session_dir: Optional[Path] = None

    _TIMEOUT = 30  # seconds

    @property
    def _local_only(self) -> bool:
        """True when CAO_LOCAL_ONLY=1 — all Hub HTTP calls become no-ops."""
        return os.environ.get("CAO_LOCAL_ONLY", "0") == "1"

    def _local_search(self, query: str, top_k: int = 10) -> list:
        """Keyword search over local notes directory (local-only fallback)."""
        from git_sync import notes_dir
        ndir = notes_dir()
        if not ndir.exists():
            return []
        results = []
        terms = query.lower().split()
        for f in ndir.glob("*.md"):
            content = f.read_text(errors="ignore")
            lower = content.lower()
            score = sum(lower.count(t) for t in terms)
            if score > 0:
                results.append({"title": f.stem, "content": content, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    # ── Session lifecycle ────────────────────────────────────────────────

    def init_session(self, git_remote: str = "") -> Path:
        """Create a new per-instance session directory with git clone.

        Sets up session isolation so this bridge instance operates on its
        own directory under ``~/.cao-evolution-client/sessions/<session_id>/``.
        Must be called before any git operations.

        Returns the session directory path.
        """
        from session_manager import create_session
        from git_sync import set_session_dir

        url = git_remote or self._git_remote
        if not url:
            url = os.environ.get("CAO_GIT_REMOTE", "")
        if not url and self._local_only:
            from git_sync import ensure_local_shared_repo
            url = ensure_local_shared_repo()
        if not url:
            raise RuntimeError(
                "No git remote configured. Set CAO_GIT_REMOTE env var "
                "or pass git_remote to init_session()."
            )

        self._session_dir = create_session(
            git_remote=url,
            agent_profile=self.agent_profile,
        )
        set_session_dir(self._session_dir)
        return self._session_dir

    def close_session(self) -> None:
        """Push pending changes and mark session as inactive.

        Called on normal agent exit. The session directory is kept on disk
        (marked inactive) for later cleanup by ``cao-session-mgr cleanup``.
        """
        if not self._session_dir:
            return
        from session_manager import deactivate_session, touch_session
        from git_sync import push

        try:
            push(self._session_dir)
        except Exception:
            logger.warning("Failed to push on session close", exc_info=True)
        deactivate_session(self._session_dir)

    @property
    def session_dir(self) -> Optional[Path]:
        """The current session directory, or None if not initialized."""
        return self._session_dir

    def register(self) -> str:
        """Register with Hub, returns terminal_id."""
        if self._local_only:
            self.terminal_id = f"local-{self.agent_profile}"
            logger.info("Local-only mode: terminal_id=%s", self.terminal_id)
            return self.terminal_id
        resp = requests.post(f"{self.hub_url}/remotes/register",
                             json={"agent_profile": self.agent_profile},
                             timeout=self._TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        self.terminal_id = data["terminal_id"]
        logger.info(f"Registered with Hub: terminal_id={self.terminal_id}")
        if self._session_dir:
            try:
                from session_manager import set_terminal_id
                set_terminal_id(self._session_dir, self.terminal_id)
            except Exception:
                pass
        return self.terminal_id

    def reattach(self, terminal_id: str) -> Optional[dict]:
        """Try to reattach an existing Hub-side terminal by id.

        Returns the Hub's reattach payload on success, ``None`` when the
        Hub returns 404 (the id is stale).  Any other error surfaces via
        ``requests.HTTPError`` so callers can decide whether to retry or
        register fresh.
        """
        if not terminal_id:
            return None
        if self._local_only:
            return None
        url = f"{self.hub_url}/remotes/{terminal_id}/reattach"
        resp = requests.post(url, timeout=self._TIMEOUT)
        if resp.status_code == 404:
            logger.info(f"Reattach rejected: terminal {terminal_id} not found on Hub")
            return None
        resp.raise_for_status()
        data = resp.json()
        self.terminal_id = data.get("terminal_id", terminal_id)
        logger.info(
            f"Reattached to Hub: terminal_id={self.terminal_id} "
            f"has_pending_input={data.get('has_pending_input')}"
        )
        return data

    def register_or_reattach(self, cached_terminal_id: str = "") -> str:
        """Reattach using a cached id when possible, else register fresh.

        The caller (session-start hook or MCP bootstrap) is responsible
        for reading/writing the cache; this helper just picks the right
        Hub call.  After either path the bridge has ``self.terminal_id``
        set and the session metadata (if any) is updated.
        """
        cached = cached_terminal_id.strip()
        if cached:
            try:
                data = self.reattach(cached)
                if data:
                    if self._session_dir:
                        try:
                            from session_manager import set_terminal_id
                            set_terminal_id(self._session_dir, self.terminal_id or cached)
                        except Exception:
                            pass
                    return self.terminal_id or cached
            except requests.RequestException as e:
                # Hub reachable issues: log and fall back to register so
                # the agent is not stranded.
                logger.warning(f"Reattach failed ({e}), falling back to register")

        return self.register()

    def poll(self) -> Optional[str]:
        """Poll Hub for pending input. Returns message or None."""
        if self._local_only:
            return None
        if not self.terminal_id:
            raise RuntimeError("Not registered")
        resp = requests.get(f"{self.hub_url}/remotes/{self.terminal_id}/poll",
                            timeout=self._TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("has_input"):
            return data["input"]
        return None

    def report(self, status: Optional[str] = None, output: Optional[str] = None,
               append: bool = False) -> None:
        """Report status and/or output to Hub."""
        if self._local_only:
            return
        if not self.terminal_id:
            raise RuntimeError("Not registered")
        body = {}
        if status:
            body["status"] = status
        if output is not None:
            body["output"] = output
            body["append"] = append
        requests.post(f"{self.hub_url}/remotes/{self.terminal_id}/report",
                      json=body, timeout=self._TIMEOUT).raise_for_status()

    def poll_loop(self, interval: float = 2.0):
        """Generator that yields input messages as they arrive."""
        while True:
            try:
                msg = self.poll()
            except requests.RequestException as e:
                logger.warning(f"Poll error (will retry): {e}")
                time.sleep(interval)
                continue
            if msg is not None:
                yield msg
            else:
                time.sleep(interval)

    # ── Evolution endpoints ──────────────────────────────────────────

    def report_score(self, task_id: str, score: Optional[float],
                     title: str = "", feedback: str = "",
                     agent_profile: str = "", batch: str = "",
                     evolution_signals: Optional[dict] = None) -> dict:
        """Report an evaluation score to the Hub."""
        if self._local_only:
            return {}
        agent_id = self.terminal_id or "anonymous"
        body: dict = {"agent_id": agent_id, "score": score,
                       "title": title, "feedback": feedback}
        if agent_profile:
            body["agent_profile"] = agent_profile
        if batch:
            body["batch"] = batch
        if evolution_signals:
            body["evolution_signals"] = evolution_signals
        resp = requests.post(
            f"{self.hub_url}/evolution/{task_id}/scores",
            json=body,
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def get_leaderboard(self, task_id: str, top_n: int = 10) -> dict:
        """Get the leaderboard for a task."""
        if self._local_only:
            return {"scores": []}
        resp = requests.get(
            f"{self.hub_url}/evolution/{task_id}/leaderboard",
            params={"top_n": top_n}, timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def search_knowledge(self, query: str, tags: str = "",
                         top_k: int = 10) -> list:
        """Search shared knowledge (notes + skills)."""
        if self._local_only:
            return self._local_search(query, top_k)
        resp = requests.get(
            f"{self.hub_url}/evolution/knowledge/search",
            params={"query": query, "tags": tags, "top_k": top_k},
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def recall_knowledge(self, query: str, tags: str = "",
                         top_k: int = 10,
                         include_content: bool = False) -> list:
        """BM25-ranked knowledge recall (more precise than search)."""
        if self._local_only:
            return self._local_search(query, top_k)
        resp = requests.get(
            f"{self.hub_url}/evolution/knowledge/recall",
            params={
                "query": query, "tags": tags,
                "top_k": top_k, "include_content": include_content,
            },
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_document(self, doc_id: str) -> dict:
        """Fetch a specific document by ID (selective sync)."""
        if self._local_only:
            from git_sync import notes_dir
            p = notes_dir() / f"{doc_id}.md"
            if p.exists():
                return {"title": doc_id, "content": p.read_text(errors="ignore")}
            return {}
        resp = requests.get(
            f"{self.hub_url}/evolution/knowledge/document/{doc_id}",
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_index(self) -> str:
        """Fetch L1 knowledge index from Hub.

        Returns the index content, or empty string if no index is available.
        SDK-based agents use this to inject knowledge context at session start.
        """
        if self._local_only:
            from git_sync import local_index_path
            p = local_index_path()
            return p.read_text(errors="ignore") if p.exists() else ""
        resp = requests.get(
            f"{self.hub_url}/evolution/index",
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.text
        if "No index available yet" in text:
            return ""
        return text

    # ── Task management (remote agent can create/update tasks) ────────

    def create_task(self, task_id: str, name: str = "", description: str = "",
                    grader_skill: str = "",
                    tips: list | None = None, group: str = "",
                    group_tags: list | None = None, force: bool = False) -> dict:
        """Create or update a task on the Hub (agent-side registration)."""
        if self._local_only:
            return {"status": "local_only", "task_id": task_id}
        body: dict = {
            "task_id": task_id, "name": name or task_id,
            "description": description, "grader_skill": grader_skill,
            "tips": tips or [],
            "created_by": self.terminal_id or "remote-agent",
            "force": force,
        }
        if group:
            body["group"] = group
        if group_tags:
            body["group_tags"] = group_tags
        resp = requests.post(
            f"{self.hub_url}/evolution/tasks",
            json=body,
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def get_task(self, task_id: str) -> dict | None:
        """Fetch task details from Hub. Returns None if not found."""
        if self._local_only:
            return None
        resp = requests.get(f"{self.hub_url}/evolution/{task_id}",
                            timeout=self._TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def list_tasks(self) -> list:
        """List all tasks on the Hub."""
        if self._local_only:
            return []
        resp = requests.get(f"{self.hub_url}/evolution/tasks",
                            timeout=self._TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    # ── Reports / human feedback ───────────────────────────────────────

    def submit_report(self, task_id: str, findings: list[dict],
                      auto_score: float | None = None) -> dict:
        """Submit a vulnerability report; registers the report_id locally."""
        if self._local_only:
            return {"status": "local_only"}
        from report_registry import add_report

        agent_id = self.terminal_id or "anonymous"
        resp = requests.post(
            f"{self.hub_url}/evolution/{task_id}/reports",
            json={
                "agent_id": agent_id,
                "terminal_id": agent_id,
                "findings": findings,
                "auto_score": auto_score,
            },
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        rid = data.get("report_id", "")
        if rid:
            add_report(rid, task_id=task_id, source="cao")
        return data

    def fetch_feedbacks(self, task_id: str = "",
                        template_path: str = "",
                        output_dir: str = "") -> dict:
        """Poll the Hub for annotations on pending reports; land results to disk."""
        if self._local_only:
            return {"feedback_md_path": "", "fetched": [],
                    "pending": [], "result_files": []}
        import json as _json
        from report_registry import list_pending, mark_annotated, reports_dir

        pending = list_pending(task_id=task_id or None, source="cao")
        if not pending:
            return {"feedback_md_path": "", "fetched": [],
                    "pending": [], "result_files": []}

        rdir = reports_dir()
        fetched: list[dict] = []
        still_pending: list[str] = []
        result_files: list[str] = []

        for entry in pending:
            rid = entry["report_id"]
            tid = entry["task_id"]
            try:
                r = requests.get(
                    f"{self.hub_url}/evolution/{tid}/reports/{rid}/result",
                    timeout=self._TIMEOUT,
                )
            except requests.RequestException as exc:
                logger.warning("fetch %s failed: %s", rid, exc)
                still_pending.append(rid)
                continue

            if r.status_code == 404:
                # Not yet annotated (or does not exist server-side).
                still_pending.append(rid)
                continue
            if not r.ok:
                logger.warning("fetch %s returned %s", rid, r.status_code)
                still_pending.append(rid)
                continue

            payload = r.json()
            out = rdir / f"{rid}.result"
            out.write_text(_json.dumps(payload, indent=2, ensure_ascii=False))
            mark_annotated(rid, str(out))
            result_files.append(str(out))
            fetched.append({
                "report_id": rid,
                "task_id": tid,
                "result_path": str(out),
                "payload": payload,
            })

        if not fetched:
            return {"feedback_md_path": "", "fetched": [],
                    "pending": still_pending, "result_files": []}

        md_path = self._render_feedback_md(
            fetched=fetched,
            template_path=template_path,
            output_dir=output_dir,
        )
        return {
            "feedback_md_path": str(md_path) if md_path else "",
            "fetched": [f["report_id"] for f in fetched],
            "pending": still_pending,
            "result_files": result_files,
        }

    def _render_feedback_md(self, fetched: list[dict],
                            template_path: str,
                            output_dir: str) -> Path | None:
        """Render the feedback markdown from a template.

        Search order for template:
          1. explicit ``template_path`` arg
          2. ``$CAO_FEEDBACK_TEMPLATE``
          3. ``~/.config/opencode/skills/feedback-fetch/templates/evolve_from_feedback.md``
          4. ``<repo>/evo-skills/feedback-fetch/templates/evolve_from_feedback.md``
             (dev layout — sibling of cao-bridge/)
        """
        import json as _json
        import os as _os

        candidates: list[Path] = []
        if template_path:
            candidates.append(Path(template_path).expanduser())
        env_tpl = _os.environ.get("CAO_FEEDBACK_TEMPLATE", "")
        if env_tpl:
            candidates.append(Path(env_tpl).expanduser())
        candidates.append(
            Path.home() / ".config" / "opencode" / "skills"
            / "feedback-fetch" / "templates" / "evolve_from_feedback.md"
        )
        candidates.append(
            Path(__file__).resolve().parent.parent
            / "evo-skills" / "feedback-fetch"
            / "templates" / "evolve_from_feedback.md"
        )

        tpl_file = next((p for p in candidates if p.is_file()), None)
        if tpl_file is None:
            logger.warning("no feedback template found, tried: %s", candidates)
            return None

        template = tpl_file.read_text(encoding="utf-8")

        task_ids = sorted({f["task_id"] for f in fetched})
        report_ids = [f["report_id"] for f in fetched]
        entries_md = "\n".join(
            f"- **{f['report_id']}** (task `{f['task_id']}`) → `{f['result_path']}`"
            for f in fetched
        )
        payloads_json = _json.dumps(
            [{"report_id": f["report_id"], "task_id": f["task_id"],
              "result": f["payload"]} for f in fetched],
            indent=2, ensure_ascii=False,
        )
        rendered = (
            template
            .replace("{task_ids}", ", ".join(task_ids))
            .replace("{report_ids}", ", ".join(report_ids))
            .replace("{fetched_count}", str(len(fetched)))
            .replace("{entries_markdown}", entries_md)
            .replace("{payloads_json}", payloads_json)
        )

        out_dir = Path(output_dir).expanduser() if output_dir else Path.cwd()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "evolve_from_feedback.md"
        out_path.write_text(rendered, encoding="utf-8")
        logger.info("rendered feedback md → %s", out_path)
        return out_path

    # ── Git sync (agent-side clone at ~/.cao-evolution-client/) ────────

    def sync_repo(self, remote_url: str = "") -> Path:
        """Clone or pull the Hub's evolution repo.

        If a session is active, operates on the session directory.
        Otherwise falls back to legacy init_client_repo behavior.
        """
        if self._session_dir:
            from git_sync import pull
            pull(self._session_dir)
            return self._session_dir
        from git_sync import init_client_repo
        url = remote_url or self._git_remote
        return init_client_repo(url or None)

    def pull_repo(self) -> bool:
        """Pull latest changes from the remote evolution repo."""
        from git_sync import pull
        return pull()

    def push_repo(self, message: str = "agent sync") -> bool:
        """Push any local agent-side changes back to the remote.

        Before pushing: auto-adopt non-cao skills, then mirror `cao-*`
        skills from the agent's local skills dir(s) into the clone.
        """
        from git_sync import push, import_local_skills
        for d in _candidate_local_skill_dirs():
            try:
                self._auto_adopt_skills(d)
            except Exception:
                logger.debug("auto_adopt_skills failed for %s", d, exc_info=True)
            try:
                import_local_skills(d)
            except Exception:
                logger.debug("import_local_skills failed for %s", d, exc_info=True)
        return push(message=message)

    def client_skills_dir(self) -> Path:
        """Return the skills directory inside the agent-side clone."""
        from git_sync import skills_dir
        return skills_dir()

    def client_notes_dir(self) -> Path:
        """Return the notes directory inside the agent-side clone."""
        from git_sync import notes_dir
        return notes_dir()

    def client_tasks_dir(self) -> Path:
        """Return the tasks directory inside the agent-side clone."""
        from git_sync import tasks_dir
        return tasks_dir()

    def pull_skills_to_local(self, target_dir: Path) -> list[str]:
        """Copy `cao-*` skills from the git clone into the agent's local
        skills dir. Non-prefixed clone entries are skipped; non-prefixed
        local skills are never touched.

        Returns list of skill names synced.
        """
        import shutil
        from git_sync import is_shared_skill
        src = self.client_skills_dir()
        if not src.exists():
            return []
        target_dir.mkdir(parents=True, exist_ok=True)
        synced: list[str] = []
        for child in src.iterdir():
            if not (child.is_dir() and is_shared_skill(child.name)):
                continue
            if (child / "SKILL.md").exists():
                dest = target_dir / child.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(child, dest)
                synced.append(child.name)
                logger.debug("Synced skill %s → %s", child.name, dest)
        if synced:
            logger.info("Synced %d cao-* skills to %s", len(synced), target_dir)
        return synced

    # ── Skill adoption ──────────────────────────────────────────────

    def _auto_adopt_skills(self, local_dir: Path) -> list[str]:
        """Auto-adopt non-cao skills into the shared pipeline.

        For each non-prefixed skill in *local_dir*, check whether a
        ``cao-{name}`` counterpart already exists locally or in the
        shared git clone.  If not, copy it with the ``cao-`` prefix so
        that the next ``import_local_skills`` picks it up.

        Returns list of newly adopted skill names (with prefix).
        """
        import shutil
        from git_sync import SHARED_SKILL_PREFIX, is_shared_skill, skills_dir

        if not local_dir.exists():
            return []

        clone_skills = skills_dir()
        adopted: list[str] = []
        for child in sorted(local_dir.iterdir()):
            if not child.is_dir():
                continue
            if is_shared_skill(child.name):
                continue
            if not (child / "SKILL.md").exists():
                continue

            target_name = SHARED_SKILL_PREFIX + child.name
            # Dedup: already adopted locally?
            if (local_dir / target_name).exists():
                continue
            # Dedup: already in shared pool (git clone)?
            if clone_skills.exists() and (clone_skills / target_name).exists():
                continue

            dest = local_dir / target_name
            shutil.copytree(child, dest)
            adopted.append(target_name)
            logger.info("Auto-adopted skill: %s → %s", child.name, target_name)

        return adopted

    def adopt_skill(self, skill_name: str, new_name: str = "") -> dict:
        """Explicitly adopt a single non-cao skill into the shared pipeline.

        Searches candidate local skill dirs for *skill_name*, copies it
        as ``cao-{new_name or skill_name}``.  Returns a dict with
        adoption details or raises ValueError on failure.
        """
        import shutil
        from git_sync import SHARED_SKILL_PREFIX, is_shared_skill, skills_dir

        if is_shared_skill(skill_name):
            raise ValueError(
                f"'{skill_name}' already has the '{SHARED_SKILL_PREFIX}' prefix"
            )

        target_name = SHARED_SKILL_PREFIX + (new_name or skill_name)

        # Find source
        for d in _candidate_local_skill_dirs():
            src = d / skill_name
            if src.is_dir() and (src / "SKILL.md").exists():
                dest = d / target_name
                # Dedup: local
                if dest.exists():
                    raise ValueError(
                        f"{target_name} already exists in {d}"
                    )
                # Dedup: shared pool
                clone_skills = skills_dir()
                if clone_skills.exists() and (clone_skills / target_name).exists():
                    raise ValueError(
                        f"{target_name} already exists in shared pool"
                    )
                shutil.copytree(src, dest)
                logger.info("Adopted skill: %s → %s in %s", skill_name, target_name, d)
                return {
                    "adopted": target_name,
                    "source": skill_name,
                    "source_path": str(src),
                    "dest_path": str(dest),
                }

        raise ValueError(
            f"Skill '{skill_name}' not found in any local skills directory"
        )
