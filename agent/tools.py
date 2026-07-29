from pathlib import Path

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

