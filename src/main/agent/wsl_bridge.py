import os
import subprocess
import logging
from langchain.tools import BaseTool

logger = logging.getLogger(__name__)

class WSLBridge:
    @staticmethod
    def to_wsl_path(windows_path: str) -> str:
        """Convert a Windows path like C:\\Projects to /mnt/c/Projects"""
        if not windows_path:
            return windows_path
            
        windows_path = os.path.abspath(windows_path)
        if windows_path.startswith("\\\\"):
            logger.warning("UNC paths are not supported in WSL")
            return windows_path
            
        if len(windows_path) >= 2 and windows_path[1] == ':':
            drive = windows_path[0].lower()
            rest = windows_path[2:].replace('\\', '/')
            return f"/mnt/{drive}{rest}"
            
        return windows_path.replace('\\', '/')

    @staticmethod
    def to_windows_path(wsl_path: str) -> str:
        """Convert a WSL path like /mnt/c/Projects to C:\\Projects"""
        if not wsl_path:
            return wsl_path
            
        if wsl_path.startswith("/mnt/") and len(wsl_path) >= 7 and wsl_path[6] == '/':
            drive = wsl_path[5].upper()
            rest = wsl_path[6:].replace('/', '\\')
            return f"{drive}:{rest}"
            
        return wsl_path

    @staticmethod
    def run_command(command: str, cwd: str = None, timeout: int = 15) -> subprocess.CompletedProcess:
        """Run a command inside WSL."""
        wsl_cwd = WSLBridge.to_wsl_path(cwd) if cwd else None
        
        args = ["wsl"]
        if wsl_cwd:
            # Change directory inside WSL before running the command
            args.extend(["--cd", wsl_cwd])
            
        args.extend(["-e", "bash", "-c", command])
        
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout
        )

class WSLPythonREPLTool(BaseTool):
    name: str = "Python_REPL"
    description: str = "A Python shell running in a WSL2 sandbox. Use this to execute python commands. Input should be a valid python command. If you want to see the output of a value, you should print it out with `print(...)`."

    def _run(self, query: str) -> str:
        # Write query to a temporary python script in the workspace (which is mapped in WSL)
        import tempfile
        # Save in the project directory so WSL has easy access
        script_path = os.path.join(os.getcwd(), ".wsl_temp_script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(query)
            
        wsl_script_path = WSLBridge.to_wsl_path(script_path)
        
        try:
            result = WSLBridge.run_command(f"python3 {wsl_script_path}", timeout=30)
            output = result.stdout
            if result.stderr:
                output += f"\\nStderr: {result.stderr}"
            return output.strip() if output else "Executed successfully with no output."
        except subprocess.TimeoutExpired:
            return "Execution timed out after 30 seconds."
        except Exception as e:
            return f"Error executing Python code: {e}"
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)
