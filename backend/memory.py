"""Elara's long-term memory: conversation history + learned facts (SQLite).

Messages give her continuity across restarts; facts are things she has
explicitly learned about the user (via the remember_fact tool). A rolling
summary lets a long conversation stay in context without shipping the entire
transcript to the model every turn.

Facts are not dumped wholesale into every prompt — `relevant_facts` ranks them
against what's being discussed so the context stays lean as the list grows.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from backend.paths import data_dir

DB_PATH = data_dir() / "elara.db"

# Common words carry no signal for matching a fact to a topic.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "at", "by", "from", "my", "your",
    "you", "i", "me", "it", "that", "this", "he", "she", "they", "we", "do",
    "does", "did", "can", "could", "would", "should", "will", "what", "who",
    "how", "when", "where", "why", "about", "get", "got", "have", "has",
}


def _tokens(text: str) -> set[str]:
    """Lowercased, meaningful word tokens for keyword overlap scoring."""
    return {
        w
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _STOPWORDS
    }


class Memory:
    def __init__(self, path: Path = DB_PATH):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now', 'localtime')),
                role TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now', 'localtime')),
                fact TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    # -- conversation history ------------------------------------------------

    def add_message(self, role: str, content: str) -> None:
        if not content.strip():
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (role, content) VALUES (?, ?)", (role, content)
            )
            self._conn.commit()

    def recent_messages(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def message_count(self) -> int:
        with self._lock:
            (n,) = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return n

    def prune_messages(self, keep: int = 400) -> int:
        """Cap the transcript so elara.db can't grow without bound over months.
        Keeps the most recent `keep` messages. Returns how many were removed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM messages WHERE id NOT IN "
                "(SELECT id FROM messages ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            self._conn.commit()
            return cur.rowcount

    def clear_messages(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages")
            self._conn.commit()

    # -- rolling conversation summary ---------------------------------------

    def get_summary(self) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv WHERE key = 'summary'"
            ).fetchone()
        return row[0] if row else ""

    def set_summary(self, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES ('summary', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (summary.strip(),),
            )
            self._conn.commit()

    # -- learned facts -------------------------------------------------------

    def add_fact(self, fact: str) -> None:
        fact = fact.strip()
        if not fact:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO facts (fact) VALUES (?)", (fact,)
            )
            self._conn.commit()

    def facts(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT fact FROM facts ORDER BY id").fetchall()
        return [fact for (fact,) in rows]

    def relevant_facts(self, query: str, limit: int = 8) -> list[str]:
        """The facts most worth putting in front of the model right now.

        Ranks stored facts by keyword overlap with `query` (usually the user's
        latest message plus a little recent context), falling back to recency
        so the list is always filled. When there are only a handful of facts,
        returns them all — filtering only matters once the list is long."""
        all_facts = self.facts()
        if len(all_facts) <= limit:
            return all_facts
        q = _tokens(query)
        scored = [
            (len(q & _tokens(fact)), idx, fact)
            for idx, fact in enumerate(all_facts)
        ]
        # highest overlap first; ties broken by most-recent (higher idx)
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [fact for _score, _idx, fact in scored[:limit]]

    def remove_facts(self, needle: str) -> list[str]:
        """Forget facts matching `needle`, returned so the caller can say what
        went. Matches whole words/phrases (case-insensitive) rather than a raw
        substring, so 'cat' won't quietly delete a fact about a 'vacation'."""
        needle = needle.strip()
        if not needle:
            return []
        pattern = re.compile(
            r"(?<![a-z0-9])" + re.escape(needle.lower()) + r"(?![a-z0-9])"
        )
        with self._lock:
            rows = self._conn.execute("SELECT id, fact FROM facts").fetchall()
            hits = [(fid, fact) for fid, fact in rows if pattern.search(fact.lower())]
            if hits:
                self._conn.executemany(
                    "DELETE FROM facts WHERE id = ?", [(fid,) for fid, _ in hits]
                )
                self._conn.commit()
        return [fact for _fid, fact in hits]
