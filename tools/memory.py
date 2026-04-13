"""
tools/memory.py

Conversation memory for Aria sessions.
Stores and retrieves chat history per founder so Aria never
starts from zero after the first session.

Features:
  - Per-founder conversation history (persisted to disk)
  - Session summarization when history gets long
  - Context injection — builds the message list NIM expects
  - Memory reset per founder
  - Last N turns retrieval for efficient context windows

Usage:
    from tools.memory import Memory

    memory = Memory("claravision")

    # Add turns
    memory.add_user("How do I configure NIM on-premise?")
    memory.add_aria("Self-hosted NIM containers run inside your perimeter...")

    # Get full history as NIM messages list
    messages = memory.as_messages(system="You are Aria...")

    # Get summary of past sessions
    summary = memory.get_summary()

    # Save to disk
    memory.save()

    # Load from disk
    memory = Memory.load("claravision")
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

MEMORY_DIR     = Path("outputs/memory")
MAX_TURNS      = 20     # Max turns kept in active memory before summarization
SUMMARY_TURNS  = 6      # How many recent turns to keep after summarization
ARIA_ROLE      = "assistant"
USER_ROLE      = "user"


# ── Memory ────────────────────────────────────────────────────────────────────

class Memory:
    """
    Manages conversation history for a single founder's Aria sessions.

    History is stored as a list of turn dicts:
        {"role": "user" | "assistant", "content": str, "timestamp": str}

    Persisted to: outputs/memory/<slug>_memory.json
    """

    def __init__(self, slug: str):
        self.slug      = slug
        self.history   = []        # List of turn dicts
        self.summary   = None      # Compressed summary of older turns
        self.created   = datetime.now().isoformat()
        self.last_saved = None

        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    # ── Adding turns ──────────────────────────────────────────────────────────

    def add_user(self, content: str) -> None:
        """Record a message from the founder."""
        self._add(USER_ROLE, content)

    def add_aria(self, content: str) -> None:
        """Record a response from Aria."""
        self._add(ARIA_ROLE, content)

    def add_turn(self, role: str, content: str) -> None:
        """Add a turn with an explicit role. Use 'user' or 'assistant'."""
        if role not in (USER_ROLE, ARIA_ROLE):
            raise ValueError(f"Role must be '{USER_ROLE}' or '{ARIA_ROLE}', got '{role}'")
        self._add(role, content)

    def _add(self, role: str, content: str) -> None:
        self.history.append({
            "role":      role,
            "content":   content,
            "timestamp": datetime.now().isoformat(),
        })
        # Auto-trim if history gets too long
        if len(self.history) > MAX_TURNS:
            self._trim()

    # ── Building NIM message lists ────────────────────────────────────────────

    def as_messages(
        self,
        system: Optional[str] = None,
        last_n: Optional[int] = None,
        include_summary: bool = True,
    ) -> list[dict]:
        """
        Build the messages list that NIM expects.

        Args:
            system:          Optional system prompt prepended to the list.
            last_n:          If set, only include the last N turns.
            include_summary: If True and a summary exists, inject it as context.

        Returns:
            List of {"role": str, "content": str} dicts ready for NIM.
        """
        messages = []

        # System prompt
        if system:
            messages.append({"role": "system", "content": system})

        # Inject summary as context if available
        if include_summary and self.summary:
            messages.append({
                "role": "system",
                "content": f"Summary of earlier conversation:\n{self.summary}"
            })

        # Recent turns
        turns = self.history[-last_n:] if last_n else self.history
        for turn in turns:
            messages.append({
                "role":    turn["role"],
                "content": turn["content"],
            })

        return messages

    def last_user_message(self) -> Optional[str]:
        """Returns the most recent user message, or None."""
        for turn in reversed(self.history):
            if turn["role"] == USER_ROLE:
                return turn["content"]
        return None

    def last_aria_message(self) -> Optional[str]:
        """Returns the most recent Aria response, or None."""
        for turn in reversed(self.history):
            if turn["role"] == ARIA_ROLE:
                return turn["content"]
        return None

    def turn_count(self) -> int:
        return len(self.history)

    def is_empty(self) -> bool:
        return len(self.history) == 0

    # ── Summarization ─────────────────────────────────────────────────────────

    def set_summary(self, summary_text: str) -> None:
        """
        Store a compressed summary of older conversation turns.
        Called by the orchestrator or a background task when history gets long.
        """
        self.summary = summary_text

    def get_summary(self) -> Optional[str]:
        return self.summary

    def build_summary_prompt(self) -> str:
        """
        Returns a prompt you can pass to NIM to generate a summary
        of the current conversation history.
        """
        turns_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}"
            for t in self.history
        )
        return (
            f"Summarize this conversation between a founder and their AI advisor Aria. "
            f"Focus on: technical decisions made, questions asked, blockers identified, "
            f"and next steps agreed. Be concise — under 200 words.\n\n"
            f"CONVERSATION:\n{turns_text}"
        )

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> str:
        """Persist memory to disk. Returns the file path."""
        path = self._path()
        data = {
            "slug":      self.slug,
            "created":   self.created,
            "saved":     datetime.now().isoformat(),
            "summary":   self.summary,
            "history":   self.history,
        }
        path.write_text(json.dumps(data, indent=2))
        self.last_saved = data["saved"]
        return str(path)

    @classmethod
    def load(cls, slug: str) -> "Memory":
        """
        Load memory from disk. Returns a fresh Memory if none exists.
        """
        memory = cls(slug)
        path = memory._path()

        if not path.exists():
            return memory

        try:
            data = json.loads(path.read_text())
            memory.history  = data.get("history", [])
            memory.summary  = data.get("summary")
            memory.created  = data.get("created", memory.created)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[Memory] Could not load memory for {slug}: {e}. Starting fresh.")

        return memory

    @classmethod
    def exists(cls, slug: str) -> bool:
        """Returns True if persisted memory exists for this founder."""
        return cls(slug)._path().exists()

    def reset(self) -> None:
        """Clear all history and summary. Deletes the persisted file."""
        self.history = []
        self.summary = None
        path = self._path()
        if path.exists():
            path.unlink()

    # ── Context helpers ───────────────────────────────────────────────────────

    def get_context_snippet(self, max_chars: int = 500) -> str:
        """
        Returns a short plain-text snippet of recent conversation
        for injection into other prompts (e.g. risk analysis).
        """
        if not self.history:
            return "No conversation history yet."

        recent = self.history[-4:]   # Last 2 exchanges
        lines = []
        for turn in recent:
            role = "Founder" if turn["role"] == USER_ROLE else "Aria"
            lines.append(f"{role}: {turn['content'][:200]}")

        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _path(self) -> Path:
        return MEMORY_DIR / f"{self.slug}_memory.json"

    def _trim(self) -> None:
        """
        Keep only the most recent SUMMARY_TURNS turns in active history.
        The older turns should be summarized before calling this.
        """
        self.history = self.history[-SUMMARY_TURNS:]

    def __repr__(self) -> str:
        return f"Memory(slug={self.slug!r}, turns={self.turn_count()}, has_summary={self.summary is not None})"