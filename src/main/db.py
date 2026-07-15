import sqlite3
import os
import uuid
import time
import json
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

class SessionManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    timestamp INTEGER
                )
            ''')
            conn.commit()

    def get_sessions(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT id, title, timestamp FROM sessions ORDER BY timestamp DESC').fetchall()
            return [{"id": r["id"], "title": r["title"], "timestamp": r["timestamp"]} for r in rows]

    def create_session(self):
        session_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        title = "New Session"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('INSERT INTO sessions (id, title, timestamp) VALUES (?, ?, ?)', (session_id, title, timestamp))
            conn.commit()
        return {"id": session_id, "title": title, "timestamp": timestamp}

    def update_session_title(self, session_id, title):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('UPDATE sessions SET title = ? WHERE id = ?', (title, session_id))
            conn.commit()
            
    def get_session_metadata(self, session_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT id, title, timestamp FROM sessions WHERE id = ?', (session_id,)).fetchone()
            if row:
                return {"id": row["id"], "title": row["title"], "timestamp": row["timestamp"]}
            return None

    def serialize_message(self, m):
        base = {"timestamp": int(time.time() * 1000)}
        if hasattr(m, "additional_kwargs") and "timestamp" in m.additional_kwargs:
            base["timestamp"] = m.additional_kwargs["timestamp"]
        else:
            if not hasattr(m, "additional_kwargs"):
                m.additional_kwargs = {}
            if "timestamp" not in m.additional_kwargs:
                m.additional_kwargs["timestamp"] = base["timestamp"]
            else:
                base["timestamp"] = m.additional_kwargs["timestamp"]

        if isinstance(m, HumanMessage):
            base.update({"role": "user", "content": str(m.content)})
        elif isinstance(m, SystemMessage):
            base.update({"role": "system", "content": str(m.content)})
        elif isinstance(m, AIMessage):
            base.update({"role": "assistant"})
            text = ""
            if isinstance(m.content, list):
                text_parts = [p.get("text", "") for p in m.content if isinstance(p, dict)]
                text = "".join(text_parts)
            else:
                text = str(m.content)
            base["content"] = text
            if hasattr(m, "tool_calls") and m.tool_calls:
                base["tool_calls"] = m.tool_calls
        elif isinstance(m, ToolMessage):
            base.update({
                "role": "tool",
                "name": m.name,
                "tool_call_id": m.tool_call_id,
                "content": str(m.content)
            })
        else:
            base.update({"role": "unknown", "content": str(m)})
            
        return base
