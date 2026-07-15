import aiosqlite
import os
import uuid
import time
import json
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

class SessionManager:
    def __init__(self, db_path):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    timestamp INTEGER
                )
            ''')
            # Table for scheduled tasks
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    prompt TEXT,
                    interval_minutes INTEGER,
                    last_run INTEGER,
                    active BOOLEAN
                )
            ''')
            await conn.commit()

    async def get_sessions(self):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute('SELECT id, title, timestamp FROM sessions ORDER BY timestamp DESC') as cursor:
                rows = await cursor.fetchall()
            return [{"id": r["id"], "title": r["title"], "timestamp": r["timestamp"]} for r in rows]

    async def create_session(self):
        session_id = str(uuid.uuid4())
        timestamp = int(time.time() * 1000)
        title = "New Session"
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('INSERT INTO sessions (id, title, timestamp) VALUES (?, ?, ?)', (session_id, title, timestamp))
            await conn.commit()
        return {"id": session_id, "title": title, "timestamp": timestamp}

    async def update_session_title(self, session_id, title):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('UPDATE sessions SET title = ? WHERE id = ?', (title, session_id))
            await conn.commit()
            
    async def get_session_metadata(self, session_id):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute('SELECT id, title, timestamp FROM sessions WHERE id = ?', (session_id,)) as cursor:
                row = await cursor.fetchone()
            if row:
                return {"id": row["id"], "title": row["title"], "timestamp": row["timestamp"]}
            return None

    # Scheduled Tasks Methods
    async def create_scheduled_task(self, prompt, interval_minutes):
        task_id = str(uuid.uuid4())
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('INSERT INTO scheduled_tasks (id, prompt, interval_minutes, last_run, active) VALUES (?, ?, ?, ?, ?)', 
                               (task_id, prompt, interval_minutes, 0, True))
            await conn.commit()
        return task_id

    async def get_scheduled_tasks(self):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute('SELECT * FROM scheduled_tasks') as cursor:
                rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def update_task_last_run(self, task_id, last_run):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('UPDATE scheduled_tasks SET last_run = ? WHERE id = ?', (last_run, task_id))
            await conn.commit()

    async def delete_scheduled_task(self, task_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('DELETE FROM scheduled_tasks WHERE id = ?', (task_id,))
            await conn.commit()

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
            
            # Extract token and cost details
            if hasattr(m, "response_metadata") and m.response_metadata:
                token_usage = m.response_metadata.get("token_usage", {})
                if token_usage:
                    base["input_tokens"] = token_usage.get("prompt_tokens", 0)
                    base["output_tokens"] = token_usage.get("completion_tokens", 0)
                
                # Try to extract Anthropic-specific usage
                usage = m.response_metadata.get("usage", {})
                if usage and not token_usage:
                    base["input_tokens"] = usage.get("input_tokens", 0)
                    base["output_tokens"] = usage.get("output_tokens", 0)
                    
                # We can compute approximate cost if using Claude or others based on token counts later in get_session_cost.

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
