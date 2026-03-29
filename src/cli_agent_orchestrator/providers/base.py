"""Base provider interface for CLI tool abstraction.

This module defines the abstract base class that all CLI providers must implement.
A "provider" is an adapter that enables CAO to interact with a specific CLI-based
AI agent (e.g., Kiro CLI, Claude Code, Codex, Q CLI).

Provider Responsibilities:
- Initialize the CLI tool in a tmux window (run startup commands)
- Detect terminal state by parsing terminal output (IDLE, PROCESSING, COMPLETED, etc.)
- Extract agent responses from terminal output
- Provide cleanup logic when terminal is deleted

Implemented Providers:
- KiroCliProvider: For Kiro CLI (kiro-cli chat)
- ClaudeCodeProvider: For Claude Code (claude)
- CodexProvider: For Codex CLI (codex)
- QCliProvider: For Amazon Q Developer CLI (q chat)

Each provider must implement pattern matching for its specific CLI's prompt
and output format to reliably detect status changes.
"""

from abc import ABC, abstractmethod
import re
from typing import Dict, List, Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus


class BaseProvider(ABC):
    """Abstract base class for CLI tool providers.

    All CLI providers must inherit from this class and implement the abstract methods.
    The provider abstraction allows CAO to work with different CLI-based AI agents
    through a unified interface.

    Attributes:
        terminal_id: Unique identifier for the terminal this provider manages
        session_name: Name of the tmux session containing the terminal
        window_name: Name of the tmux window containing the terminal
        _status: Internal status cache (use get_status() for current status)
        _env_vars: Environment variables to set before launching the CLI tool
    """

    def __init__(self, terminal_id: str, session_name: str, window_name: str):
        """Initialize provider with terminal context.

        Args:
            terminal_id: Unique identifier for this terminal instance
            session_name: Name of the tmux session
            window_name: Name of the tmux window
        """
        self.terminal_id = terminal_id
        self.session_name = session_name
        self.window_name = window_name
        self._status = TerminalStatus.IDLE
        self._env_vars: Dict[str, str] = {}

    @property
    def status(self) -> TerminalStatus:
        """Get current provider status."""
        return self._status

    @property
    def paste_enter_count(self) -> int:
        """Number of Enter keys to send after pasting user input.

        After bracketed paste (``paste-buffer -p``), many TUIs (e.g.
        Claude Code) enter multi-line mode. The first Enter adds a
        newline; the second Enter on the empty line triggers submission.

        Default is 2 (double-Enter). Override to 1 for TUIs where single
        Enter submits after bracketed paste.
        """
        return 2

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the provider (e.g., start CLI tool, send setup commands).

        Returns:
            bool: True if initialization successful, False otherwise
        """
        pass

    @abstractmethod
    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Get current provider status by analyzing terminal output.

        Args:
            tail_lines: Number of lines to capture from terminal (default: provider-specific)

        Returns:
            TerminalStatus: Current status of the provider
        """
        pass

    @abstractmethod
    def get_idle_pattern_for_log(self) -> str:
        """Get pattern that indicates IDLE state in log file output.

        Used for quick detection in file watcher before calling full get_status().
        Should return a simple pattern that appears in the IDLE prompt.

        Returns:
            str: Pattern to search for in log file tail
        """
        pass

    @property
    def extraction_retries(self) -> int:
        """Number of extraction retries for transient TUI rendering issues.

        TUI-based providers (e.g. Gemini CLI's Ink renderer) may show
        notification spinners that temporarily obscure response text in
        the tmux capture buffer.  Override this to enable automatic retries
        with re-capture between attempts.  Default is 0 (no retries).
        """
        return 0

    @abstractmethod
    def extract_last_message_from_script(self, script_output: str) -> str:
        """Extract the last message from terminal script output.

        Args:
            script_output: Raw terminal output/script content

        Returns:
            str: Extracted last message from the provider
        """
        pass

    @abstractmethod
    def exit_cli(self) -> str:
        """Get the command to exit the provider CLI.

        Returns:
            Command string to send to terminal for exiting
        """
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up provider resources."""
        pass

    @property
    def env_vars(self) -> Dict[str, str]:
        """Environment variables to set before launching the CLI tool."""
        return self._env_vars

    def set_env_vars(self, env_vars: Dict[str, str]) -> None:
        """Set environment variables to be applied before CLI launch.

        Args:
            env_vars: Mapping of variable names to values. These will be
                exported in the tmux shell before the CLI command is started.
        """
        self._env_vars = dict(env_vars)

    # Regex for valid POSIX shell variable names (letters, digits, underscores;
    # must not start with a digit).
    _ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def _apply_env_vars(self) -> None:
        """Send ``export KEY=VALUE`` commands via tmux for each configured env var.

        Should be called in ``initialize()`` *before* launching the CLI command.
        Uses ``send_keys`` which pastes + Enter; a short sleep between exports
        gives the shell time to process each line.

        Raises:
            ValueError: If any key is not a valid shell variable name.
        """
        import shlex
        import time

        for key, value in self._env_vars.items():
            if not self._ENV_KEY_RE.match(key):
                raise ValueError(
                    f"Invalid environment variable name: {key!r}. "
                    "Only letters, digits and underscores are allowed "
                    "(must not start with a digit)."
                )
            cmd = f"export {key}={shlex.quote(value)}"
            tmux_client.send_keys(self.session_name, self.window_name, cmd)
            time.sleep(0.3)

    def graceful_exit(self) -> Optional[str]:
        """Gracefully exit the CLI and return a session identifier if available.

        Providers that support session persistence (e.g. OpenCode) should
        override this to:
        1. Send the appropriate exit signal.
        2. Wait for the CLI to terminate.
        3. Capture terminal output and extract a resumable session ID.

        Returns:
            Session identifier string for resuming later, or ``None`` if the
            provider does not support session persistence.
        """
        return None

    def mark_input_received(self) -> None:
        """Notify the provider that external input was sent to the terminal.

        Called by the terminal service after send_input() delivers a message.
        Providers can override this to adjust status detection behavior.
        For example, providers with initial prompts can use this to
        distinguish post-init idle (ready for first input) from
        post-task completed.
        """
        pass

    def _update_status(self, status: TerminalStatus) -> None:
        """Update internal status."""
        self._status = status
