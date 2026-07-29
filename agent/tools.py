from pathlib import Path
from urllib.parse import urlparse
import urllib.request

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