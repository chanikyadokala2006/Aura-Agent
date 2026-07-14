import os
import re

agent_file = r"C:\Projects\Agent_project\my-ollama-project\src\main\agent\MyAgent.py"
with open(agent_file, "r", encoding="utf-8") as f:
    content = f.read()

loop_guard_code = """
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

"""

# Insert LoopGuardMiddleware right before PatchToolMessagesMiddleware
if "class LoopGuardMiddleware" not in content:
    content = content.replace("class PatchToolMessagesMiddleware", loop_guard_code + "\nclass PatchToolMessagesMiddleware")

# Add LoopGuardMiddleware() to middleware list
if "LoopGuardMiddleware()" not in content:
    content = content.replace("middleware=[PatchToolMessagesMiddleware()]", "middleware=[LoopGuardMiddleware(), PatchToolMessagesMiddleware()]")

with open(agent_file, "w", encoding="utf-8") as f:
    f.write(content)

print("Injected LoopGuardMiddleware")
