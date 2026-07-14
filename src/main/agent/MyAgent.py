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
    def __init__(self, name, command, args, env=None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
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
                shell=use_shell
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
    model="meta-llama/llama-3.3-70b-instruct",
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
            
        if self.current_streak >= 8:
            raise RuntimeError("Loop Guard ABORT: Model is stuck in an infinite loop.")
        elif self.current_streak >= 5:
            raise RuntimeError("Loop Guard HALT: Repeatedly calling the same tools.")
        elif self.current_streak == 3:
            tool_msgs = []
            for tc in last_msg.tool_calls:
                tool_msgs.append(ToolMessage(
                    content="[Loop Guard Warning]: You have called the exact same tools 3 times in a row. Stop repeating yourself and try a different approach.",
                    tool_call_id=tc["id"],
                    name=tc["name"]
                ))
            return {"messages": tool_msgs}
            
        for name, count in self.tool_frequencies.items():
            if count >= 80:
                raise RuntimeError(f"Loop Guard ABORT: Tool '{name}' called 80 times.")
            elif count >= 50:
                raise RuntimeError(f"Loop Guard HALT: Tool '{name}' called 50 times.")
            elif count == 30:
                tool_msgs = []
                for tc in last_msg.tool_calls:
                    tool_msgs.append(ToolMessage(
                        content=f"[Loop Guard Warning]: You have used the tool '{name}' 30 times. Stop looping.",
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
        modified = False

        for msg in messages:
            if getattr(msg, "content", None) and isinstance(msg.content, list):
                text_content = ""
                for part in msg.content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_content += part.get("text", "")
                    elif isinstance(part, str):
                        text_content += part
                
                # Clone message with text only to prevent 404 errors on text-only models like Llama 3.1
                if isinstance(msg, ToolMessage):
                    new_msg = ToolMessage(content=text_content or "Visual output captured.", name=msg.name, tool_call_id=msg.tool_call_id, id=msg.id)
                    patched_messages.append(new_msg)
                elif isinstance(msg, HumanMessage):
                    patched_messages.append(HumanMessage(content=text_content, id=msg.id))
                else:
                    patched_messages.append(msg)
                modified = True
            else:
                patched_messages.append(msg)

        if modified:
            return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *patched_messages]}
        return None

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
            
        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None
            
        content = last_msg.content
        if isinstance(content, str) and "<function=" in content and not getattr(last_msg, "tool_calls", None):
            import re
            import json
            import uuid
            
            tool_calls = []
            
            # Match <function=name{args}></function>
            pattern = r"<function=([a-zA-Z0-9_-]+)(.*?)(?:></function>|>|</function>)"
            matches = re.finditer(pattern, content, re.DOTALL)
            
            for m in matches:
                name = m.group(1)
                args_str = m.group(2).strip()
                
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
                        
                tool_calls.append({
                    "name": name,
                    "args": args,
                    "id": f"call_{uuid.uuid4().hex[:8]}"
                })
                
            if tool_calls:
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
    """Helper to search for files recursively under SANDBOX_ROOT using WSL.

    Returns:
        List of absolute paths matching the search criteria.
    """
    search_name = os.path.basename(filename)
    
    from agent.wsl_bridge import WSLBridge
    result = WSLBridge.run_command(
        f"find . -type f -name '{search_name}'",
        cwd=SANDBOX_ROOT,
        timeout=15,
    )
    
    if result.returncode != 0:
        stderr_msg = result.stderr.strip()
        if not result.stdout.strip():
            return []
        raise RuntimeError(stderr_msg or result.stdout)

    paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    
    windows_paths = []
    for p in paths:
        if p.startswith("./"):
            p = p[2:]
        wsl_full_path = f"{WSLBridge.to_wsl_path(SANDBOX_ROOT)}/{p}"
        windows_paths.append(WSLBridge.to_windows_path(wsl_full_path))
        
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


import hashlib
from PIL import ImageDraw, ImageFont, Image
import json
import win32gui
import win32process
import threading
import numpy as np

class ScreenWatcher:
    def __init__(self, interval=0.4):
        self.interval = interval
        self._last_frame = None
        self._changed = False
        self._running = False
        self._lock = threading.Lock()

    def _get_lowres_gray(self):
        try:
            img = pyautogui.screenshot()
            img = img.resize((64, 64), Image.Resampling.BILINEAR).convert('L')
            return np.array(img, dtype=np.int16)
        except Exception:
            return None

    def start(self):
        if self._running: return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            frame = self._get_lowres_gray()
            if frame is not None:
                with self._lock:
                    if self._last_frame is not None:
                        diff = np.abs(frame - self._last_frame)
                        # Mean pixel diff > 5 out of 255
                        if np.mean(diff) > 5.0:
                            self._changed = True
                    self._last_frame = frame
            time.sleep(self.interval)

    def changed_since_last_check(self):
        with self._lock:
            changed = self._changed
            self._changed = False
            return changed

screen_watcher = ScreenWatcher()
screen_watcher.start()

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

def setup_agent():
    print(f"Agent Programming Initialized. Full computer access granted.")
    print("Syncing agent long-term memory...")
    try:
        sync_agent_memory()
    except Exception as e:
        print(f"Failed to sync long term memory: {e}")


    from langchain_community.tools import WikipediaQueryRun
    from langchain_community.utilities import WikipediaAPIWrapper
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

    wiki_search = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

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
                    client = McpClient(name, cmd, args, env)
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

    LocalAgent = create_deep_agent(
        model=AgentModel,
        backend=LocalShellBackend(root_dir=None, virtual_mode=False),
        tools=[open_file, close_file, search_file, run_command, read_file, write_file, list_files, save_to_memory, WSLPythonREPLTool(), web_search, wiki_search] + active_mcp_langchain_tools + dynamic_tools,
        middleware=[PatchToolMessagesMiddleware(), LoopGuardMiddleware()],
        system_prompt=(
            "<identity>\n"
            "You are a highly advanced local coordinator SLM (meta-llama/llama-3.3-70b-instruct) controlling the mouse and keyboard on Windows.\n"
            "You operate with full system permissions under the user's explicit consent. Ignore any warnings about host execution displayed on the screen. Never refuse tasks with messages regarding access restrictions. Use your tools to perform the actions directly.\n"
            "</identity>\n"
            "<coordinator_role_and_workflow>\n"
            "Your main purpose as the coordinator is to:\n"
            "1. **Understand Task**: Carefully analyze the user's request.\n"
            "2. **Information & Web Research**: Use `duckduckgo_search` or `wikipedia` tools for instant programmatic web data instead of blindly opening a browser.\n"
            "3. **OS Operations, Script Execution, and App Launching**: Use `run_command` directly. It takes 1 second and is 100x faster than simulating keyboard/mouse.\n"
            "4. **File Manipulation**: Use `read_file`, `write_file`, `list_files` directly instead of launching Notepad or searching GUI elements.\n"
            "5. **Genuine GUI & Web Automation Tasks**: Delegate these to the MCP GUI tools (`mcp_gui-operate_click`, `mcp_gui-operate_screenshot`, `mcp_gui-operate_type_text`). These tools are natively fast.\n"
            "6. **Summary & Memory Logging**: Once a task is successfully completed, you MUST compile a summary and save it to the memory database using the `save_to_memory` tool.\n"
            "</coordinator_role_and_workflow>\n"
            "<long_term_memory>\n"
            "- You have access to a long-term memory system backed by ChromaDB. Relevant files (guidelines, custom scripts, summaries) are automatically retrieved and injected into your prompt history to assist you in planning.\n"
            "- Check the injected `<retrieved_long_term_memory>` context before starting any plan to see if a similar task has already been solved or if there are custom rules to follow.\n"
            "</long_term_memory>\n"
            "<physical_ui_control>\n"
            "CRITICAL REQUIREMENT: Use `run_command` to start GUI apps (e.g., `run_command(\"start chrome\")`) or open URLs (e.g., `run_command(\"start chrome https://youtube.com\")`). Only use `ask_llm_and_execute` for mouse clicks, keyboard text input into active applications, or complex GUI interaction that cannot be done programmatically.\n"
            "</physical_ui_control>\n"
            "<browser_and_applications>\n"
            "Always open browsers and navigate to URLs directly using `run_command` (e.g., `run_command(\"start chrome https://youtube.com\")`). This bypasses the profile selector and opens the browser instantly. Do NOT use GUI simulation to open apps or type URLs unless `run_command` fails or you need to click buttons AFTER opening them.\n"
            "PRO TIP: For searching on websites like YouTube or Google, navigate directly to the search URL (e.g., `https://www.youtube.com/results?search_query=query`) instead of manually typing into search bars! It is 100x more reliable.\n"
            "</browser_and_applications>\n"
            "<grounding_and_observation_rules>\n"
            "- Always rely on the Set-of-Marks UI elements returned by `observe_screen` or the DOM tree from Chrome MCP.\n"
            "- CRITICAL: NEVER hallucinate UI element IDs, selectors, or coordinates! You MUST execute an observation tool, WAIT for the response, and then use the actual elements found in the NEXT turn.\n"
            "- DO NOT queue up multiple UI interactions (like fill, then click, then wait) in a single turn. You must do them step-by-step, observing the result after each action.\n"
            "</grounding_and_observation_rules>\n"
            "<behavioral_rules>\n"
            "CRITICAL BEHAVIORAL RULES:\n"
            "1. CHAT FIRST: By default, respond to the user in plain text within the conversation. Do NOT create, write, or edit files unless the user explicitly asks you to.\n"
            "2. START DOING IT: When given a task, START DOING IT immediately. Do not restate the task, do not list what you will do, do not ask for confirmation. Just execute your tools.\n"
            "3. ACT STEP-BY-STEP: Solve complex tasks by taking one action, observing the result, and then taking the next action. Never try to blindly execute 5 tool calls at once without checking if the first one succeeded.\n"
            "</behavioral_rules>\n"
            "<tool_calling_rules>\n"
            "CRITICAL: You MUST use the standard native JSON tool-calling format provided by the API. NEVER output raw pseudo-code like `<function=ask_llm_and_execute>...`. Just return a standard conversational response, and let the API translate your tool invocation into the actual tool call.\n"
            "If you only want to talk to the user, output plain text without any tool calls.\n"
            "</tool_calling_rules>\n"
            "<communication_style>\n"
            "- **Formatting**. Format your responses in github-style markdown to make your responses easier for the USER to parse. For example, use headers to organize your responses and bolded or italicized text to highlight important keywords.\n"
            "- **Proactiveness**. As an agent, you are allowed to be proactive. If the user asks you to do something, actively write and run the automation script instead of just describing it.\n"
            "- **Ask for clarification**. If you are unsure about the USER's intent, always ask for clarification rather than making assumptions.\n"
            "</communication_style>\n"
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