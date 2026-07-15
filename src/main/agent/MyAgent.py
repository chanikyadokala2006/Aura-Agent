import os
import subprocess
import psutil
import pyautogui
import time
import base64
from io import BytesIO
from typing import Literal, Optional
from pydantic import BaseModel, Field
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv


from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, RemoveMessage
from deepagents import create_deep_agent
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langchain.agents.middleware import AgentMiddleware
from agent.skills_manager import SkillsManager
from agent.wsl_bridge import WSLPythonREPLTool

load_dotenv()

aicredits_key = os.getenv("AICREDITS_API_KEY")
if not aicredits_key:
    raise ValueError("AICREDITS_API_KEY is not set. Please set it in the .env file.")

from deepagents.backends import LocalShellBackend

import subprocess
import json
import threading
import atexit
from typing import Any, List, Dict
from pydantic import Field, create_model

active_mcp_servers = []
active_mcp_langchain_tools = []

class McpClient:
    def __init__(self, name, command, args, env=None, cwd=None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.cwd = cwd
        self.process = None
        self.request_id = 1
        self.tools = []

    def start(self):
        try:
            full_command = [self.command] + self.args
            use_shell = True if self.command == "npx" or os.name == "nt" else False
            run_env = os.environ.copy()
            if self.env:
                run_env.update(self.env)
                
            self.process = subprocess.Popen(
                full_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=run_env,
                shell=use_shell,
                cwd=self.cwd
            )
            
            threading.Thread(target=self._log_errors, daemon=True).start()
            
            if not self._initialize():
                self.stop()
                return False
                
            self.tools = self._list_tools()
            return True
        except Exception as e:
            print(f"[MCP] Failed to start server {self.name}: {e}")
            return False

    def _log_errors(self):
        while self.process and self.process.poll() is None:
            line = self.process.stderr.readline()
            if not line:
                break

    def _send_request(self, method, params=None):
        if not self.process or self.process.poll() is not None:
            return None
            
        req = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method
        }
        if params:
            req["params"] = params
            
        data = json.dumps(req) + "\n"
        try:
            self.process.stdin.write(data.encode('utf-8'))
            self.process.stdin.flush()
        except Exception as e:
            print(f"[MCP] Error writing to {self.name}: {e}")
            return None
            
        self.request_id += 1
        return self._read_response(req["id"])

    def _send_notification(self, method, params=None):
        if not self.process or self.process.poll() is not None:
            return
            
        req = {
            "jsonrpc": "2.0",
            "method": method
        }
        if params:
            req["params"] = params
            
        data = json.dumps(req) + "\n"
        try:
            self.process.stdin.write(data.encode('utf-8'))
            self.process.stdin.flush()
        except Exception:
            pass

    def _read_response(self, expected_id):
        try:
            import time
            start_time = time.time()
            while time.time() - start_time < 10:
                line = self.process.stdout.readline()
                if not line:
                    break
                try:
                    resp = json.loads(line.decode('utf-8'))
                    if resp.get("id") == expected_id:
                        return resp
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"[MCP] Error reading from {self.name}: {e}")
        return None

    def _initialize(self):
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "python-mcp-client", "version": "1.0"}
        }
        resp = self._send_request("initialize", init_params)
        if not resp or "error" in resp:
            print(f"[MCP] Initialize failed for {self.name}: {resp}")
            return False
            
        self._send_notification("notifications/initialized")
        return True

    def _list_tools(self):
        resp = self._send_request("tools/list")
        if resp and "result" in resp:
            return resp["result"].get("tools", [])
        return []

    def call_tool(self, tool_name, arguments):
        resp = self._send_request("tools/call", {"name": tool_name, "arguments": arguments})
        if not resp:
            return "Error: No response from MCP server."
        if "error" in resp:
            return f"MCP Error: {resp['error']}"
        
        result = resp.get("result", {})
        content_list = result.get("content", [])
        text_out = []
        for content in content_list:
            if content.get("type") == "text":
                text_out.append(content.get("text", ""))
        return "\n".join(text_out) if text_out else str(result)

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

def json_schema_to_pydantic(properties, required_fields):
    from pydantic import Field, create_model
    from typing import Any, List, Dict
    
    fields = {}
    for name, prop in properties.items():
        p_type = prop.get("type", "string")
        desc = prop.get("description", "")
        
        if p_type == "string":
            py_type = str
        elif p_type == "integer":
            py_type = int
        elif p_type == "number":
            py_type = float
        elif p_type == "boolean":
            py_type = bool
        elif p_type == "array":
            py_type = list
        elif p_type == "object":
            py_type = dict
        else:
            py_type = Any
            
        default_val = ... if name in required_fields else None
        fields[name] = (py_type, Field(default=default_val, description=desc))
        
    return create_model("McpToolSchema", **fields)

def make_mcp_langchain_tool(client, mcp_tool):
    from langchain_core.tools import StructuredTool
    name = f"mcp_{client.name}_{mcp_tool['name']}"
    desc = mcp_tool.get("description", "")
    schema = mcp_tool.get("inputSchema", {})
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    try:
        args_schema = json_schema_to_pydantic(properties, required)
    except Exception:
        args_schema = None
        
    def _execute(**kwargs):
        return client.call_tool(mcp_tool["name"], kwargs)
        
    return StructuredTool(
        name=name,
        func=_execute,
        description=desc,
        args_schema=args_schema
    )

def cleanup_mcp_servers():
    for client in active_mcp_servers:
        try:
            client.stop()
        except Exception:
            pass
    active_mcp_servers.clear()

atexit.register(cleanup_mcp_servers)

AgentModel = ChatOpenAI(
    base_url="https://aicredits.in/v1",
    api_key=aicredits_key,
    model="anthropic/claude-sonnet-latest",
    temperature=0
)

from typing import Any


import hashlib

def stable_tool_key(name: str, args: dict) -> str:
    if name == 'read_file':
        try:
            line = int(args.get('start_line', 0))
            bucket = line // 200
            return f"{name}:{args.get('file_path', '')}:{bucket}"
        except:
            pass
    elif name == 'write_file':
        content = str(args.get('content', ''))
        content_hash = hashlib.md5(content.encode()).hexdigest()
        return f"{name}:{args.get('file_path', '')}:{content_hash}"
    elif name == 'str_replace':
        return f"{name}:{args.get('path', '')}:{args.get('old_str', '')}:{args.get('new_str', '')}"
    
    clean_args = {k: v for k, v in args.items() if k not in ['session_id', 'ts']}
    sorted_items = sorted(clean_args.items())
    return f"{name}:{str(sorted_items)}"

def message_calls_hash(tool_calls: list) -> str:
    if not tool_calls:
        return ""
    keys = [stable_tool_key(tc['name'], tc.get('args', {})) for tc in tool_calls]
    combined = "|".join(keys)
    return hashlib.md5(combined.encode()).hexdigest()

class LoopGuardMiddleware(AgentMiddleware):
    def __init__(self):
        self.current_streak = 0
        self.current_hash = ""
        self.tool_frequencies = {}

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last_msg = messages[-1]
        
        if getattr(last_msg, "type", None) != "ai" or not getattr(last_msg, "tool_calls", None):
            return None
            
        t_hash = message_calls_hash(last_msg.tool_calls)
        if t_hash == self.current_hash:
            self.current_streak += 1
        else:
            self.current_streak = 1
            self.current_hash = t_hash
            
        for tc in last_msg.tool_calls:
            name = tc['name']
            self.tool_frequencies[name] = self.tool_frequencies.get(name, 0) + 1
            
        if self.current_streak >= 5:
            raise RuntimeError("Loop Guard ABORT: Model is stuck in an infinite loop.")
        elif self.current_streak >= 4:
            raise RuntimeError("Loop Guard HALT: Repeatedly calling the same tools.")
        elif self.current_streak == 3:
            tool_msgs = []
            for tc in last_msg.tool_calls:
                tool_msgs.append(ToolMessage(
                    content="[Loop Guard Warning]: You have called the exact same tools 3 times in a row. Stop repeating yourself and try a different approach. Remember to wait for page loads.",
                    tool_call_id=tc["id"],
                    name=tc["name"]
                ))
            return {"messages": tool_msgs}
            
        for name, count in self.tool_frequencies.items():
            if count >= 15:
                raise RuntimeError(f"Loop Guard ABORT: Tool '{name}' called 15 times.")
            elif count >= 12:
                raise RuntimeError(f"Loop Guard HALT: Tool '{name}' called 12 times.")
            elif count == 10:
                tool_msgs = []
                for tc in last_msg.tool_calls:
                    tool_msgs.append(ToolMessage(
                        content=f"[Loop Guard Warning]: You have used the tool '{name}' 10 times. You are likely in a loop. Try a completely different approach.",
                        tool_call_id=tc["id"],
                        name=tc["name"]
                    ))
                return {"messages": tool_msgs}
                
        return None


class PatchToolMessagesMiddleware(AgentMiddleware):
    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        patched_messages = []
        remove_messages = []
        modified = False

        # Keep only the last 16 messages to strictly bound context and prevent runaway costs
        if len(messages) > 16:
            for m in messages[:-16]:
                if hasattr(m, "id") and m.id:
                    remove_messages.append(RemoveMessage(id=m.id))
            messages = messages[-16:]
            modified = True

        # Find the index of the most recent message with an image and the most recent memory injection
        latest_img_idx = -1
        latest_memory_idx = -1
        for i, msg in enumerate(messages):
            if getattr(msg, "content", None) and isinstance(msg.content, list):
                if any(isinstance(p, dict) and p.get("type") == "image_url" for p in msg.content):
                    latest_img_idx = i
            if isinstance(msg, SystemMessage) and isinstance(msg.content, str) and "<retrieved_long_term_memory>" in msg.content:
                latest_memory_idx = i

        for i, msg in enumerate(messages):
            content = getattr(msg, "content", None)
            # Aggressively truncate tool outputs to save tokens
            if isinstance(msg, ToolMessage) and isinstance(content, str):
                # Is it a recent message? (within the last 4 messages in the window)
                is_recent = i >= (len(messages) - 4)
                max_len = 6000 if is_recent else 500
                
                if len(content) > max_len:
                    truncated_content = content[:max_len] + f"\n... [TRUNCATED TOOL OUTPUT ({len(content)} bytes)]"
                    patched_messages.append(ToolMessage(content=truncated_content, name=msg.name, tool_call_id=msg.tool_call_id, id=msg.id))
                    modified = True
            # Remove old injected memory contexts to prevent them from stacking up over multiple turns
            if isinstance(msg, SystemMessage) and isinstance(content, str) and "<retrieved_long_term_memory>" in content:
                if i != latest_memory_idx and hasattr(msg, "id") and msg.id:
                    remove_messages.append(RemoveMessage(id=msg.id))
                    modified = True
                    continue

            if content and isinstance(content, list):
                new_content = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        if i == latest_img_idx:
                            new_content.append(part)
                        else:
                            new_content.append({"type": "text", "text": "[Image removed from history to save context space]"})
                            modified = True
                    else:
                        new_content.append(part)
                
                if isinstance(msg, ToolMessage):
                    patched_messages.append(ToolMessage(content=new_content, name=msg.name, tool_call_id=msg.tool_call_id, id=msg.id))
                elif isinstance(msg, HumanMessage):
                    patched_messages.append(HumanMessage(content=new_content, id=msg.id))
                else:
                    patched_messages.append(msg)
            else:
                patched_messages.append(msg)

        if modified:
            return {"messages": remove_messages + [RemoveMessage(id=REMOVE_ALL_MESSAGES), *patched_messages]}
        return None

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
            
        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None
            
        modified = False
        content = last_msg.content
        tool_calls = getattr(last_msg, "tool_calls", [])

        if isinstance(content, str) and "<function=" in content and not tool_calls:
            import re
            import json
            import uuid
            
            # Match <function=name{args}></function>
            pattern = r"<function=([a-zA-Z0-9_-]+)(.*?)(?:></function>|>|</function>)"
            matches = list(re.finditer(pattern, content, re.DOTALL))
            
            if matches:
                m = matches[0]
                name = m.group(1)
                args_str = m.group(2).strip()
                
                # Truncate content to only show the first function call
                content = content[:m.end()]
                
                # Fix common llama 3 JSON hallucination where it puts extra braces
                args_str = args_str.replace("}, \"", ", \"")
                
                if args_str and not args_str.startswith("{"):
                    args_str = "{" + args_str
                if args_str and not args_str.endswith("}"):
                    args_str = args_str + "}"
                    
                args = {}
                if args_str:
                    try:
                        args = json.loads(args_str)
                    except:
                        pass
                        
                tool_calls = [{
                    "name": name,
                    "args": args,
                    "id": f"call_{uuid.uuid4().hex[:8]}"
                }]
                modified = True
                
        # Enforce step-by-step execution by truncating to max 1 tool call globally
        if tool_calls and len(tool_calls) > 1:
            tool_calls = [tool_calls[0]]
            modified = True
            
        if modified:
            new_msg = AIMessage(
                content=content,
                tool_calls=tool_calls,
                id=last_msg.id
            )
            return {"messages": [RemoveMessage(id=last_msg.id), new_msg]}
                
        return None

# ---------------------------------------------------------------------------
# Scope: everything the agent can search/read/list is bounded to this root.
# Defaulted to whole-system (C:\) per user preference. Narrow this back to a
# project folder via AGENT_SANDBOX_ROOT if you ever want to restrict it again.
# ---------------------------------------------------------------------------
SANDBOX_ROOT = os.path.abspath(os.environ.get("AGENT_SANDBOX_ROOT", "C:\\"))

# ---------------------------------------------------------------------------
# Long Term Memory (ChromaDB) Configuration
# ---------------------------------------------------------------------------
DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".chroma_db"))
MEMORY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "agent_memory"))

# Ensure memory folder exists
if not os.path.exists(MEMORY_DIR):
    os.makedirs(MEMORY_DIR)
    try:
        with open(os.path.join(MEMORY_DIR, "README.md"), "w", encoding="utf-8") as f:
            f.write(
                "# Agent Long Term Memory\n\n"
                "Place high-level text instructions, custom scripts, workflow guidelines, and task summaries "
                "here. The agent will automatically index them in ChromaDB and retrieve relevant files to "
                "guide its planning phase!\n"
            )
    except Exception:
        pass

def sync_agent_memory():
    """Syncs local files in MEMORY_DIR with the ChromaDB collection."""
    import glob
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.vectorstores import Chroma
    from langchain_core.documents import Document

    try:
        embeddings = OpenAIEmbeddings(
            base_url="https://aicredits.in/v1",
            openai_api_key=aicredits_key,
            model="text-embedding-3-small"
        )
        
        vector_store = Chroma(
            persist_directory=DB_DIR,
            embedding_function=embeddings,
            collection_name="agent_long_term_memory"
        )
        
        # Scan folder for allowed extensions
        allowed_extensions = ["*.txt", "*.md", "*.py", "*.json"]
        files = []
        for ext in allowed_extensions:
            files.extend(glob.glob(os.path.join(MEMORY_DIR, "**", ext), recursive=True))
            
        if not files:
            return vector_store
            
        documents = []
        for filepath in files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if not content:
                    continue
                filename = os.path.relpath(filepath, MEMORY_DIR)
                mtime = os.path.getmtime(filepath)
                documents.append(Document(
                    page_content=content,
                    metadata={"source": filename, "mtime": mtime}
                ))
            except Exception as e:
                print(f"Error reading memory file {filepath}: {e}")
                
        if not documents:
            return vector_store
            
        # Perform Sync
        current_data = vector_store.get()
        current_sources = {}
        if current_data and "metadatas" in current_data and "ids" in current_data:
            for idx, meta in enumerate(current_data["metadatas"]):
                doc_id = current_data["ids"][idx]
                source = meta.get("source")
                mtime = meta.get("mtime", 0.0)
                if source:
                    current_sources[source] = {"id": doc_id, "mtime": mtime}
                    
        to_add = []
        to_delete_ids = []
        indexed_sources = set()
        
        for doc in documents:
            source = doc.metadata["source"]
            indexed_sources.add(source)
            if source in current_sources:
                if abs(doc.metadata["mtime"] - current_sources[source]["mtime"]) > 0.1:
                    to_delete_ids.append(current_sources[source]["id"])
                    to_add.append(doc)
            else:
                to_add.append(doc)
                
        for source, info in current_sources.items():
            if source not in indexed_sources:
                to_delete_ids.append(info["id"])
                
        if to_delete_ids:
            vector_store.delete(ids=to_delete_ids)
        if to_add:
            vector_store.add_documents(to_add)
            
        print(f"Synced Memory: Added/Updated {len(to_add)} documents, Deleted {len(to_delete_ids)} documents.")
    except Exception as e:
        print(f"Error syncing memory: {e}")

def retrieve_relevant_memories(query: str, limit: int = 3) -> str:
    """Queries ChromaDB to retrieve relevant memory context."""
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.vectorstores import Chroma
    
    try:
        embeddings = OpenAIEmbeddings(
            base_url="https://aicredits.in/v1",
            openai_api_key=aicredits_key,
            model="text-embedding-3-small"
        )
        vector_store = Chroma(
            persist_directory=DB_DIR,
            embedding_function=embeddings,
            collection_name="agent_long_term_memory"
        )
        
        # Check if DB has any documents
        db_data = vector_store.get()
        if not db_data or not db_data.get("ids"):
            return ""
            
        results = vector_store.similarity_search(query, k=limit)
        formatted_memories = []
        for doc in results:
            filename = doc.metadata.get("source", "Unknown")
            content = doc.page_content
            formatted_memories.append(
                f"<memory_file name=\"{filename}\">\n"
                f"{content}\n"
                f"</memory_file>"
            )
            
        if formatted_memories:
            return (
                "<retrieved_long_term_memory>\n"
                "The following guidelines, custom scripts, or past summaries were found in your long-term memory "
                "and are relevant to the user's current request. Use them to guide your plan and writing phase:\n\n"
                + "\n\n".join(formatted_memories) + "\n"
                "</retrieved_long_term_memory>"
            )
    except Exception as e:
        print(f"Error querying memory: {e}")
    return ""


# ---------------------------------------------------------------------------
# opened_files tracks PID (or "external") per absolute path so close_file
# only ever targets a process THIS agent started - never a window title.
# ---------------------------------------------------------------------------
opened_files: dict[str, int | str] = {}

def _search_files(filename: str) -> list[str]:
    """Helper to search for files recursively under SANDBOX_ROOT using native Python.

    Returns:
        List of absolute paths matching the search criteria.
    """
    search_name = os.path.basename(filename)
    windows_paths = []
    
    import fnmatch
    for root, dirs, files in os.walk(SANDBOX_ROOT):
        for name in files:
            if fnmatch.fnmatch(name, search_name):
                windows_paths.append(os.path.join(root, name))
                
    return windows_paths


@tool
def search_file(filename: str) -> str:
    """Search for a file (within SANDBOX_ROOT) using cmd.exe and return the directory path where it is located.

    Args:
        filename: Name or wildcard pattern of the file to search for.
    """
    try:
        paths = _search_files(filename)
        if not paths:
            return f"No files matching '{filename}' were found in '{SANDBOX_ROOT}'."

        # Extract parent directories and deduplicate them
        unique_dirs = sorted(list(set(os.path.dirname(p) for p in paths)))

        if len(unique_dirs) == 1:
            return unique_dirs[0]
        else:
            return "\n".join(unique_dirs)

    except subprocess.TimeoutExpired:
        return f"Search timed out after 15 seconds. Please search for a more specific filename/pattern."
    except Exception as e:
        return f"An error occurred while searching: {str(e)}"


@tool
def open_file(filename: str) -> str:
    """Open a file with its default application (or Notepad for .txt files).
    If the file is not found directly, it searches for it recursively within SANDBOX_ROOT.
    Tracks the resulting process by PID so it can be closed safely later.

    Args:
        filename: Path, name, or pattern of the file to open.
    """
    abs_path = os.path.abspath(filename)

    # If the file does not exist directly, attempt to search for it using cmd.exe
    if not os.path.exists(abs_path):
        try:
            paths = _search_files(filename)
            if len(paths) == 1:
                abs_path = paths[0]
            elif len(paths) > 1:
                paths_str = "\n".join(f"- {p}" for p in paths)
                return f"Multiple matches found for '{filename}'. Please be more specific:\n{paths_str}"
            else:
                return f"Error: '{filename}' does not exist, and no search matches were found in '{SANDBOX_ROOT}'."
        except subprocess.TimeoutExpired:
            return f"Search timed out after 15 seconds. Please search for a more specific filename/pattern."
        except Exception as e:
            return f"Error: '{filename}' does not exist, and search failed: {e}"

    key = abs_path.lower()
    if key in opened_files:
        return f"'{abs_path}' is already recorded as open (PID/state: {opened_files[key]})."

    try:
        if abs_path.lower().endswith(".txt"):
            proc = subprocess.Popen(["notepad.exe", abs_path])
            opened_files[key] = proc.pid
            return f"Opened '{abs_path}' with Notepad (PID: {proc.pid})."
        else:
            os.startfile(abs_path)  # noqa: S606 - intentional, OS-level open
            opened_files[key] = "external"
            return (
                f"Requested the OS to open '{abs_path}' with its default app. "
                "Note: this agent cannot track or close externally-launched "
                "processes by PID, only by best-effort process-name matching."
            )
    except Exception as e:
        return f"Error opening '{abs_path}': {e}"


@tool
def close_file(filename: str) -> str:
    """Close a file previously opened by open_file, using the tracked PID.
    Never closes windows by title matching, to avoid killing the wrong process.

    Args:
        filename: Path or name of the file to close.
    """
    abs_path = os.path.abspath(filename)
    key = abs_path.lower()

    if key not in opened_files:
        return (
            f"'{filename}' was not opened by this agent in this session, "
            "so it cannot be safely closed (no tracked PID)."
        )

    entry = opened_files[key]

    if entry == "external":
        del opened_files[key]
        return (
            f"'{filename}' was opened externally via the OS default handler; "
            "this agent has no PID for it and will not attempt to kill it. "
            "Removed from tracking."
        )

    pid = entry
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        del opened_files[key]
        return f"Closed '{filename}' (PID {pid})."
    except psutil.NoSuchProcess:
        del opened_files[key]
        return f"Process for '{filename}' (PID {pid}) was already gone."
    except Exception as e:
        return f"Error closing '{filename}' (PID {pid}): {e}"

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.1

@tool
def computer_move_mouse(x: int, y: int, duration: float = 0.2) -> str:
    """Move the mouse to the absolute coordinates (x, y) on the screen."""
    try:
        pyautogui.moveTo(x, y, duration=duration)
        return f"Moved mouse to ({x}, {y})."
    except Exception as e:
        return f"Error moving mouse: {e}"

@tool
def computer_click(button: str = "left", clicks: int = 1) -> str:
    """Click the mouse at its current location."""
    try:
        pyautogui.click(button=button, clicks=clicks)
        return f"Clicked {button} button {clicks} time(s)."
    except Exception as e:
        return f"Error clicking mouse: {e}"

@tool
def computer_type(text: str, interval: float = 0.05) -> str:
    """Type text on the keyboard."""
    try:
        pyautogui.write(text, interval=interval)
        return f"Typed text successfully."
    except Exception as e:
        return f"Error typing: {e}"



import hashlib
from PIL import ImageDraw, ImageFont, Image
import json
import win32gui
import win32process
import threading
import numpy as np

# Removed unused ScreenWatcher background thread which consumed massive CPU by taking screenshots every 400ms

last_screen_hash = ""
cached_ui_tree = []
cached_annotated_b64 = ""
current_window_offset = (0, 0)

@tool
def observe_screen() -> str:
    """Captures the active window and extracts UI elements, returning them as a multimodal block.
    Uses Set-of-Marks to draw bounding boxes and numeric IDs on the screenshot.
    """
    global last_screen_hash, cached_ui_tree, cached_annotated_b64, current_window_offset
    
    time.sleep(0.15)
    
    hwnd = win32gui.GetForegroundWindow()
    class_name = win32gui.GetClassName(hwnd) if hwnd else ""
    rect = win32gui.GetWindowRect(hwnd) if hwnd else None
    
    try:
        if rect and rect[2] - rect[0] > 0 and rect[3] - rect[1] > 0:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(rect[0], rect[1], rect[2], rect[3]), all_screens=True)
            current_window_offset = (rect[0], rect[1])
        else:
            img = pyautogui.screenshot()
            current_window_offset = (0, 0)
        img_hash = hashlib.md5(img.tobytes()).hexdigest()
        if img_hash == last_screen_hash and cached_annotated_b64:
            return _build_observe_result(cached_ui_tree, cached_annotated_b64, failed=(img_hash == "screenshot_failed"))
        last_screen_hash = img_hash
    except Exception as e:
        from PIL import Image
        print(f"Warning: screen grab failed ({e}). Creating black fallback image.")
        img = Image.new("RGB", (1024, 768), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), f"Screen Grab Failed: {e}", fill=(255, 0, 0))
        last_screen_hash = "screenshot_failed"
        current_window_offset = (0, 0)
    game_classes = ["UnityWndClass", "UnrealWindow", "Chrome_RenderWidgetHostHWND"]
    is_game = any(gc in class_name for gc in game_classes)
    
    elements = []
    if not is_game and hwnd:
        try:
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            window = desktop.window(handle=hwnd)
            window.wait('ready', timeout=2)
            
            def walk_elements(ctrl, depth=0, max_depth=3):
                if depth > max_depth or len(elements) >= 80:
                    return
                try:
                    rect = ctrl.rectangle()
                    if rect and rect.width() > 0 and rect.height() > 0:
                        name = ctrl.element_info.name.strip() if ctrl.element_info.name else ""
                        control_type = ctrl.element_info.control_type.strip() if ctrl.element_info.control_type else ""
                        
                        keep = True
                        if not name and control_type not in ["Edit", "Document", "Button", "CheckBox", "ComboBox", "RadioButton", "Hyperlink", "MenuItem", "TabItem"]:
                            keep = False
                        if keep:
                            elements.append({
                                "id": len(elements) + 1,
                                "type": control_type,
                                "name": name,
                                "x": rect.left + (rect.width() // 2),
                                "y": rect.top + (rect.height() // 2),
                                "rect": (rect.left, rect.top, rect.right, rect.bottom)
                            })
                except Exception: pass
                try:
                    for child in ctrl.children():
                        walk_elements(child, depth + 1, max_depth)
                except Exception: pass
            
            walk_elements(window)
        except Exception:
            pass

    draw = ImageDraw.Draw(img, "RGBA")
    for el in elements:
        r = el["rect"]
        ox, oy = current_window_offset
        rx, ry, rw, rh = r[0] - ox, r[1] - oy, r[2] - ox, r[3] - oy
        draw.rectangle((rx, ry, rw, rh), outline=(255, 0, 0, 200), width=2)
        text = str(el["id"])
        draw.rectangle((rx, ry, rx+20, ry+15), fill=(255, 0, 0, 200))
        draw.text((rx+2, ry+2), text, fill=(255, 255, 255))
    
    img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=50)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    
    cached_ui_tree = elements
    cached_annotated_b64 = b64
    
    return _build_observe_result(elements, b64, failed=(last_screen_hash == "screenshot_failed"))

def _build_observe_result(elements, b64, failed=False):
    if failed:
        tree_text = "CRITICAL ERROR: Screen grab failed. Do not attempt to click coordinates or elements. You must use OS keyboard navigation like win+r, type_text, or abort.\n"
    else:
        tree_text = "UI Elements (Set-of-Marks):\n"
        for el in elements:
            tree_text += f"[{el['id']}] {el['type']} '{el['name']}' at ({el['x']}, {el['y']})\n"
        if not elements:
            tree_text += "No accessible UI tree found (could be a game, canvas, or unsupported app). Rely solely on visual coordinates.\n"
        
    return [
        {"type": "text", "text": tree_text},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
    ]

def click_element(element_id: int) -> str:
    """Clicks a specific element by its ID shown in the annotated screenshot."""
    global cached_ui_tree
    for el in cached_ui_tree:
        if el["id"] == element_id:
            pyautogui.click(el["x"], el["y"])
            return f"Clicked element {element_id} ({el['name']})"
    return f"Element {element_id} not found."

def click_coordinate(x: int, y: int) -> str:
    """Clicks an exact pixel coordinate on the screen. Use this if the element has no ID."""
    global current_window_offset
    gx = x + current_window_offset[0]
    gy = y + current_window_offset[1]
    pyautogui.click(gx, gy)
    return f"Clicked coordinate ({gx}, {gy}) (window-relative: {x}, {y})"

def type_text(text: str) -> str:
    """Types text directly via keyboard."""
    try:
        pyautogui.write(text, interval=0.0)
        return f"Typed: {text}"
    except Exception as e:
        return f"Error typing text: {e}"

def press_key(key: str) -> str:
    """Presses a single keyboard key (e.g., 'enter', 'tab', 'esc')."""
    pyautogui.press(key)
    return f"Pressed key: {key}"

def wait(ms: int) -> str:
    """Waits for the specified number of milliseconds."""
    time.sleep(ms / 1000.0)
    return f"Waited {ms}ms"

tool_batch_approval_event = __import__('threading').Event()
tool_batch_approval_result = {"approved": False, "feedback": ""}
tool_batch_waiting = False

current_gui_model = "deepseek/deepseek-r1"

import hashlib
import json

@tool
def run_command(command: str) -> str:
    """Executes a command on the host Windows machine (via cmd.exe) and returns the output.
    Use this for launching applications, running scripts, opening websites, or basic OS operations.
    Examples:
      - Launch Chrome: run_command("start chrome")
      - Launch Chrome with a URL: run_command("start chrome https://youtube.com")
      - List files: run_command("dir")
    """
    try:
        # Launching processes with 'start' in cmd.exe sometimes returns immediately, 
        # which is desired for opening GUI applications so we don't block the agent.
        result = subprocess.run(
            ["cmd.exe", "/c", command],
            capture_output=True,
            text=True,
            timeout=15,
            shell=True
        )
        output = result.stdout
        if result.stderr:
            output += f"\nStderr:\n{result.stderr}"
        return output or "Command executed successfully (no stdout/stderr returned)."
    except Exception as e:
        return f"Error executing command: {e}"

@tool
def read_file(filename: str) -> str:
    """Reads and returns the text content of a file.
    filename: Absolute path or relative path under SANDBOX_ROOT.
    """
    try:
        abs_path = os.path.abspath(filename)
        if not abs_path.startswith(SANDBOX_ROOT):
            return f"Error: Cannot read '{abs_path}' because it is outside the workspace root."
        if not os.path.exists(abs_path):
            return f"Error: File '{abs_path}' does not exist."
        
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

@tool
def write_file(filename: str, content: str) -> str:
    """Writes content to a file (creates it if it doesn't exist, overwrites if it does).
    filename: Absolute path or relative path under SANDBOX_ROOT.
    content: The text content to write.
    """
    try:
        abs_path = os.path.abspath(filename)
        if not abs_path.startswith(SANDBOX_ROOT):
            return f"Error: Cannot write to '{abs_path}' because it is outside the workspace root."
        
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} characters to '{abs_path}'."
    except Exception as e:
        return f"Error writing file: {e}"

@tool
def list_files(directory: str = ".") -> str:
    """Lists all files and directories in the specified directory.
    directory: Directory path relative to workspace or absolute.
    """
    try:
        abs_path = os.path.abspath(directory)
        if not abs_path.startswith(SANDBOX_ROOT):
            return f"Error: Cannot list '{abs_path}' because it is outside the workspace root."
        if not os.path.exists(abs_path):
            return f"Error: Directory '{abs_path}' does not exist."
        
        items = os.listdir(abs_path)
        result = []
        for item in items:
            full = os.path.join(abs_path, item)
            suffix = "/" if os.path.isdir(full) else ""
            result.append(f"{item}{suffix}")
        return "\n".join(result) if result else "(Empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"

class LoopGuard:
    def __init__(self):
        self.current_hash = None
        self.current_streak = 0
        self.streak_warn_issued = False
        self.streak_halt_issued = False
        self.streak_abort_issued = False

    def _normalize_args(self, args):
        if not args:
            return {}
        if isinstance(args, dict):
            return {k: self._normalize_args(v) for k, v in sorted(args.items())}
        if isinstance(args, list):
            return [self._normalize_args(v) for v in args]
        return args

    def record_turn(self, tool_calls):
        if not tool_calls:
            return {"action": "none"}
        
        hashes = []
        for tc in tool_calls:
            norm = self._normalize_args(tc.get("args", {}))
            data = f"{tc['name']}:{json.dumps(norm, sort_keys=True)}"
            hashes.append(hashlib.md5(data.encode()).hexdigest())
        group_hash = hashlib.md5("".join(hashes).encode()).hexdigest()
        
        if group_hash == self.current_hash:
            self.current_streak += 1
        else:
            self.current_hash = group_hash
            self.current_streak = 1
            self.streak_warn_issued = False
            self.streak_halt_issued = False
            self.streak_abort_issued = False
            
        count = self.current_streak
        
        if count >= 8 and not self.streak_abort_issued:
            self.streak_abort_issued = True
            return {"action": "abort", "count": count}
        if count >= 5 and not self.streak_halt_issued:
            self.streak_halt_issued = True
            return {"action": "halt", "count": count}
        if count >= 3 and not self.streak_warn_issued:
            self.streak_warn_issued = True
            return {"action": "warn", "count": count}
            
        return {"action": "none"}

def _run_subagent_task(task_description: str) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(
        base_url="https://aicredits.in/v1",
        api_key=aicredits_key,
        model="anthropic/claude-3.5-sonnet", # Better model for reasoning
        temperature=0.0
    )
    messages = [
        SystemMessage(content="You are a focused sub-agent. Complete the task below and return ONLY the result. Do not ask questions."),
        HumanMessage(content=f"Task: {task_description}")
    ]
    try:
        # We can bind the standard coding tools here if we want, but for now we'll let it use the basic tools or just think.
        from langchain_core.tools import StructuredTool
        tools = [
            StructuredTool.from_function(list_files),
            StructuredTool.from_function(read_file),
            StructuredTool.from_function(write_file),
            StructuredTool.from_function(run_command)
        ] + active_mcp_langchain_tools
        llm_with_tools = llm.bind_tools(tools)
        # We run a small local loop for the subagent
        for _ in range(5):
            res = llm_with_tools.invoke(messages)
            messages.append(res)
            if not res.tool_calls:
                return res.content
            for tc in res.tool_calls:
                tool_name = tc["name"]
                args = tc["args"]
                try:
                    target_tool = next((t for t in tools if t.name == tool_name), None)
                    if target_tool:
                        output = target_tool.invoke(args)
                    else:
                        output = "Unknown tool"
                except Exception as e:
                    output = str(e)
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))
        return "Subagent stopped after max turns without finishing."
    except Exception as e:
        return f"Subagent error: {e}"

@tool
def spawn_subagent(task_description: str, timeout_seconds: int = 120) -> str:
    """Spawns a child agent to complete a focused sub-task in its own context.
    The child inherits basic coding tools but not your conversation history.
    Use for heavy coding or complex reasoning tasks that benefit from isolated context."""
    return _run_subagent_task(task_description)

@tool
def ask_llm_and_execute(task_description: str) -> str:
    """Delegates a complex GUI task to DeepSeek-R1 via a safe tool-calling loop.
    DeepSeek will automatically observe the screen, click, type, and press keys.
    """
    global current_gui_model
    from langchain_core.tools import StructuredTool
    
    tools = [
        StructuredTool.from_function(click_element),
        StructuredTool.from_function(click_coordinate),
        StructuredTool.from_function(type_text),
        StructuredTool.from_function(press_key),
        StructuredTool.from_function(wait)
    ]
    
    models_to_try = [
        "deepseek/deepseek-r1",
        "deepseek/deepseek-r1-distill-llama-70b",
        "deepseek/deepseek-r1-distill-qwen-32b",
        "deepseek/deepseek-latest",
        "deepseek/deepseek-chat"
    ]
    
    if current_gui_model in models_to_try:
        models_to_try.remove(current_gui_model)
    models_to_try.insert(0, current_gui_model)
    
    system_prompt = (
        "You are DeepSeek-R1, a safe GUI automation assistant.\n"
        "You have access to tools: click_element, click_coordinate, type_text, press_key, wait.\n"
        "1. Observe the screen context provided.\n"
        "2. To click an element with a red numeric label, use `click_element(id)`.\n"
        "3. Output a sequence of tool calls in one go to save latency.\n"
        "4. IF you receive a 'Screen grab failed' error, DO NOT try to click coordinates. Instead, use keyboard tools (like type_text or press_key) to recover, or exit.\n"
        "5. Output your reasoning in <think> tags, then strictly output your tool calls.\n"
    )
    
    observation = observe_screen.invoke({})
    
    # Strip image parts because deepseek-r1 is a text-only model and will 404 on image inputs
    text_observation = ""
    for part in observation:
        if part["type"] == "text":
            text_observation += part["text"]
            
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Task: {task_description}"},
        {"role": "user", "content": text_observation}
    ]
    
    max_turns = 8
    initial_approval_done = False
    all_results = []
    
    loop_guard = LoopGuard()
    
    for turn in range(max_turns):
        try:
            # Dynamic Context Compaction
            # Ensure we don't sever AIMessage tool_calls from ToolMessage results
            if len(messages) > 20:
                # Keep first 3 (system, task, initial observation)
                safe_messages = messages[:3]
                # Slice backwards to find a safe boundary (HumanMessage or AIMessage without tool calls)
                slice_idx = len(messages) - 15
                while slice_idx < len(messages):
                    msg = messages[slice_idx]
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        break
                    if hasattr(msg, "type") and msg.type == "human":
                        break
                    slice_idx += 1
                safe_messages.extend(messages[slice_idx:])
                messages = safe_messages

            response = None
            last_err = None
            for model_name in models_to_try:
                try:
                    llm = ChatOpenAI(
                        base_url="https://aicredits.in/v1",
                        api_key=aicredits_key,
                        model=model_name,
                        temperature=0.0
                    )
                    llm_with_tools = llm.bind_tools(tools)
                    response = llm_with_tools.invoke(messages)
                    current_gui_model = model_name
                    if current_gui_model in models_to_try:
                        models_to_try.remove(current_gui_model)
                    models_to_try.insert(0, current_gui_model)
                    break
                except Exception as e:
                    last_err = e
                    print(f"Fallback: Model {model_name} failed with: {e}. Trying next...")
            
            if response is None:
                raise RuntimeError(f"All DeepSeek-R1 models failed. Last error: {last_err}")
                
            if not response.tool_calls:
                break
                
            guard_decision = loop_guard.record_turn(response.tool_calls)
            
            if guard_decision["action"] == "abort":
                all_results.append(f"Loop Guard: Identical tool-call group repeated {guard_decision['count']} times. Aborting batch.")
                break
            
            messages.append(response)

            if guard_decision["action"] == "halt":
                messages.append({"role": "user", "content": f"[Loop Guard · STOP] Identical tool-call group has now repeated {guard_decision['count']} times — this is a loop. **STOP all tool calls immediately. You must output the final conclusion in plain text based on the information you have already collected.**"})
                continue
            elif guard_decision["action"] == "warn":
                messages.append({"role": "user", "content": f"[Loop Guard · Warning] You have executed the same group of tool calls {guard_decision['count']} times in a row. Please stop the repetitive calls and change your strategy (use different tools / adjust parameters / break into subtasks)."})
                continue
            
            # ---------------------------------------------------------
            # HARDENING: Ask UI for batch approval before executing
            # ---------------------------------------------------------
            if not initial_approval_done:
                plan_text = "<plan>\n# DeepSeek Action Batch\n<tasks>\n"
                for tc in response.tool_calls:
                    plan_text += f"- [ ] {tc['name']}({tc['args']})\n"
                plan_text += "</tasks>\n</plan>"
                
                try:
                    import webview
                    import json
                    webview.windows[0].evaluate_js(f"window.appendFinalResponse({json.dumps(plan_text)})")
                    
                    global tool_batch_approval_event, tool_batch_approval_result, tool_batch_waiting
                    tool_batch_approval_event.clear()
                    tool_batch_waiting = True
                    tool_batch_approval_event.wait()
                    tool_batch_waiting = False
                    
                    if not tool_batch_approval_result["approved"]:
                        return f"User rejected the actions with feedback: {tool_batch_approval_result['feedback']}"
                    initial_approval_done = True
                except Exception as e:
                    tool_batch_waiting = False
                    print("Could not prompt UI for approval, proceeding natively. Error:", e)
                    initial_approval_done = True
            
            # Execute tools
            batch_aborted = False
            for tc in response.tool_calls:
                tool_name = tc["name"]
                args = tc["args"]
                res = f"Unknown tool {tool_name}"
                try:
                    if tool_name == "click_element": res = click_element(**args)
                    elif tool_name == "click_coordinate": res = click_coordinate(**args)
                    elif tool_name == "type_text": res = type_text(**args)
                    elif tool_name == "press_key": res = press_key(**args)
                    elif tool_name == "wait": res = wait(**args)
                except Exception as e:
                    res = f"Execution Error: {str(e)}"
                
                all_results.append(f"{tool_name}({args}) -> {res}")
                
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(content=res, tool_call_id=tc["id"]))
                
                time.sleep(0.2)
                
            # Inject fresh observation so DeepSeek can verify success or handle obstacles (like profile selectors)
            new_obs = observe_screen.invoke({})
            text_obs = "".join(p["text"] for p in new_obs if p["type"] == "text")
            messages.append({"role": "user", "content": f"Batch completed. Current screen state:\n{text_obs}\nExamine the screen. If the ultimate task '{task_description}' is achieved, output NO tools. If you are stuck on an obstacle or the task is incomplete, issue tools to bypass it."})
                
        except Exception as e:
            return f"Error running DeepSeek tool loop: {e}"

    final_res = "\n".join(all_results)
    if not final_res:
        return "Task completed without tool executions."
        
    # MEMORIZE TASK FOR REPEATS
    memory_filename = f"task_routine_{hashlib.md5(task_description.encode()).hexdigest()[:8]}.txt"
    memory_content = f"Task: {task_description}\nSuccessful Routine:\n{final_res}\n"
    save_path = os.path.join(MEMORY_DIR, memory_filename)
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(memory_content)
        sync_agent_memory() 
    except: pass
        
    return f"Executed tools successfully:\n{final_res}\n(Routine saved to memory: {memory_filename})"


@tool("take_screenshot")
def take_screenshot() -> str:
    """Capture a screenshot of the current screen to get visual feedback.
    Saves the screenshot locally to 'screenshot.png'.
    """
    try:
        time.sleep(0.15)
        img = pyautogui.screenshot()
        img.save("screenshot.png")
        return "Screenshot captured and saved to screenshot.png."
    except Exception as e:
        return f"Screenshot capture failed: {e}"

@tool("focus_window")
def focus_window(window_title: str) -> str:
    """Focuses an application window by its title (partial match).
    Use this BEFORE sending any keyboard or mouse commands to ensure they don't leak into the terminal.
    """
    import win32gui, win32con
    import pyautogui
    
    def callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if window_title.lower() in title.lower():
                windows.append(hwnd)
        return True
    
    windows = []
    win32gui.EnumWindows(callback, windows)
    if not windows:
        return f"No window found matching '{window_title}'"
    
    hwnd = windows[0]
    try:
        # Press Alt to bypass Windows foreground lock
        pyautogui.press('alt')
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return f"Successfully focused window: {win32gui.GetWindowText(hwnd)}"
    except Exception as e:
        return f"Failed to focus window '{window_title}': {e}"

@tool("save_to_memory")
def save_to_memory(filename: str, content: str) -> str:
    """Saves high-level text instructions, custom scripts, workflow guidelines, or task summaries to the agent's long term memory.
    filename: The name of the file to save (e.g., 'open_chrome_macro.py', 'start_menu_workaround.txt').
    content: The text content to write inside the file.
    """
    import os
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(MEMORY_DIR, safe_filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        sync_agent_memory()
        return f"Successfully saved '{safe_filename}' to long term memory and indexed it."
    except Exception as e:
        return f"Failed to save to memory: {e}"

@tool("create_skill")
def create_skill(name: str, python_code: str) -> str:
    """
    Creates a new reusable skill (macro) for the agent. 
    The skill will be written to the skills directory and loaded dynamically on the next agent start.
    Provide the EXACT Python code. The code MUST import `@tool` from `langchain.tools` and define a function decorated with `@tool` containing a docstring.
    
    Example python_code:
    from langchain.tools import tool
    @tool
    def ping_google() -> str:
        '''Pings google.com to test internet connection.'''
        import subprocess
        result = subprocess.run(['ping', 'google.com'], capture_output=True, text=True)
        return result.stdout
    """
    import os
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    if not os.path.exists(skills_dir):
        os.makedirs(skills_dir)
    file_path = os.path.join(skills_dir, f"{name}.py")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(python_code)
        return f"Successfully created skill '{name}' at {file_path}. It will be available upon the next agent restart."
    except Exception as e:
        return f"Failed to create skill: {e}"

@tool("agent_sleep")
def agent_sleep(seconds: float) -> str:
    """Wait or sleep for a specified number of seconds."""
    import time
    time.sleep(seconds)
    return f"Waited for {seconds} seconds."
def setup_agent(memory=None):
    print(f"Agent Programming Initialized. Full computer access granted.")
    print("Syncing agent long-term memory...")
    try:
        sync_agent_memory()
    except Exception as e:
        print(f"Failed to sync long term memory: {e}")


    # from langchain_community.tools import WikipediaQueryRun
    # from langchain_community.utilities import WikipediaAPIWrapper
    from duckduckgo_search import DDGS
    
    @tool("web_search")
    def web_search(query: str) -> str:
        """Search the web for real-time information."""
        try:
            results = DDGS().text(query, max_results=5)
            if not results:
                return "No results found."
            return "\n\n".join(f"Title: {r['title']}\nSnippet: {r['body']}\nURL: {r['href']}" for r in results)
        except Exception as e:
            return f"Search failed: {e}"

    # wiki_search = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

    skills_mgr = SkillsManager(os.path.join(os.path.dirname(__file__), "skills"))
    dynamic_tools = skills_mgr.load_skills()

    # Load MCP Servers
    mcp_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp_config.json")
    if os.path.exists(mcp_config_path):
        try:
            with open(mcp_config_path, "r", encoding="utf-8") as f:
                mcp_config = json.load(f)
            servers = mcp_config.get("servers", {})
            for name, cfg in servers.items():
                if cfg.get("enabled", False):
                    cmd = cfg.get("command")
                    args = cfg.get("args", [])
                    env = cfg.get("env")
                    mcp_cwd = os.path.dirname(mcp_config_path)
                    client = McpClient(name, cmd, args, env, cwd=mcp_cwd)
                    print(f"Starting MCP server: {name} ({cmd} {' '.join(args)})")
                    if client.start():
                        active_mcp_servers.append(client)
                        for t in client.tools:
                            lc_tool = make_mcp_langchain_tool(client, t)
                            active_mcp_langchain_tools.append(lc_tool)
                            print(f"  Loaded MCP Tool: {lc_tool.name}")
                    else:
                        print(f"  Failed to start MCP Server: {name}")
        except Exception as e:
            print(f"Error loading MCP servers: {e}")

    # memory is injected from main.py as AsyncSqliteSaver

    try:
        from agent.playwright_tools import get_playwright_tools
        pw_tools = get_playwright_tools()
    except Exception as e:
        print(f"Playwright tools not loaded: {e}")
        pw_tools = []

    LocalAgent = create_deep_agent(
        model=AgentModel,
        backend=LocalShellBackend(root_dir=None, virtual_mode=False),
        tools=[open_file, close_file, search_file, run_command, read_file, write_file, list_files, save_to_memory, web_search, computer_move_mouse, computer_click, computer_type, create_skill, agent_sleep] + active_mcp_langchain_tools + dynamic_tools + pw_tools,
        middleware=[PatchToolMessagesMiddleware(), LoopGuardMiddleware()],
        checkpointer=memory,
        system_prompt=(
            "You are a highly advanced local coordinator agent controlling the system via tools.\n\n"
            "CRITICAL BEHAVIORAL RULES:\n"
            "1. CHAT FIRST: By default, respond to the user in plain text within the conversation. Do NOT create, write, or edit files unless the user explicitly asks you to.\n"
            "2. When a request is actionable, proceed immediately with reasonable assumptions. If you need clarification, ask briefly in plain text.\n"
            "3. When given a task, START DOING IT. Do not restate the task, do not list what you will do, do not ask for confirmation. Just execute.\n"
            "4. NEVER hallucinate UI element IDs, selectors, or coordinates.\n"
            "5. Execute one browser action per turn. DO NOT queue multiple chrome actions in the same response without checking the result.\n\n"
            "<tool_behavior>\n"
            "Tool routing:\n"
            "- If user explicitly asks to use Chrome/browser/web navigation, prioritize Playwright and MCP Chrome tools.\n"
            "- Use `run_command` to execute OS level operations, start applications, or run bash scripts.\n"
            "- Use `computer_move_mouse`/`computer_click` ONLY as a last resort when programmatic or native tools fail.\n"
            "- If asked to create a macro or skill, use `create_skill` to write it. Remind the user they need to restart for it to load.\n"
            "- If asked to wait or sleep, use the `agent_sleep` tool.\n"
            "</tool_behavior>\n\n"
            "<long_term_memory>\n"
            "- Check any injected `<retrieved_long_term_memory>` context before starting any plan to see if a similar task has already been solved or if there are custom rules to follow.\n"
            "- Once a major task is successfully completed, compile a summary and save it to the memory database using `save_to_memory`.\n"
            "</long_term_memory>\n"
        ),
    )
    return LocalAgent

def main():
    LocalAgent = setup_agent()
    messages = []
    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break

            try:
                # Intent-Based Routing: Bypass agent for greetings
                greetings = ["hi", "hello", "hey", "greetings", "yo", "morning", "afternoon", "evening", "who are you", "what's up", "how are you"]
                lower_input = user_input.lower().strip()
                is_greeting = any(lower_input.startswith(g) or lower_input == g for g in greetings)
                
                if is_greeting:
                    fast_resp = AgentModel.invoke([
                        SystemMessage(content="You are a friendly AI assistant. Keep it brief and conversational."),
                        HumanMessage(content=user_input)
                    ])
                    print(f"Agent: {fast_resp.content}\n")
                    continue
                    
                # Query relevant memories for the current request
                memories_context = retrieve_relevant_memories(user_input)
                if memories_context:
                    messages.append(SystemMessage(content=memories_context))

                user_message = HumanMessage(content=user_input)
                messages.append(user_message)
                
                # Keep messages bounded to prevent context overflow, but do it safely.
                # Slicing arbitrarily can orphan ToolMessages from their preceding AIMessage(tool_calls),
                # which causes OpenAI 400 Bad Request errors. We search for the closest HumanMessage boundary to slice at.
                if len(messages) > 30:
                    slice_idx = len(messages) - 30
                    while slice_idx < len(messages):
                        if isinstance(messages[slice_idx], HumanMessage):
                            break
                        slice_idx += 1
                    if slice_idx < len(messages):
                        messages = messages[slice_idx:]
                    else:
                        messages = messages[-30:]
                        
                response = LocalAgent.invoke({"messages": messages}) # use agent for LLM
                if response.get("messages"):
                    messages = response["messages"]
                    last_message = messages[-1]
                    
                    if isinstance(last_message.content, list):
                        text_parts = [part["text"] for part in last_message.content if isinstance(part, dict) and "text" in part]
                        if text_parts:
                            print(f"Agent: {''.join(text_parts)}\n")
                        else:
                            print("Agent: [Tool action executed]\n")
                    else:
                        print(f"Agent: {last_message.content}\n")
                else:
                    print(f"Agent: {response}\n")
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"Error: {e}\n")
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        # Clean up any processes this agent spawned so nothing is orphaned.
        for path, entry in list(opened_files.items()):
            if isinstance(entry, int):
                try:
                    p = psutil.Process(entry)
                    p.terminate()
                    p.wait(timeout=2)
                except Exception:
                    pass
        opened_files.clear()


if __name__ == "__main__":
    main()