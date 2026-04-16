"""
code_indexer.py — Scan codebases and build a searchable code index.

Provides relevant code snippets during incident investigation by:
1. Indexing source files (imports, classes, functions, line ranges)
2. Searching by service name + error context at incident time
3. Returning code snippets formatted for the RCA agent prompt
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FunctionDef:
    name: str
    line_start: int
    line_end: int
    args: List[str] = field(default_factory=list)


@dataclass
class ClassDef:
    name: str
    line_start: int
    line_end: int
    methods: List[str] = field(default_factory=list)


@dataclass
class FileEntry:
    path: str
    language: str
    imports: List[str] = field(default_factory=list)
    classes: List[ClassDef] = field(default_factory=list)
    functions: List[FunctionDef] = field(default_factory=list)

    def all_symbols(self) -> List[str]:
        symbols = [f.name for f in self.functions]
        for c in self.classes:
            symbols.append(c.name)
            symbols.extend(c.methods)
        return symbols

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "imports": self.imports,
            "classes": [asdict(c) for c in self.classes],
            "functions": [asdict(f) for f in self.functions],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FileEntry":
        return cls(
            path=d["path"],
            language=d["language"],
            imports=d.get("imports", []),
            classes=[ClassDef(**c) for c in d.get("classes", [])],
            functions=[FunctionDef(**f) for f in d.get("functions", [])],
        )


@dataclass
class CodeSnippet:
    file_path: str
    function_name: Optional[str]
    line_start: int
    line_end: int
    code: str
    relevance: str  # why this snippet was selected


# ---------------------------------------------------------------------------
# Language detection + extensions
# ---------------------------------------------------------------------------

_LANG_MAP = {
    ".py": "python",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rb": "ruby",
    ".rs": "rust",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".kt": "kotlin",
    ".scala": "scala",
    ".php": "php",
    ".swift": "swift",
}

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    "vendor", "third_party",
}


def _detect_language(path: str) -> Optional[str]:
    return _LANG_MAP.get(Path(path).suffix.lower())


# ---------------------------------------------------------------------------
# Python AST indexer
# ---------------------------------------------------------------------------

def _index_python(filepath: str, source: str) -> FileEntry:
    entry = FileEntry(path=filepath, language="python")
    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return entry

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                entry.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                entry.imports.append(node.module)
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # Only top-level or class-level (handled by class visitor)
            if _is_top_level(tree, node):
                entry.functions.append(FunctionDef(
                    name=node.name,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    args=[a.arg for a in node.args.args if a.arg != "self"],
                ))
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(item.name)
            entry.classes.append(ClassDef(
                name=node.name,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                methods=methods,
            ))

    return entry


def _is_top_level(tree: ast.Module, target: ast.AST) -> bool:
    """Check if a node is a direct child of the module (not inside a class)."""
    for node in ast.iter_child_nodes(tree):
        if node is target:
            return True
    return False


# ---------------------------------------------------------------------------
# Regex-based indexer for other languages
# ---------------------------------------------------------------------------

_FUNC_PATTERNS = {
    "go": re.compile(r"^func\s+(?:\(.*?\)\s+)?(\w+)\s*\(", re.MULTILINE),
    "java": re.compile(r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(", re.MULTILINE),
    "javascript": re.compile(r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\()", re.MULTILINE),
    "typescript": re.compile(r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(|(?:export\s+)?(?:async\s+)?function\s+(\w+))", re.MULTILINE),
    "ruby": re.compile(r"^\s*def\s+(\w+)", re.MULTILINE),
    "rust": re.compile(r"^\s*(?:pub\s+)?fn\s+(\w+)", re.MULTILINE),
    "csharp": re.compile(r"(?:public|private|protected|internal|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(", re.MULTILINE),
    "kotlin": re.compile(r"^\s*(?:fun|suspend\s+fun)\s+(\w+)", re.MULTILINE),
    "scala": re.compile(r"^\s*def\s+(\w+)", re.MULTILINE),
    "php": re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)", re.MULTILINE),
    "swift": re.compile(r"^\s*func\s+(\w+)", re.MULTILINE),
    "cpp": re.compile(r"(?:[\w:]+\s+)+(\w+)\s*\(", re.MULTILINE),
    "c": re.compile(r"(?:[\w\*]+\s+)+(\w+)\s*\(", re.MULTILINE),
}

_CLASS_PATTERNS = {
    "java": re.compile(r"^\s*(?:public|private|abstract|final|\s)*class\s+(\w+)", re.MULTILINE),
    "javascript": re.compile(r"^\s*class\s+(\w+)", re.MULTILINE),
    "typescript": re.compile(r"^\s*(?:export\s+)?class\s+(\w+)", re.MULTILINE),
    "csharp": re.compile(r"^\s*(?:public|private|internal|abstract|sealed|\s)*class\s+(\w+)", re.MULTILINE),
    "kotlin": re.compile(r"^\s*(?:data\s+)?class\s+(\w+)", re.MULTILINE),
    "scala": re.compile(r"^\s*(?:case\s+)?class\s+(\w+)", re.MULTILINE),
    "php": re.compile(r"^\s*class\s+(\w+)", re.MULTILINE),
    "swift": re.compile(r"^\s*class\s+(\w+)", re.MULTILINE),
    "rust": re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)", re.MULTILINE),
    "go": re.compile(r"^\s*type\s+(\w+)\s+struct", re.MULTILINE),
    "cpp": re.compile(r"^\s*class\s+(\w+)", re.MULTILINE),
}

_IMPORT_PATTERNS = {
    "go": re.compile(r'^\s*(?:import\s+)?"([^"]+)"', re.MULTILINE),
    "java": re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    "javascript": re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)|require\s*\(\s*['"]([^'"]+))""", re.MULTILINE),
    "typescript": re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)|require\s*\(\s*['"]([^'"]+))""", re.MULTILINE),
    "ruby": re.compile(r"^\s*require\s+['\"]([^'\"]+)", re.MULTILINE),
    "rust": re.compile(r"^\s*use\s+([\w:]+)", re.MULTILINE),
    "csharp": re.compile(r"^\s*using\s+([\w.]+)", re.MULTILINE),
    "kotlin": re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    "scala": re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    "php": re.compile(r"^\s*use\s+([\w\\]+)", re.MULTILINE),
    "swift": re.compile(r"^\s*import\s+(\w+)", re.MULTILINE),
}


def _index_generic(filepath: str, source: str, language: str) -> FileEntry:
    entry = FileEntry(path=filepath, language=language)

    # Imports
    pat = _IMPORT_PATTERNS.get(language)
    if pat:
        for m in pat.finditer(source):
            imp = next((g for g in m.groups() if g), None)
            if imp:
                entry.imports.append(imp)

    # Functions
    pat = _FUNC_PATTERNS.get(language)
    if pat:
        lines = source.split("\n")
        for m in pat.finditer(source):
            name = next((g for g in m.groups() if g), None)
            if name:
                line_num = source[:m.start()].count("\n") + 1
                entry.functions.append(FunctionDef(
                    name=name,
                    line_start=line_num,
                    line_end=min(line_num + 30, len(lines)),  # approximate
                ))

    # Classes
    pat = _CLASS_PATTERNS.get(language)
    if pat:
        for m in pat.finditer(source):
            name = next((g for g in m.groups() if g), None)
            if name:
                line_num = source[:m.start()].count("\n") + 1
                entry.classes.append(ClassDef(
                    name=name,
                    line_start=line_num,
                    line_end=min(line_num + 50, len(source.split("\n"))),
                ))

    return entry


# ---------------------------------------------------------------------------
# Service mapping heuristics
# ---------------------------------------------------------------------------

_SERVICE_INDICATORS = [
    "service", "svc", "server", "api", "app", "microservice",
    "handler", "controller", "worker",
]


def _infer_service_map(files: Dict[str, FileEntry]) -> Dict[str, List[str]]:
    """
    Infer service name → file paths from directory structure.
    Looks for directories named like services (e.g., src/cart-service/).
    """
    service_map: Dict[str, List[str]] = {}

    for fpath in files:
        parts = Path(fpath).parts
        for i, part in enumerate(parts):
            part_lower = part.lower().replace("-", "_").replace(".", "_")
            # Check if this directory level looks like a service
            if any(ind in part_lower for ind in _SERVICE_INDICATORS):
                service_name = part.lower().replace("_", "-")
                service_map.setdefault(service_name, []).append(fpath)
                break
            # Also map top-level dirs in src/ as potential services
            if i > 0 and parts[i - 1].lower() in ("src", "services", "apps", "packages"):
                service_name = part.lower().replace("_", "-")
                service_map.setdefault(service_name, []).append(fpath)
                break

    return service_map


# ---------------------------------------------------------------------------
# CodeIndex — the searchable index
# ---------------------------------------------------------------------------

class CodeIndex:
    """Searchable code index built from one or more codebases."""

    def __init__(
        self,
        files: Dict[str, FileEntry],
        service_map: Dict[str, List[str]],
        base_paths: List[str],
    ):
        self.files = files
        self.service_map = service_map
        self.base_paths = base_paths

    def search(
        self,
        service: str,
        error_context: str = "",
        max_files: int = 5,
        max_lines_per_snippet: int = 60,
    ) -> List[CodeSnippet]:
        """
        Find code snippets relevant to a service + error context.

        Strategy:
        1. Find files associated with the service (via service_map or path matching)
        2. Rank by symbol overlap with error_context
        3. Extract relevant function/class bodies
        """
        candidates = self._find_candidate_files(service)
        if not candidates and error_context:
            # Broaden: search all files for symbol matches
            candidates = list(self.files.keys())

        scored = self._score_files(candidates, service, error_context)
        scored.sort(key=lambda x: x[1], reverse=True)

        snippets: List[CodeSnippet] = []
        for fpath, score, reason in scored[:max_files]:
            entry = self.files[fpath]
            snippet = self._extract_snippet(fpath, entry, error_context, max_lines_per_snippet)
            if snippet:
                snippet.relevance = reason
                snippets.append(snippet)

        return snippets

    def _find_candidate_files(self, service: str) -> List[str]:
        """Find files likely belonging to a service."""
        service_lower = service.lower().replace("-", "_").replace(".", "_")

        # Direct match in service_map
        for svc_name, paths in self.service_map.items():
            svc_lower = svc_name.lower().replace("-", "_").replace(".", "_")
            if service_lower in svc_lower or svc_lower in service_lower:
                return paths

        # Fuzzy: service name appears in file path
        matches = []
        for fpath in self.files:
            path_lower = fpath.lower().replace("-", "_").replace(".", "_")
            if service_lower in path_lower:
                matches.append(fpath)
        return matches

    def _score_files(
        self, candidates: List[str], service: str, error_context: str
    ) -> List[Tuple[str, float, str]]:
        """Score candidate files by relevance to error context."""
        error_tokens = set(re.findall(r"\w+", error_context.lower()))
        results = []

        for fpath in candidates:
            entry = self.files.get(fpath)
            if not entry:
                continue

            score = 0.0
            reasons = []

            # Service name in path
            if service.lower().replace("-", "_") in fpath.lower().replace("-", "_"):
                score += 2.0
                reasons.append("path matches service")

            # Symbol overlap with error context
            symbols = set(s.lower() for s in entry.all_symbols())
            overlap = symbols & error_tokens
            if overlap:
                score += len(overlap) * 3.0
                reasons.append(f"symbols match: {', '.join(list(overlap)[:3])}")

            # Import overlap (modules mentioned in error)
            import_names = set(i.split(".")[-1].lower() for i in entry.imports)
            imp_overlap = import_names & error_tokens
            if imp_overlap:
                score += len(imp_overlap) * 1.5
                reasons.append(f"imports match: {', '.join(list(imp_overlap)[:3])}")

            # File name relevance
            fname = Path(fpath).stem.lower()
            if fname in error_tokens:
                score += 2.0
                reasons.append("filename matches error context")

            if score > 0:
                results.append((fpath, score, "; ".join(reasons) if reasons else "general match"))

        return results

    def _extract_snippet(
        self,
        fpath: str,
        entry: FileEntry,
        error_context: str,
        max_lines: int,
    ) -> Optional[CodeSnippet]:
        """Read actual code from disk for the most relevant function/class."""
        # Find the absolute path
        abs_path = self._resolve_path(fpath)
        if not abs_path or not os.path.isfile(abs_path):
            return None

        try:
            lines = open(abs_path, encoding="utf-8", errors="replace").readlines()
        except Exception:
            return None

        error_tokens = set(re.findall(r"\w+", error_context.lower()))

        # Try to find the most relevant function/class
        best_start, best_end, best_name = 0, min(max_lines, len(lines)), None

        # Score each function/class
        best_score = -1
        for func in entry.functions:
            s = sum(1 for t in error_tokens if t == func.name.lower())
            if s > best_score:
                best_score = s
                best_start = func.line_start - 1
                best_end = min(func.line_end, best_start + max_lines)
                best_name = func.name

        for cls in entry.classes:
            s = sum(1 for t in error_tokens if t == cls.name.lower())
            s += sum(0.5 for m in cls.methods for t in error_tokens if t == m.lower())
            if s > best_score:
                best_score = s
                best_start = cls.line_start - 1
                best_end = min(cls.line_end, best_start + max_lines)
                best_name = cls.name

        code = "".join(lines[best_start:best_end])
        return CodeSnippet(
            file_path=fpath,
            function_name=best_name,
            line_start=best_start + 1,
            line_end=best_end,
            code=code,
            relevance="",
        )

    def _resolve_path(self, fpath: str) -> Optional[str]:
        """Resolve a relative file path using base_paths."""
        if os.path.isabs(fpath) and os.path.exists(fpath):
            return fpath
        for base in self.base_paths:
            full = os.path.join(base, fpath)
            if os.path.exists(full):
                return full
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files": {k: v.to_dict() for k, v in self.files.items()},
            "service_map": self.service_map,
            "base_paths": self.base_paths,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CodeIndex":
        files = {k: FileEntry.from_dict(v) for k, v in d["files"].items()}
        return cls(
            files=files,
            service_map=d.get("service_map", {}),
            base_paths=d.get("base_paths", []),
        )

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "CodeIndex":
        with open(path) as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# CodeIndexer — builds the index
# ---------------------------------------------------------------------------

class CodeIndexer:
    """
    Scans codebases (local paths or GitHub URLs) and builds a CodeIndex.

    Usage:
        indexer = CodeIndexer(["/path/to/repo", "https://github.com/org/repo"])
        index = indexer.build_index()
        snippets = index.search("cart-service", "TimeoutError in get_cart")
    """

    def __init__(self, codebase_paths: List[str]):
        self.codebase_paths = codebase_paths
        self._temp_dirs: List[str] = []

    def build_index(self) -> CodeIndex:
        """Scan all codebases and return a unified CodeIndex."""
        all_files: Dict[str, FileEntry] = {}
        base_paths: List[str] = []

        for path in self.codebase_paths:
            local_path = self._resolve_codebase(path)
            base_paths.append(local_path)
            print(f"[CodeIndexer] Scanning {local_path}...")
            files = self._scan_directory(local_path, local_path)
            all_files.update(files)
            print(f"[CodeIndexer] Indexed {len(files)} source files")

        service_map = _infer_service_map(all_files)
        if service_map:
            print(f"[CodeIndexer] Inferred {len(service_map)} services: {', '.join(service_map.keys())}")

        return CodeIndex(files=all_files, service_map=service_map, base_paths=base_paths)

    def _resolve_codebase(self, path: str) -> str:
        """Resolve a codebase path: local directory or GitHub URL → local path."""
        if path.startswith("https://github.com/") or path.startswith("git@"):
            return self._clone_repo(path)
        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            raise FileNotFoundError(f"Codebase not found: {path}")
        return abs_path

    def _clone_repo(self, url: str) -> str:
        """Clone a GitHub repo to a temporary directory."""
        tmp = tempfile.mkdtemp(prefix="rootscout_code_")
        self._temp_dirs.append(tmp)
        print(f"[CodeIndexer] Cloning {url} to {tmp}...")
        subprocess.run(
            ["git", "clone", "--depth=1", url, tmp],
            check=True,
            capture_output=True,
        )
        return tmp

    def _scan_directory(self, root: str, base: str) -> Dict[str, FileEntry]:
        """Walk a directory and index all source files."""
        files: Dict[str, FileEntry] = {}

        for dirpath, dirnames, filenames in os.walk(root):
            # Skip irrelevant directories
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]

            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                language = _detect_language(fname)
                if not language:
                    continue

                # Use relative path from base
                rel_path = os.path.relpath(full_path, base)

                try:
                    source = open(full_path, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue

                # Skip very large files (>500KB)
                if len(source) > 500_000:
                    continue

                if language == "python":
                    entry = _index_python(rel_path, source)
                else:
                    entry = _index_generic(rel_path, source, language)

                files[rel_path] = entry

        return files


# ---------------------------------------------------------------------------
# Context enrichment — integrates with RCA agent
# ---------------------------------------------------------------------------

def enrich_context_from_code_index(
    context_packet: Dict[str, Any],
    code_index: CodeIndex,
    max_snippets_per_service: int = 3,
    max_lines: int = 60,
) -> Dict[str, Any]:
    """
    Enrich a context_packet with code snippets from the CodeIndex.
    Follows the same envelope pattern as enrich_context_from_github_output_path.
    """
    from rootscout.graph.data_parser import make_envelope

    out = dict(context_packet)
    out_nodes: List[Dict[str, Any]] = []

    for node in context_packet.get("related_nodes", []):
        n = dict(node)
        svc = n.get("service", "")
        existing = list(n.get("events") or [])

        # Build error context from existing events
        error_parts = []
        for ev in existing:
            if isinstance(ev, dict):
                desc = ev.get("description", "")
                summary = ev.get("summary", "")
                error_parts.append(f"{desc} {summary}")
        error_context = " ".join(error_parts)

        snippets = code_index.search(
            service=svc,
            error_context=error_context,
            max_files=max_snippets_per_service,
            max_lines_per_snippet=max_lines,
        )

        for snippet in snippets:
            envelope = make_envelope(
                source="codebase",
                kind="relevant_code",
                timestamp=None,
                summary=f"Code: {snippet.file_path}"
                + (f"::{snippet.function_name}" if snippet.function_name else "")
                + f" (lines {snippet.line_start}-{snippet.line_end})",
                payload={
                    "filename": snippet.file_path,
                    "function": snippet.function_name,
                    "line_start": snippet.line_start,
                    "line_end": snippet.line_end,
                    "patch": snippet.code,
                    "relevance": snippet.relevance,
                },
            )
            existing.append(envelope)

        n["events"] = existing
        out_nodes.append(n)

    out["related_nodes"] = out_nodes
    return out
