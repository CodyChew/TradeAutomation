from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = WORKSPACE_ROOT / "scripts" / "verify_lpfs_structured_command.py"
SPEC = importlib.util.spec_from_file_location("verify_lpfs_structured_command", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class Stage5StructuredVerifierTests(unittest.TestCase):
    def _bundle(
        self,
        root: Path,
        *,
        step: str = "precheck",
        stdout: str = 'LPFS_GATE3_PRECHECK_JSON={"ok":true}\n',
        stderr: str = "",
        exit_code: str = "0\n",
        include: tuple[str, ...] = ("command", "stdout", "stderr", "exit_code"),
    ) -> None:
        values = {
            "command": "powershell -File read_only.ps1\n",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
        for label in include:
            (root / f"{step}.{label}.txt").write_text(values[label], encoding="utf-8")

    def _manifest(self, root: Path, *, result: str = "PASS") -> None:
        files = []
        for path in sorted(root.iterdir()):
            if path.is_file() and path.name not in {"manifest.json", "manifest.sha256.txt"}:
                files.append(
                    {
                        "path": path.name,
                        "bytes": path.stat().st_size,
                        "sha256": verifier._sha256(path),
                    }
                )
        manifest = {"schema_version": 1, "result": result, "file_count": len(files), "files": files}
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (root / "manifest.sha256.txt").write_text(verifier._sha256(manifest_path) + "\n", encoding="ascii")
        (root / "validation_summary.json").write_text(json.dumps({"result": result}), encoding="utf-8")

    def test_structured_bundle_passes_and_preserves_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            result = verifier.verify_command_bundle(root, "precheck", "LPFS_GATE3_PRECHECK_JSON=")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["reason"], "all command artifacts and structured output verified")
            self.assertEqual(result["structured_payload"], {"ok": True})
            self.assertEqual(set(result["artifacts"]), {"command", "stdout", "stderr", "exit_code"})
            self.assertTrue(all(receipt["sha256"] for receipt in result["artifacts"].values()))

    def test_missing_artifact_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, include=("command", "stdout", "exit_code"))
            result = verifier.verify_command_bundle(root, "precheck", "LPFS_GATE3_PRECHECK_JSON=")
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("missing stderr artifact", " ".join(result["failures"]))

    def test_malformed_exit_code_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, exit_code="TIMEOUT\n")
            result = verifier.verify_command_bundle(root, "precheck", "LPFS_GATE3_PRECHECK_JSON=")
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("exit code is not an integer", " ".join(result["failures"]))

    def test_malformed_json_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, stdout="LPFS_GATE3_PRECHECK_JSON={broken}\n")
            result = verifier.verify_command_bundle(root, "precheck", "LPFS_GATE3_PRECHECK_JSON=")
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("invalid JSON", " ".join(result["failures"]))

    def test_ambiguous_stdout_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(
                root,
                stdout=(
                    'LPFS_GATE3_PRECHECK_JSON={"ok":true}\n'
                    'LPFS_GATE3_PRECHECK_JSON={"ok":false}\n'
                ),
            )
            result = verifier.verify_command_bundle(root, "precheck", "LPFS_GATE3_PRECHECK_JSON=")
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("exactly one", " ".join(result["failures"]))

    def test_nonempty_stderr_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, stderr="NativeCommandError\n")
            result = verifier.verify_command_bundle(root, "precheck", "LPFS_GATE3_PRECHECK_JSON=")
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("stderr artifact is not empty", result["failures"])

    def test_packet_manifest_and_expected_result_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            result = verifier.verify_packet(
                root,
                [("precheck", "LPFS_GATE3_PRECHECK_JSON=")],
                expected_packet_result="PASS",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["reason"], "packet manifest, command bundles, and expected result verified")
            self.assertEqual(result["manifest"]["status"], "PASS")

    def test_manifest_tamper_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            (root / "precheck.stdout.txt").write_text("tampered\n", encoding="utf-8")
            result = verifier.verify_manifest(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(result["bad_payloads"], ["precheck.stdout.txt"])


if __name__ == "__main__":
    unittest.main()
