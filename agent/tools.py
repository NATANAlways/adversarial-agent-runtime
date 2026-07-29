from pathlib import Path
from urllib.parse import urlparse
import urllib.request
from agent.email_tool import send_email
import subprocess
import sys

# Allowed websites
ALLOWED_HOSTS = {
    "example.com",
    "api.github.com",
}

WORKSPACE = Path("workspace").resolve()

def _safe_path(path: str) -> Path:
    """
    the path given check whether it is within the workspace/
    if it outside , error will be rasied
    """

    # the path given will be considerd within the worspace
    target = (WORKSPACE / path).resolve()

    # check whether the given path exsists
    if not target.is_relative_to(WORKSPACE):
        raise ValueError(f"REFUSED: path '{path}' is outside workspace/")
    return target

def read_file(path: str) -> str:
    """
        read a file inside the workspace 
    """ 
    target = _safe_path(path)
    if not target.exists():
        return f"Error: file '{path}' does not exsists"
    return target.read_text()

def write_file(path:str , content: str) -> str:
    """
        writing a file within thw workspace
    """
    target = _safe_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Ok: wrote {len(content)} characters to '{path}'"


def http_get(url:str) -> str:
    """
    allow to fetch url if it was in the allowed lists
    """

    parsed = urlparse(url)
    host = parsed.hostname

    if host not in ALLOWED_HOSTS:
        return f"REFUSED: host '{host}' is not on the aloow-list. Allowed: {sorted(ALLOWED_HOSTS)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode()[:1000]
    except Exception as e:
        return f"ERROR fetching '{url}': {e}"
    

def run_python(code: str) -> str:
    """
        running the code given by the model in a subprocess
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]: {result.stderr}"
        return output.strip() or "(no output)"
    
    except subprocess.TimeoutExpired:
        return "ERROR: code timeout (exceed 5 seconds)"
    except Exception as e:
        return f"ERROR running python: {e}"
    
def run_tool(name: str, tool_input: dict) -> str:
    """
    calling right fucntions the model asks or the tool not available telling the tools are not here
    """
    try:
        if name == "read_file":
            return read_file(tool_input["path"])
        elif name == "write_file":
            return write_file(tool_input["path"], tool_input["content"])
        elif name == "http_get":
            return http_get(tool_input["url"])
        elif name == "send_email":
            return send_email(
                tool_input["to"],
                tool_input["subject"],
                tool_input["body"]
            )
        elif name == "run_python":
            return run_python(tool_input["code"])
        else:
            return f"ERROR: unknown tool '{name}'"
    except (KeyError, TypeError) as e:
        # S2/S3 defense: if arguments were wrong (missing/wrong type)
        return f"ERROR: bad arguments for tool '{name}': {e}"