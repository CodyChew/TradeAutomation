"""Audit TradeAutomation process docs and tracked artifact hygiene."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]

CRITICAL_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "README.md",
    "PROJECT_STATE.md",
    "SESSION_HANDOFF.md",
    "strategies/lp_force_strike_strategy_lab/START_HERE.md",
    "strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md",
    "docs/change_gate.md",
    "docs/codex_worktree_workflow.md",
    "docs/system_troubleshooting.md",
    "docs/lpfs_strategy_improvement_workflow.md",
    "docs/context_architecture.md",
    "docs/evidence_catalog.md",
    "docs/history/lpfs_operations.md",
    "docs/repo_maintenance_policy.md",
    "docs/decision_log.md",
    "strategies/lp_force_strike_strategy_lab/docs/experiment_history.md",
)

CRITICAL_DIRS: tuple[str, ...] = (
    "docs/reviews",
)

ADVISORY_LINE_LIMITS: dict[str, int] = {
    "README.md": 250,
    "PROJECT_STATE.md": 650,
    "SESSION_HANDOFF.md": 1200,
    "strategies/lp_force_strike_strategy_lab/START_HERE.md": 500,
    "strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md": 1200,
    "AGENTS.md": 800,
}

REQUIRED_REFERENCES: dict[str, tuple[str, ...]] = {
    "README.md": (
        "SESSION_HANDOFF.md",
        "PROJECT_STATE.md",
        "docs/context_architecture.md",
        "docs/evidence_catalog.md",
        "docs/repo_maintenance_policy.md",
    ),
    "PROJECT_STATE.md": (
        "docs/context_architecture.md",
        "docs/evidence_catalog.md",
        "docs/history/lpfs_operations.md",
        "docs/repo_maintenance_policy.md",
        "docs/decision_log.md",
    ),
    "SESSION_HANDOFF.md": (
        "docs/context_architecture.md",
        "docs/evidence_catalog.md",
        "docs/history/lpfs_operations.md",
        "docs/repo_maintenance_policy.md",
    ),
    "AGENTS.md": (
        "docs/change_gate.md",
        "docs/repo_maintenance_policy.md",
    ),
    "docs/change_gate.md": (
        "docs/reviews/",
        "docs/decision_log.md",
    ),
    "docs/repo_maintenance_policy.md": (
        "scripts/audit_repo_process.py",
        "docs/decision_log.md",
    ),
    "docs/context_architecture.md": (
        "SESSION_HANDOFF.md",
        "PROJECT_STATE.md",
        "docs/evidence_catalog.md",
        "docs/decision_log.md",
    ),
    "docs/evidence_catalog.md": (
        "current_label",
        "hash_or_manifest",
        "non_actions",
    ),
    "strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md": (
        "docs/evidence_catalog.md",
        "docs/experiment_history.md",
        "docs/lpfs_strategy_iteration_context.md",
    ),
}

REQUIRED_CONTEXT_ANCHORS: dict[str, tuple[str, ...]] = {
    "SESSION_HANDOFF.md": (
        "historical packet facts only",
        "No live strategy change is approved",
        "active state/broker mismatch count",
    ),
    "PROJECT_STATE.md": (
        "historical facts only",
        "No reconciliation, canary, recovery enablement",
        "Current decision: no live strategy change",
    ),
    "strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md": (
        "No live strategy change is approved",
        "H8 compressed risk",
        "H8 low-spread-only",
    ),
    "docs/evidence_catalog.md": (
        "historical packet facts only",
        "lpfs-status-20260627",
        "lpfs-research-closeout-20260627",
    ),
}

CURRENT_STATE_FILES: tuple[str, ...] = (
    "PROJECT_STATE.md",
    "SESSION_HANDOFF.md",
    "strategies/lp_force_strike_strategy_lab/START_HERE.md",
    "strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md",
)

STALE_CURRENT_STATE_PHRASES: tuple[str, ...] = (
    "FTMO remains contained",
    "IC remains contained",
    "remain paused",
    "remains paused",
    "production remains paused",
    "Production remains intentionally paused",
    "stop before Stage 5",
    "Stop before Stage 5",
    "kill switches active",
    "contained IC Stage 3 point-in-time boundary",
    "current handoff boundary is the contained IC Stage 3",
    "Refresh both lanes before any approved Stage 5 resumption",
    "before any approved Stage 5 resumption",
    "locally verified but not deployed",
    "Pulling code alone does not start separated telemetry",
)

STALE_PROVENANCE_PHRASES: dict[str, tuple[str, ...]] = {
    "strategies/lp_force_strike_strategy_lab/START_HERE.md": (
        "local candle datasets only",
    ),
    "strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md": (
        "local journal copies and local candle datasets",
    ),
    "docs/lpfs_strategy_iteration_context.md": (
        "local dataset roots",
        "local journal copies and local candle datasets",
    ),
}

TEXT_SUFFIXES: tuple[str, ...] = (
    ".csv",
    ".gitignore",
    ".html",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)

EXCLUDED_DIRS: tuple[str, ...] = (
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "data",
    "htmlcov",
    "reports",
)

EXCLUDED_DIR_PREFIXES: tuple[str, ...] = (
    "venv",
)

RISKY_TRACKED_PREFIXES: tuple[str, ...] = (
    "data/",
    "reports/",
    "configs/local/",
    "htmlcov/",
)

RISKY_TRACKED_EXACT: set[str] = {
    ".coverage",
    "coverage.json",
    "coverage.xml",
    "config.local.json",
    "mql5/lpfs_ea/compile_lpfs_ea.log",
}

RISKY_TRACKED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)\.coverage\.", re.IGNORECASE),
    re.compile(r"(^|/).+\.ex5$", re.IGNORECASE),
    re.compile(r"(^|/).*credentials.*\.json$", re.IGNORECASE),
    re.compile(r"(^|/).*secrets.*\.json$", re.IGNORECASE),
    re.compile(r"(^|/).*\.local\.json$", re.IGNORECASE),
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("telegram_bot_token", re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    path: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, object]:
        row: dict[str, object] = {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }
        if self.line is not None:
            row["line"] = self.line
        return row


@dataclass(frozen=True)
class AuditReport:
    root: str
    status: str
    issues: tuple[AuditIssue, ...]

    @property
    def ok(self) -> bool:
        return self.status != "fail"

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def run_audit(
    root: Path,
    *,
    tracked_paths: Sequence[str] | None = None,
    line_limits: dict[str, int] | None = None,
) -> AuditReport:
    root = root.resolve()
    limits = dict(ADVISORY_LINE_LIMITS)
    if line_limits:
        limits.update(line_limits)

    issues: list[AuditIssue] = []
    issues.extend(_check_required_paths(root))
    issues.extend(_check_required_references(root))
    issues.extend(_check_required_context_anchors(root))
    issues.extend(_check_stale_current_state_phrases(root))
    issues.extend(_check_stale_provenance_phrases(root))
    tracked = list(tracked_paths) if tracked_paths is not None else _load_git_tracked_paths(root)
    issues.extend(_check_line_limits(root, limits))
    issues.extend(_scan_secret_patterns(root, tracked))
    issues.extend(_check_tracked_artifacts(tracked))

    if any(issue.severity == "error" for issue in issues):
        status = "fail"
    elif issues:
        status = "warn"
    else:
        status = "pass"

    return AuditReport(root=str(root), status=status, issues=tuple(issues))


def render_text(report: AuditReport) -> str:
    lines = [
        "TradeAutomation repo process audit",
        f"root={report.root}",
        f"status={report.status}",
        "",
    ]
    if not report.issues:
        lines.append("No issues found.")
        return "\n".join(lines).rstrip() + "\n"

    for issue in report.issues:
        location = issue.path if issue.line is None else f"{issue.path}:{issue.line}"
        lines.append(f"[{issue.severity}] {issue.code} {location} - {issue.message}")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="Repository root to audit.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--fail-on-warning", action="store_true", help="Return 1 for warnings as well as errors.")
    args = parser.parse_args(argv)

    report = run_audit(Path(args.root))
    if args.json:
        print(report.to_json(), end="")
    else:
        print(render_text(report), end="")

    if report.status == "fail":
        return 1
    if args.fail_on_warning and report.status == "warn":
        return 1
    return 0


def _check_required_paths(root: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for relative in CRITICAL_FILES:
        if not (root / relative).is_file():
            issues.append(
                AuditIssue(
                    severity="error",
                    code="missing_critical_file",
                    path=relative,
                    message="critical handoff, process, or source-of-truth file is missing",
                )
            )
    for relative in CRITICAL_DIRS:
        if not (root / relative).is_dir():
            issues.append(
                AuditIssue(
                    severity="error",
                    code="missing_critical_dir",
                    path=relative,
                    message="critical review or process directory is missing",
                )
            )
    return issues


def _check_required_references(root: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for relative, required in REQUIRED_REFERENCES.items():
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in required:
            if needle not in text:
                issues.append(
                    AuditIssue(
                        severity="warning",
                        code="missing_required_reference",
                        path=relative,
                        message=f"expected reference to {needle}",
                    )
                )
    return issues


def _check_required_context_anchors(root: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for relative, required in REQUIRED_CONTEXT_ANCHORS.items():
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in required:
            if needle not in text:
                issues.append(
                    AuditIssue(
                        severity="warning",
                        code="missing_context_anchor",
                        path=relative,
                        message=f"expected first-read context anchor {needle!r}",
                    )
                )
    return issues


def _check_stale_current_state_phrases(root: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for relative in CURRENT_STATE_FILES:
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for phrase in STALE_CURRENT_STATE_PHRASES:
            index = text.find(phrase)
            if index == -1:
                continue
            line = text.count("\n", 0, index) + 1
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="stale_current_state_phrase",
                    path=relative,
                    line=line,
                    message=f"current-state file contains stale-looking phrase {phrase!r}",
                )
            )
    return issues


def _check_stale_provenance_phrases(root: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for relative, phrases in STALE_PROVENANCE_PHRASES.items():
        path = root / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for phrase in phrases:
            index = text.find(phrase)
            if index == -1:
                continue
            line = text.count("\n", 0, index) + 1
            issues.append(
                AuditIssue(
                    severity="error",
                    code="stale_provenance_phrase",
                    path=relative,
                    line=line,
                    message=(
                        f"first-read file contains unsafe unqualified candle-source wording {phrase!r}; "
                        "use explicit provenanced/lane-authoritative candle-source wording"
                    ),
                )
            )
    return issues


def _check_line_limits(root: Path, limits: dict[str, int]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for relative, limit in limits.items():
        path = root / relative
        if not path.is_file():
            continue
        line_count = _line_count(path)
        if line_count > limit:
            issues.append(
                AuditIssue(
                    severity="warning",
                    code="line_limit_exceeded",
                    path=relative,
                    message=f"{line_count} lines exceeds advisory limit {limit}",
                )
            )
    return issues


def _scan_secret_patterns(root: Path, tracked_paths: Sequence[str]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for path in _iter_tracked_text_files(root, tracked_paths):
        relative = _relative_path(path, root)
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for code, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    issues.append(
                        AuditIssue(
                            severity="error",
                            code=f"secret_pattern_{code}",
                            path=relative,
                            line=line_number,
                            message="possible committed secret pattern found",
                        )
                    )
    return issues


def _check_tracked_artifacts(tracked_paths: Sequence[str]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for raw_path in tracked_paths:
        path = raw_path.replace("\\", "/")
        if path in RISKY_TRACKED_EXACT or any(path.startswith(prefix) for prefix in RISKY_TRACKED_PREFIXES):
            issues.append(_tracked_artifact_issue(path))
            continue
        for pattern in RISKY_TRACKED_PATTERNS:
            if pattern.search(path) and not _is_allowed_tracked_local_example(path):
                issues.append(_tracked_artifact_issue(path))
                break
    return issues


def _tracked_artifact_issue(path: str) -> AuditIssue:
    return AuditIssue(
        severity="error",
        code="tracked_runtime_or_secret_artifact",
        path=path,
        message="tracked path looks like runtime evidence, local config, secret material, coverage output, or generated build artifact",
    )


def _is_allowed_tracked_local_example(path: str) -> bool:
    return path.endswith(".example.json") or path.endswith(".template.json")


def _load_git_tracked_paths(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _iter_tracked_text_files(root: Path, tracked_paths: Sequence[str]) -> Iterable[Path]:
    for raw_path in tracked_paths:
        path = root / raw_path
        if not path.is_file():
            continue
        relative_parts = Path(raw_path).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            continue
        if any(part.startswith(EXCLUDED_DIR_PREFIXES) for part in relative_parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_SUFFIXES:
            yield path


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8-sig").splitlines())
    except UnicodeDecodeError:
        return 0


def _relative_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
