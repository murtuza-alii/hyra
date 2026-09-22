import re
from pathlib import Path
from typing import Protocol

from .context_agent import Inspiration
from .integrations.antigravity_client import AntigravityClient
from .integrations.session_pool import SessionPool
from .manifest import build_package
from .models import SolutionPackage, TaskContract


class ProposalAgent(Protocol):
    async def propose(self, *, task: TaskContract, inspiration: Inspiration, staging_dir: Path) -> SolutionPackage: ...


def _normalize_solution_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip().lstrip("/")
    if cleaned.startswith("solution/"):
        return cleaned
    return f"solution/{cleaned}"


def extract_files_from_markdown(text: str) -> dict[str, str]:
    """Extract file contents and relative paths from markdown code blocks."""
    files: dict[str, str] = {}

    pattern1 = re.compile(
        r"```[a-zA-Z0-9_-]*\s+(?:file|path|filename)=[\"']?([^\s\"'>]+)[\"']?\s*\n(.*?)```",
        re.DOTALL
    )
    for match in pattern1.finditer(text):
        path, code = match.group(1).strip(), match.group(2)
        norm_path = _normalize_solution_path(path)
        files[norm_path] = code

    if not files:
        pattern2 = re.compile(
            r"(?:###?\s*[`\"']?([a-zA-Z0-9_./\\-]+)[`\"']?|\*\*([a-zA-Z0-9_./\\-]+)\*\*)\s*\n\s*```[a-zA-Z0-9_-]*\s*\n(.*?)```",
            re.DOTALL
        )
        for match in pattern2.finditer(text):
            raw_path = (match.group(1) or match.group(2)).strip()
            code = match.group(3)
            if "solution" in raw_path or raw_path.endswith((".sh", ".py", ".json", ".txt")):
                norm_path = _normalize_solution_path(raw_path)
                files[norm_path] = code

    if not files:
        pattern3 = re.compile(
            r"```[a-zA-Z0-9_-]*\s*\n\s*(?:#|//|--)\s*(?:file|filepath|path):\s*([^\r\n]+)\s*\n(.*?)```",
            re.DOTALL
        )
        for match in pattern3.finditer(text):
            path, code = match.group(1).strip(), match.group(2)
            norm_path = _normalize_solution_path(path)
            files[norm_path] = code

    if not files:
        code_blocks = re.findall(r"```([a-zA-Z0-9_-]*)\s*\n(.*?)```", text, re.DOTALL)
        if len(code_blocks) == 1:
            lang, code = code_blocks[0]
            lang = lang.lower()
            if lang in ("bash", "sh", "shell") or code.strip().startswith("#!"):
                files["solution/solve.sh"] = code
            elif lang in ("python", "py"):
                files["solution/main.py"] = code
                files["solution/solve.sh"] = "#!/bin/sh\npython3 solution/main.py\n"
            else:
                files["solution/solve.sh"] = code
        elif len(code_blocks) > 1:
            for i, (lang, code) in enumerate(code_blocks):
                lang = lang.lower()
                if (lang in ("bash", "sh", "shell") or code.strip().startswith("#!")) and "solution/solve.sh" not in files:
                    files["solution/solve.sh"] = code
                elif lang in ("python", "py"):
                    filename = f"solution/script_{i}.py" if "solution/main.py" in files else "solution/main.py"
                    files[filename] = code
            if "solution/solve.sh" not in files and "solution/main.py" in files:
                files["solution/solve.sh"] = "#!/bin/sh\npython3 solution/main.py\n"

    if "solution/solve.sh" not in files:
        bash_blocks = [code for lang, code in re.findall(r"```([a-zA-Z0-9_-]*)\s*\n(.*?)```", text, re.DOTALL) if lang.lower() in ("bash", "sh")]
        if bash_blocks:
            files["solution/solve.sh"] = bash_blocks[0]

    return files


class AntigravityProposalAgent:
    """Uses the Universal Antigravity Client to query local Antigravity subscription."""

    def __init__(self, client: AntigravityClient, session_pool: SessionPool | None = None) -> None:
        self.client = client
        self.session_pool = session_pool or SessionPool()

    def _build_prompt(self, task: TaskContract, inspiration: Inspiration) -> str:
        prompt_lines = [
            f"You are Mini-Hyra's Proposal Agent. Your job is to create a code solution for task '{task.task_id}'.",
            f"Task Family: {task.task_family}",
            f"Objective Metric: {task.objective.name} (direction: {task.objective.direction})",
            f"Resource limits: Wall timeout {task.wall_timeout_seconds}s, Memory limit {task.memory_limit_mb}MB.",
            "",
            "### Context & Exploration Direction:",
            f"- Direction: {inspiration.direction}",
            f"- Reason: {inspiration.reason}",
        ]

        if inspiration.checks:
            prompt_lines.append("Validity checks to satisfy:")
            for check in inspiration.checks:
                prompt_lines.append(f"- {check}")

        if inspiration.record_ids:
            prompt_lines.append(f"Historical record references: {', '.join(inspiration.record_ids)}")

        prompt_lines.extend([
            "",
            "### Output Requirements:",
            "1. Output a complete, self-contained solution.",
            "2. The primary execution entrypoint MUST be `solution/solve.sh` (a valid POSIX shell script).",
            "3. If using Python or another language, write your code to `solution/` (e.g. `solution/main.py`) and make `solution/solve.sh` execute it.",
            "4. Format your output using Markdown code fences with file path annotations:",
            '```bash file="solution/solve.sh"',
            "#!/bin/sh",
            "python3 solution/main.py",
            "```",
            '```python file="solution/main.py"',
            "# Your code implementation here",
            "```",
            "Do not include conversational filler before the code blocks.",
        ])

        return "\n".join(prompt_lines)


    async def propose(self, *, task: TaskContract, inspiration: Inspiration, staging_dir: Path) -> SolutionPackage:
        prompt = self._build_prompt(task, inspiration)
        response = await self.client.send_message(role="proposal", message=prompt, staging_dir=staging_dir)

        if not response.success:
            raise RuntimeError(f"Antigravity Proposal Agent failed: {response.error}")

        files = extract_files_from_markdown(response.content)
        if "solution/solve.sh" not in files:
            raise ValueError(f"Proposal Agent response did not contain required solution/solve.sh. Response excerpt:\n{response.content[:600]}")

        for rel_path, code in files.items():
            target_file = staging_dir / rel_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(code.encode("utf-8"))
            if rel_path.endswith(".sh"):
                try:
                    target_file.chmod(target_file.stat().st_mode | 0o755)
                except OSError:
                    pass

        return build_package({k: v.encode("utf-8") for k, v in files.items()})


class TemplateProposalAgent:
    """Generates baseline template or custom scripted proposals without calling an LLM."""

    def __init__(self, template_files: dict[str, str] | None = None) -> None:
        self.template_files = template_files or {
            "solution/solve.sh": "#!/bin/sh\nexit 0\n"
        }

    async def propose(self, *, task: TaskContract, inspiration: Inspiration, staging_dir: Path) -> SolutionPackage:
        for path, code in self.template_files.items():
            full = staging_dir / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(code.encode("utf-8"))
            if path.endswith(".sh"):
                try:
                    full.chmod(full.stat().st_mode | 0o755)
                except OSError:
                    pass
        return build_package({k: v.encode("utf-8") for k, v in self.template_files.items()})
