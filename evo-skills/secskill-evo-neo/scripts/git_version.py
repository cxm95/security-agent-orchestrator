"""Git version management for skill evolution.

Provides CLI commands for snapshotting, tagging, diffing, and reverting
skill versions via git. All operations use subprocess to call git CLI.
All output is JSON for agent consumption.

Safety: mutating commands (commit, revert) refuse to operate on
directories outside /tmp/cao-evo-workspace/ to prevent accidental
pollution of parent repositories.

Usage:
    python -m scripts.git_version init <skill-dir>
    python -m scripts.git_version commit <skill-dir> --message "msg" [--tag v1]
    python -m scripts.git_version log <skill-dir>
    python -m scripts.git_version diff <skill-dir> [--from v1] [--to v2]
    python -m scripts.git_version revert <skill-dir> --to v1
    python -m scripts.git_version current <skill-dir>
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Only directories under this prefix are allowed for mutating operations.
SAFE_PREFIX = "/tmp/cao-evo-workspace/"


def _run_git(args: list[str], cwd: str | Path) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _output(data: dict) -> None:
    """Print JSON output for agent consumption."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _check_safe_workspace(skill_dir: Path, command: str) -> bool:
    """Verify skill_dir is inside the safe workspace prefix.

    Mutating commands (commit, revert) must only operate on isolated
    workspaces under /tmp/cao-evo-workspace/ to prevent polluting
    parent repositories like .cao-evolution-client/ or the project root.

    Read-only commands (init, log, diff, current) are allowed anywhere.
    """
    resolved = str(skill_dir.resolve())
    if not resolved.startswith(SAFE_PREFIX):
        _output({
            "status": "error",
            "message": (
                f"Safety check failed: '{command}' refused because "
                f"'{resolved}' is not under {SAFE_PREFIX}. "
                f"Copy the skill to /tmp/cao-evo-workspace/<name>/ first."
            ),
        })
        return False
    return True


def _is_inside_git_repo(path: Path) -> bool:
    """Check if path is inside an existing git repository."""
    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _get_repo_root(path: Path) -> str:
    """Get the top-level directory of the git repo containing path."""
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode != 0:
        raise RuntimeError(f"Not inside a git repo: {path}")
    return result.stdout.strip()


def _get_relative_path(skill_dir: Path) -> str:
    """Get skill_dir relative to the git repo root."""
    repo_root = _get_repo_root(skill_dir)
    try:
        return str(skill_dir.resolve().relative_to(Path(repo_root).resolve()))
    except ValueError:
        return "."


# ── Commands ─────────────────────────────────────────────────────────


def cmd_init(skill_dir: Path) -> None:
    """Initialize git tracking for a skill directory.

    If already inside a git repo, reports the existing repo.
    Otherwise, initializes a new repo at the skill directory.
    """
    skill_dir = skill_dir.resolve()

    if not skill_dir.exists():
        _output({"status": "error", "message": f"Directory does not exist: {skill_dir}"})
        sys.exit(1)

    if _is_inside_git_repo(skill_dir):
        repo_root = _get_repo_root(skill_dir)
        rel_path = _get_relative_path(skill_dir)
        _output({
            "status": "ok",
            "message": "Already inside a git repository",
            "repo_root": repo_root,
            "skill_relative_path": rel_path,
            "initialized_new": False,
        })
        return

    # Initialize a new repo at the skill directory
    result = _run_git(["init"], cwd=skill_dir)
    if result.returncode != 0:
        _output({"status": "error", "message": f"git init failed: {result.stderr.strip()}"})
        sys.exit(1)

    # Configure user identity for this repo (required for commits)
    _run_git(["config", "user.email", "cao-evo@local"], cwd=skill_dir)
    _run_git(["config", "user.name", "cao-evo"], cwd=skill_dir)

    # Initial commit with all existing files
    _run_git(["add", "-A"], cwd=skill_dir)
    _run_git(["commit", "-m", "initial: skill baseline"], cwd=skill_dir)

    _output({
        "status": "ok",
        "message": "Initialized new git repository",
        "repo_root": str(skill_dir),
        "skill_relative_path": ".",
        "initialized_new": True,
    })


def cmd_commit(skill_dir: Path, message: str, tag: str | None = None) -> None:
    """Commit current state of skill files, optionally tagging."""
    skill_dir = skill_dir.resolve()

    if not _check_safe_workspace(skill_dir, "commit"):
        sys.exit(1)

    if not _is_inside_git_repo(skill_dir):
        _output({"status": "error", "message": "Not inside a git repository. Run 'init' first."})
        sys.exit(1)

    rel_path = _get_relative_path(skill_dir)
    repo_root = _get_repo_root(skill_dir)

    # Stage all changes in the skill directory
    if rel_path == ".":
        _run_git(["add", "-A"], cwd=repo_root)
    else:
        _run_git(["add", "-A", rel_path], cwd=repo_root)

    # Check if there are staged changes
    status_result = _run_git(["diff", "--cached", "--quiet"], cwd=repo_root)
    if status_result.returncode == 0:
        # No changes to commit — still tag if requested
        if tag:
            tag_result = _run_git(["tag", tag], cwd=repo_root)
            if tag_result.returncode != 0:
                _output({"status": "warning", "message": f"No changes to commit. Tag failed: {tag_result.stderr.strip()}"})
                return
            _output({"status": "ok", "message": "No changes to commit, but tag created.", "tag": tag})
            return
        _output({"status": "ok", "message": "No changes to commit."})
        return

    # Commit
    commit_result = _run_git(["commit", "-m", message], cwd=repo_root)
    if commit_result.returncode != 0:
        _output({"status": "error", "message": f"Commit failed: {commit_result.stderr.strip()}"})
        sys.exit(1)

    # Get the commit hash
    hash_result = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_root)
    commit_hash = hash_result.stdout.strip()

    result_data: dict = {
        "status": "ok",
        "message": "Committed successfully",
        "commit": commit_hash,
        "commit_message": message,
    }

    # Tag if requested
    if tag:
        tag_result = _run_git(["tag", tag], cwd=repo_root)
        if tag_result.returncode != 0:
            result_data["tag_error"] = tag_result.stderr.strip()
        else:
            result_data["tag"] = tag

    _output(result_data)


def cmd_log(skill_dir: Path) -> None:
    """Show version history for the skill directory."""
    skill_dir = skill_dir.resolve()

    if not _is_inside_git_repo(skill_dir):
        _output({"status": "error", "message": "Not inside a git repository."})
        sys.exit(1)

    rel_path = _get_relative_path(skill_dir)
    repo_root = _get_repo_root(skill_dir)

    log_args = [
        "log", "--pretty=format:%H|%h|%s|%ai|%D",
        "--", rel_path if rel_path != "." else ".",
    ]
    result = _run_git(log_args, cwd=repo_root)

    if result.returncode != 0:
        _output({"status": "error", "message": f"git log failed: {result.stderr.strip()}"})
        sys.exit(1)

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 4:
            continue
        full_hash, short_hash, subject, date = parts[0], parts[1], parts[2], parts[3]
        refs = parts[4] if len(parts) > 4 else ""

        # Extract tags from refs
        tags = []
        if refs:
            for ref in refs.split(","):
                ref = ref.strip()
                if ref.startswith("tag: "):
                    tags.append(ref[5:])

        entries.append({
            "hash": short_hash,
            "full_hash": full_hash,
            "message": subject,
            "date": date.strip(),
            "tags": tags,
        })

    _output({"status": "ok", "entries": entries, "total": len(entries)})


def cmd_diff(skill_dir: Path, from_ref: str | None = None, to_ref: str | None = None) -> None:
    """Show diff between two versions."""
    skill_dir = skill_dir.resolve()

    if not _is_inside_git_repo(skill_dir):
        _output({"status": "error", "message": "Not inside a git repository."})
        sys.exit(1)

    rel_path = _get_relative_path(skill_dir)
    repo_root = _get_repo_root(skill_dir)

    diff_args = ["diff"]
    if from_ref and to_ref:
        diff_args += [from_ref, to_ref]
    elif from_ref:
        diff_args += [from_ref, "HEAD"]
    elif to_ref:
        diff_args += ["HEAD", to_ref]
    # else: diff working tree against HEAD

    diff_args += ["--", rel_path if rel_path != "." else "."]

    result = _run_git(diff_args, cwd=repo_root)
    if result.returncode != 0:
        _output({"status": "error", "message": f"git diff failed: {result.stderr.strip()}"})
        sys.exit(1)

    # Also get stat summary
    stat_args = diff_args.copy()
    stat_args.insert(1, "--stat")
    stat_result = _run_git(stat_args, cwd=repo_root)

    _output({
        "status": "ok",
        "diff": result.stdout,
        "stat": stat_result.stdout.strip() if stat_result.returncode == 0 else "",
        "from": from_ref or "HEAD",
        "to": to_ref or ("working tree" if not from_ref else "HEAD"),
    })


def cmd_revert(skill_dir: Path, to_ref: str) -> None:
    """Revert skill files to a specific version.

    Checks out files from the target ref and commits the result,
    preserving full history. Only operates on the skill's subdirectory
    within the repo — never the entire repo root.
    """
    skill_dir = skill_dir.resolve()

    if not _check_safe_workspace(skill_dir, "revert"):
        sys.exit(1)

    if not _is_inside_git_repo(skill_dir):
        _output({"status": "error", "message": "Not inside a git repository."})
        sys.exit(1)

    repo_root = _get_repo_root(skill_dir)
    rel_path = _get_relative_path(skill_dir)

    # Safety: refuse to revert the entire repo root
    if rel_path == ".":
        repo_root_resolved = str(Path(repo_root).resolve())
        skill_dir_resolved = str(skill_dir)
        if repo_root_resolved == skill_dir_resolved:
            # This is fine — the workspace IS the repo (init created it)
            pass
        else:
            _output({
                "status": "error",
                "message": "Refusing to revert: relative path resolved to '.' but skill_dir != repo_root. This could affect files outside the skill directory.",
            })
            sys.exit(1)

    # Verify the target ref exists
    ref_result = _run_git(["rev-parse", to_ref], cwd=repo_root)
    if ref_result.returncode != 0:
        _output({"status": "error", "message": f"Unknown ref '{to_ref}': {ref_result.stderr.strip()}"})
        sys.exit(1)
    target_hash = ref_result.stdout.strip()

    # Check if already at target
    head_result = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    head_hash = head_result.stdout.strip()

    if target_hash == head_hash:
        _output({"status": "ok", "message": "Already at the target version."})
        return

    # Checkout files from the target ref
    checkout_path = rel_path if rel_path != "." else "."
    checkout_result = _run_git(["checkout", to_ref, "--", checkout_path], cwd=repo_root)

    if checkout_result.returncode != 0:
        _output({"status": "error", "message": f"Checkout failed: {checkout_result.stderr.strip()}"})
        sys.exit(1)

    # Commit the reverted state
    revert_msg = f"revert: restore to {to_ref}"
    _run_git(["add", "-A", checkout_path], cwd=repo_root)
    commit_result = _run_git(["commit", "-m", revert_msg], cwd=repo_root)

    if commit_result.returncode != 0:
        # No changes — files already match target
        _output({"status": "ok", "message": f"Files already match {to_ref}, no revert needed."})
        return

    new_hash = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_root).stdout.strip()

    _output({
        "status": "ok",
        "message": f"Reverted to {to_ref}",
        "reverted_to": to_ref,
        "new_commit": new_hash,
        "commit_message": revert_msg,
    })


def cmd_current(skill_dir: Path) -> None:
    """Get current version info (HEAD commit + tags)."""
    skill_dir = skill_dir.resolve()

    if not _is_inside_git_repo(skill_dir):
        _output({"status": "error", "message": "Not inside a git repository."})
        sys.exit(1)

    repo_root = _get_repo_root(skill_dir)

    hash_result = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_root)
    full_hash_result = _run_git(["rev-parse", "HEAD"], cwd=repo_root)
    msg_result = _run_git(["log", "-1", "--pretty=format:%s"], cwd=repo_root)
    date_result = _run_git(["log", "-1", "--pretty=format:%ai"], cwd=repo_root)

    # Tags pointing at HEAD
    tags_result = _run_git(["tag", "--points-at", "HEAD"], cwd=repo_root)
    tags = [t.strip() for t in tags_result.stdout.strip().split("\n") if t.strip()]

    # All version tags (proxy for version number)
    all_tags_result = _run_git(["tag", "-l", "v*"], cwd=repo_root)
    all_version_tags = [t.strip() for t in all_tags_result.stdout.strip().split("\n") if t.strip()]

    _output({
        "status": "ok",
        "hash": hash_result.stdout.strip(),
        "full_hash": full_hash_result.stdout.strip(),
        "message": msg_result.stdout.strip(),
        "date": date_result.stdout.strip(),
        "tags": tags,
        "total_version_tags": len(all_version_tags),
    })


# ── CLI ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Git version management for skill evolution",
        prog="python -m scripts.git_version",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize git tracking")
    p_init.add_argument("skill_dir", type=Path)

    # commit
    p_commit = subparsers.add_parser("commit", help="Commit with optional tag")
    p_commit.add_argument("skill_dir", type=Path)
    p_commit.add_argument("--message", "-m", required=True)
    p_commit.add_argument("--tag", "-t")

    # log
    p_log = subparsers.add_parser("log", help="Show version history")
    p_log.add_argument("skill_dir", type=Path)

    # diff
    p_diff = subparsers.add_parser("diff", help="Show diff between versions")
    p_diff.add_argument("skill_dir", type=Path)
    p_diff.add_argument("--from", dest="from_ref")
    p_diff.add_argument("--to", dest="to_ref")

    # revert
    p_revert = subparsers.add_parser("revert", help="Revert to a specific version")
    p_revert.add_argument("skill_dir", type=Path)
    p_revert.add_argument("--to", dest="to_ref", required=True)

    # current
    p_current = subparsers.add_parser("current", help="Get current version info")
    p_current.add_argument("skill_dir", type=Path)

    args = parser.parse_args()

    commands = {
        "init": lambda: cmd_init(args.skill_dir),
        "commit": lambda: cmd_commit(args.skill_dir, args.message, args.tag),
        "log": lambda: cmd_log(args.skill_dir),
        "diff": lambda: cmd_diff(args.skill_dir, args.from_ref, args.to_ref),
        "revert": lambda: cmd_revert(args.skill_dir, args.to_ref),
        "current": lambda: cmd_current(args.skill_dir),
    }

    commands[args.command]()


if __name__ == "__main__":
    main()
