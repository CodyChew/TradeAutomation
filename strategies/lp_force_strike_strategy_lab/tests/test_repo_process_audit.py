from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SCRIPT_PATH = WORKSPACE_ROOT / "scripts" / "audit_repo_process.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_repo_process", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_required_files(root: Path) -> None:
    module = _load_module()
    for relative in module.CRITICAL_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        references = module.REQUIRED_REFERENCES.get(relative, ())
        anchors = module.REQUIRED_CONTEXT_ANCHORS.get(relative, ())
        text = "\n".join((relative, *references, *anchors)) + "\n"
        path.write_text(text, encoding="utf-8")
    for relative in module.CRITICAL_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


class RepoProcessAuditTests(unittest.TestCase):
    def test_audit_passes_minimal_required_tree(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_required_files(root)

            report = module.run_audit(root, tracked_paths=["README.md", "docs/reviews/example.md"])

        self.assertEqual(report.status, "pass")
        self.assertTrue(report.ok)
        self.assertEqual(report.issues, ())

    def test_audit_fails_for_missing_file_secret_pattern_and_tracked_artifact(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_required_files(root)
            (root / "docs" / "decision_log.md").unlink()
            fake_token = "123456789:" + "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi123456789"
            (root / "README.md").write_text(
                f"token {fake_token}\n",
                encoding="utf-8",
            )

            report = module.run_audit(
                root,
                tracked_paths=[
                    "README.md",
                    "reports/live_ops/status_packet.md",
                    "config.local.json",
                ],
            )

        codes = {issue.code for issue in report.issues}
        self.assertEqual(report.status, "fail")
        self.assertFalse(report.ok)
        self.assertIn("missing_critical_file", codes)
        self.assertIn("secret_pattern_telegram_bot_token", codes)
        self.assertIn("tracked_runtime_or_secret_artifact", codes)

    def test_line_limits_are_warnings_not_default_failures(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_required_files(root)
            (root / "PROJECT_STATE.md").write_text("one\ntwo\nthree\n", encoding="utf-8")

            report = module.run_audit(
                root,
                tracked_paths=["README.md"],
                line_limits={"PROJECT_STATE.md": 2},
            )

        self.assertEqual(report.status, "warn")
        self.assertTrue(report.ok)
        self.assertTrue(any(issue.code == "line_limit_exceeded" for issue in report.issues))
        self.assertTrue(all(issue.severity == "warning" for issue in report.issues))

    def test_missing_context_anchor_is_warning(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_required_files(root)
            handoff = root / "SESSION_HANDOFF.md"
            handoff.write_text(
                "SESSION_HANDOFF.md\n" + "\n".join(module.REQUIRED_REFERENCES["SESSION_HANDOFF.md"]),
                encoding="utf-8",
            )

            report = module.run_audit(root, tracked_paths=["SESSION_HANDOFF.md"])

        self.assertEqual(report.status, "warn")
        self.assertTrue(any(issue.code == "missing_context_anchor" for issue in report.issues))

    def test_stale_current_state_phrase_is_warning(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_required_files(root)
            project_state = root / "PROJECT_STATE.md"
            project_state.write_text(
                project_state.read_text(encoding="utf-8") + "\nFTMO remains contained\n",
                encoding="utf-8",
            )

            report = module.run_audit(root, tracked_paths=["PROJECT_STATE.md"])

        self.assertEqual(report.status, "warn")
        self.assertTrue(any(issue.code == "stale_current_state_phrase" for issue in report.issues))

    def test_current_workspace_audit_has_no_error_findings(self) -> None:
        module = _load_module()
        report = module.run_audit(WORKSPACE_ROOT)

        errors = [issue for issue in report.issues if issue.severity == "error"]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
