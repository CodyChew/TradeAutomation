from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = WORKSPACE_ROOT / "scripts"
STRUCTURED_SCRIPT_PATH = SCRIPTS_ROOT / "verify_lpfs_structured_command.py"
PRE_EXECUTION_SCRIPT_PATH = SCRIPTS_ROOT / "verify_lpfs_pre_execution_contract.py"
BOUNDED_STATUS_COLLECTOR_PATH = SCRIPTS_ROOT / "collect_lpfs_bounded_status_bundle.py"
GATE1_V2_PRODUCER_PATH = SCRIPTS_ROOT / "build_lpfs_stage5_gate1_v2_pre_execution.py"
TRACKED_PROFILE_PATH = WORKSPACE_ROOT / "configs" / "operations" / "lpfs_stage5_safety_contract_profiles_v1.json"
TRACKED_RESUMPTION_PROFILE_PATH = (
    WORKSPACE_ROOT / "configs" / "operations" / "lpfs_stage5_resumption_safety_contract_profiles_v2.json"
)
TRACKED_PRE_EXECUTION_CONTRACT_PATH = (
    WORKSPACE_ROOT / "configs" / "operations" / "lpfs_stage5_read_only_command_contracts_v1.json"
)
TRACKED_RESUMPTION_PRE_EXECUTION_CONTRACT_PATH = (
    WORKSPACE_ROOT / "configs" / "operations" / "lpfs_stage5_read_only_command_contracts_v2.json"
)
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_script("verify_lpfs_structured_command_tests", STRUCTURED_SCRIPT_PATH)
pre_execution = _load_script("verify_lpfs_pre_execution_contract_tests", PRE_EXECUTION_SCRIPT_PATH)
bounded_status_collector = _load_script("collect_lpfs_bounded_status_bundle_tests", BOUNDED_STATUS_COLLECTOR_PATH)
gate1_v2_producer = _load_script("build_lpfs_stage5_gate1_v2_pre_execution_tests", GATE1_V2_PRODUCER_PATH)


class Stage5StructuredVerifierTests(unittest.TestCase):
    def _bundle(
        self,
        root: Path,
        *,
        step: str = "precheck",
        stdout: str = 'LPFS_GATE3_PRECHECK_JSON={"ok":true,"nested":{"count":0}}\n',
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

    def _bounded_bundle(
        self,
        root: Path,
        *,
        step: str = "bounded_status",
        stderr: str = "",
        exit_code: int = 0,
        timed_out: bool = False,
        duplicate_marker: bool = False,
        include: tuple[str, ...] = (
            "command",
            "stdout",
            "stderr",
            "exit_code",
            "timeout",
            "status_implementation",
            "execution",
        ),
    ) -> tuple[str, str]:
        implementation = b"Write-Output 'LPFS live status'\n"
        implementation_sha = hashlib.sha256(implementation).hexdigest()
        command = "ssh lane powershell -NoProfile -EncodedCommand REVIEWED\n"
        command_path = root / f"{step}.command.txt"
        command_path.write_text(command, encoding="utf-8")
        command_sha = verifier._sha256(command_path)
        stdout = (
            f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={implementation_sha}\n"
            + (
                f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={implementation_sha}\n"
                if duplicate_marker
                else ""
            )
            + "LPFS live status\n"
        )
        execution = {
            "bundle_kind": verifier.BOUNDED_STATUS_BUNDLE_KIND,
            "command_hash_matches_expected": True,
            "command_sha256": command_sha,
            "execution_attempted": True,
            "exit_code": exit_code,
            "expected_command_sha256": command_sha,
            "remote_status_implementation_sha256_verified": True,
            "schema_version": verifier.BOUNDED_STATUS_EXECUTION_SCHEMA_VERSION,
            "status_implementation_sha256": implementation_sha,
            "status_implementation_source": verifier.BOUNDED_STATUS_SOURCE,
            "stderr_empty": not bool(stderr),
            "stdout_nonempty": True,
            "timed_out": timed_out,
            "timeout_seconds": 30,
        }
        values: dict[str, str | bytes] = {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": f"{exit_code}\n",
            "timeout": f"{str(timed_out).lower()}\n",
            "status_implementation": implementation,
            "execution": json.dumps(execution),
        }
        for label in include:
            path = root / (
                f"{step}.status_implementation.ps1"
                if label == "status_implementation"
                else f"{step}.execution.json"
                if label == "execution"
                else f"{step}.{label}.txt"
            )
            payload = values[label]
            if isinstance(payload, bytes):
                path.write_bytes(payload)
            else:
                path.write_text(payload, encoding="utf-8")
        if "command" not in include:
            command_path.unlink(missing_ok=True)
        return command_sha, implementation_sha

    def _compact_bundle(
        self,
        root: Path,
        *,
        step: str = "compact_containment",
        stderr: str = "",
        exit_code: int = 0,
        timed_out: bool = False,
        duplicate_marker: bool = False,
        include: tuple[str, ...] = (
            "command",
            "stdout",
            "stderr",
            "exit_code",
            "timeout",
            "compact_script",
            "execution",
        ),
    ) -> tuple[str, str]:
        compact_script = b"Write-Output 'LPFS_GATE1_CONTAINMENT_JSON={\"ok\":true,\"nested\":{\"count\":0}}'\n"
        compact_sha = hashlib.sha256(compact_script).hexdigest()
        command = bounded_status_collector.render_command(
            bounded_status_collector.build_remote_compact_containment_command(
                ssh_alias="lpfs-vps",
                expected_compact_script_sha256=compact_sha,
            )
        )
        command_path = root / f"{step}.command.txt"
        command_path.write_text(command, encoding="utf-8")
        command_sha = verifier._sha256(command_path)
        stdout = (
            f"LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED={compact_sha}\n"
            + (
                f"LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED={compact_sha}\n"
                if duplicate_marker
                else ""
            )
            + 'LPFS_GATE1_CONTAINMENT_JSON={"ok":true,"nested":{"count":0}}\n'
        )
        execution = {
            "bundle_kind": verifier.COMPACT_CONTAINMENT_BUNDLE_KIND,
            "command_hash_matches_expected": True,
            "command_length": len(command),
            "command_length_within_safe_threshold": True,
            "command_sha256": command_sha,
            "compact_script_hash_matches_expected": True,
            "compact_script_sha256": compact_sha,
            "compact_script_source": verifier.COMPACT_CONTAINMENT_SOURCE,
            "execution_attempted": True,
            "exit_code": exit_code,
            "expected_command_sha256": command_sha,
            "expected_compact_script_sha256": compact_sha,
            "remote_compact_script_sha256_verified": True,
            "schema_version": verifier.COMPACT_CONTAINMENT_EXECUTION_SCHEMA_VERSION,
            "stderr_empty": not bool(stderr),
            "stdout_nonempty": True,
            "timed_out": timed_out,
            "timeout_seconds": 30,
        }
        values: dict[str, str | bytes] = {
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": f"{exit_code}\n",
            "timeout": f"{str(timed_out).lower()}\n",
            "compact_script": compact_script,
            "execution": json.dumps(execution),
        }
        for label in include:
            path = root / (
                f"{step}.remote.ps1"
                if label == "compact_script"
                else f"{step}.execution.json"
                if label == "execution"
                else f"{step}.{label}.txt"
            )
            payload = values[label]
            if isinstance(payload, bytes):
                path.write_bytes(payload)
            else:
                path.write_text(payload, encoding="utf-8")
        if "command" not in include:
            command_path.unlink(missing_ok=True)
        return command_sha, compact_sha

    def _write_manifest_from_files(self, root: Path, *, result: str = "PASS", excluded: tuple[str, ...] = ()) -> None:
        files = []
        for path in sorted(root.iterdir()):
            if (
                path.is_file()
                and path.name not in {"manifest.json", "manifest.sha256.txt"}
                and path.name not in excluded
            ):
                files.append(
                    {
                        "path": path.name,
                        "bytes": path.stat().st_size,
                        "sha256": verifier._sha256(path),
                    }
                )
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps({"schema_version": 1, "result": result, "file_count": len(files), "files": files}),
            encoding="utf-8",
        )
        (root / "manifest.sha256.txt").write_text(verifier._sha256(manifest_path) + "\n", encoding="ascii")

    def _manifest(self, root: Path, *, result: str = "PASS", excluded: tuple[str, ...] = ()) -> None:
        (root / "validation_summary.json").write_text(json.dumps({"result": result}), encoding="utf-8")
        self._write_manifest_from_files(root, result=result, excluded=excluded)

    def _profile_document(
        self,
        *,
        expectations: dict[str, object] | None = None,
        required_fields: list[str] | None = None,
        required_steps: list[str] | None = None,
        steps: dict[str, object] | None = None,
        profile_version: int = 1,
        runtime_integrity_steps: list[str] | None = None,
    ) -> dict[str, object]:
        expectation_values = {"ok": True, "nested.count": 0} if expectations is None else expectations
        step_values = (
            {
                "precheck": {
                    "contract_version": 1,
                    "marker": "LPFS_GATE3_PRECHECK_JSON=",
                    "required_expectation_fields": (
                        list(expectation_values) if required_fields is None else required_fields
                    ),
                    "expectations": expectation_values,
                }
            }
            if steps is None
            else steps
        )
        profile: dict[str, object] = {
            "profile_version": profile_version,
            "gate": "test_gate",
            "expected_packet_result": "PASS",
            "required_steps": ["precheck"] if required_steps is None else required_steps,
            "steps": step_values,
        }
        if profile_version >= 2:
            profile["runtime_integrity_steps"] = (
                ["precheck"] if runtime_integrity_steps is None else runtime_integrity_steps
            )
        return {
            "schema_version": 1,
            "profiles": {
                "test_profile_v1": profile
            },
        }

    def _profile_file(self, root: Path, **kwargs: object) -> Path:
        path = root / "profile.json"
        path.write_text(json.dumps(self._profile_document(**kwargs)), encoding="utf-8")
        return path

    def _verify_packet(
        self,
        root: Path,
        *,
        profile_path: Path | None = None,
        profile_kwargs: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if profile_path is None:
            profile_path = self._profile_file(root, **(profile_kwargs or {}))
        return verifier.verify_packet(
            root,
            safety_profile_path=profile_path,
            profile_id="test_profile_v1",
            expected_profile_sha256=verifier._sha256(profile_path),
        )

    def _verify_bundle(self, root: Path, **kwargs: object) -> dict[str, object]:
        self._manifest(root)
        manifest = verifier.verify_manifest(root)
        return verifier.verify_command_bundle(
            root,
            "precheck",
            "LPFS_GATE3_PRECHECK_JSON=",
            expectations={"ok": True},
            required_expectation_fields=["ok"],
            declared_artifacts=manifest["declared_artifacts"],
            **kwargs,
        )

    def _verify_bounded_bundle(
        self,
        root: Path,
        command_sha: str,
        implementation_sha: str,
    ) -> dict[str, object]:
        self._manifest(root)
        manifest = verifier.verify_manifest(root)
        return verifier.verify_bounded_status_bundle(
            root,
            "bounded_status",
            expected_command_sha256=command_sha,
            expected_status_implementation_sha256=implementation_sha,
            required_stdout_substrings=[
                f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={implementation_sha}",
                "LPFS live status",
            ],
            declared_artifacts=manifest["declared_artifacts"],
        )

    def _verify_compact_bundle(
        self,
        root: Path,
        command_sha: str,
        compact_sha: str,
    ) -> dict[str, object]:
        self._manifest(root)
        manifest = verifier.verify_manifest(root)
        return verifier.verify_compact_containment_bundle(
            root,
            "compact_containment",
            "LPFS_GATE1_CONTAINMENT_JSON=",
            expectations={"ok": True, "nested.count": 0},
            required_expectation_fields=["ok", "nested.count"],
            expected_command_sha256=command_sha,
            expected_compact_script_sha256=compact_sha,
            declared_artifacts=manifest["declared_artifacts"],
        )

    def test_structured_bundle_passes_and_preserves_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            result = self._verify_packet(root)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["proof_scope"], "post_execution_evidence_only")
            self.assertFalse(result["proves_command_was_safe_to_run"])
            self.assertTrue(result["pre_execution_read_only_contract_required"])
            self.assertTrue(all(item["matched"] for item in result["steps"][0]["expectations"]))

    def test_missing_artifact_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, include=("command", "stdout", "exit_code"))
            result = self._verify_bundle(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("missing stderr artifact", " ".join(result["failures"]))

    def test_malformed_exit_code_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, exit_code="TIMEOUT\n")
            result = self._verify_bundle(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("exit code is not an integer", " ".join(result["failures"]))

    def test_ambiguous_stdout_and_nonempty_stderr_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(
                root,
                stdout='LPFS_GATE3_PRECHECK_JSON={"ok":true}\nLPFS_GATE3_PRECHECK_JSON={"ok":false}\n',
                stderr="NativeCommandError\n",
            )
            result = self._verify_bundle(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("exactly one", " ".join(result["failures"]))
            self.assertIn("stderr artifact is not empty", result["failures"])

    def test_bounded_status_bundle_passes_with_embedded_reviewed_implementation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            command_sha, implementation_sha = self._bounded_bundle(root)
            result = self._verify_bounded_bundle(root, command_sha, implementation_sha)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["execution"]["status_implementation_sha256"], implementation_sha)

    def test_bounded_status_bundle_fails_closed_on_exit_timeout_missing_output_or_stderr(self) -> None:
        cases = (
            ("nonzero exit", {"exit_code": 9}, "exit code is nonzero"),
            ("timeout", {"exit_code": 124, "timed_out": True}, "timed out"),
            (
                "missing output",
                {
                    "include": (
                        "command",
                        "stderr",
                        "exit_code",
                        "timeout",
                        "status_implementation",
                        "execution",
                    )
                },
                "missing stdout artifact",
            ),
            ("stderr", {"stderr": "NativeCommandError\n"}, "stderr artifact is not empty"),
            (
                "duplicate verification marker",
                {"duplicate_marker": True},
                "exactly one implementation verification marker",
            ),
        )
        for label, bundle_kwargs, pattern in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                command_sha, implementation_sha = self._bounded_bundle(root, **bundle_kwargs)
                result = self._verify_bounded_bundle(root, command_sha, implementation_sha)
                self.assertEqual(result["status"], "STOPPED")
                self.assertIn(pattern, " ".join(result["failures"]))

    def test_bounded_status_bundle_rejects_vps_resident_status_script_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            command_sha, implementation_sha = self._bounded_bundle(root)
            command_path = root / "bounded_status.command.txt"
            command_path.write_text(
                "ssh lane powershell -EncodedCommand X -File C:\\TradeAutomation\\scripts\\Get-LpfsLiveStatus.ps1\n",
                encoding="utf-8",
            )
            execution_path = root / "bounded_status.execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            command_sha = verifier._sha256(command_path)
            execution["command_sha256"] = command_sha
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            result = self._verify_bounded_bundle(root, command_sha, implementation_sha)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("unverified VPS-resident", " ".join(result["failures"]))

    def test_compact_containment_bundle_passes_with_stdin_script_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            command_sha, compact_sha = self._compact_bundle(root)
            result = self._verify_compact_bundle(root, command_sha, compact_sha)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["execution"]["compact_script_sha256"], compact_sha)
            command = (root / "compact_containment.command.txt").read_text(encoding="utf-8")
            script = (root / "compact_containment.remote.ps1").read_text(encoding="utf-8")
            self.assertLess(len(command), verifier.COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH)
            self.assertNotIn(script.strip(), command)

    def test_compact_containment_bundle_fails_closed_on_incomplete_artifacts(self) -> None:
        cases = (
            ("missing command", ("stdout", "stderr", "exit_code", "timeout", "compact_script", "execution")),
            ("missing stdout", ("command", "stderr", "exit_code", "timeout", "compact_script", "execution")),
            ("missing script", ("command", "stdout", "stderr", "exit_code", "timeout", "execution")),
            ("missing execution", ("command", "stdout", "stderr", "exit_code", "timeout", "compact_script")),
        )
        for label, include in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                command_sha, compact_sha = self._compact_bundle(root, include=include)
                result = self._verify_compact_bundle(root, command_sha, compact_sha)
                self.assertEqual(result["status"], "STOPPED")
                self.assertIn("missing", " ".join(result["failures"]))

    def test_compact_containment_bundle_rejects_tampered_artifacts(self) -> None:
        mutations = {
            "command": lambda root: (root / "compact_containment.command.txt").write_text(
                "ssh wrong powershell -EncodedCommand REVIEWED\n",
                encoding="utf-8",
            ),
            "script": lambda root: (root / "compact_containment.remote.ps1").write_text(
                "Write-Output 'tampered'\n",
                encoding="utf-8",
            ),
            "stdout": lambda root: (root / "compact_containment.stdout.txt").write_text(
                'LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED=0000\nLPFS_GATE1_CONTAINMENT_JSON={"ok":true,"nested":{"count":0}}\n',
                encoding="utf-8",
            ),
            "stderr": lambda root: (root / "compact_containment.stderr.txt").write_text(
                "NativeCommandError\n",
                encoding="utf-8",
            ),
            "exit_code": lambda root: (root / "compact_containment.exit_code.txt").write_text(
                "9\n",
                encoding="utf-8",
            ),
            "timeout": lambda root: (root / "compact_containment.timeout.txt").write_text(
                "true\n",
                encoding="utf-8",
            ),
            "execution": lambda root: (root / "compact_containment.execution.json").write_text(
                "{}",
                encoding="utf-8",
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                command_sha, compact_sha = self._compact_bundle(root)
                self._manifest(root)
                mutate(root)
                manifest = verifier.verify_manifest(root)
                result = verifier.verify_compact_containment_bundle(
                    root,
                    "compact_containment",
                    "LPFS_GATE1_CONTAINMENT_JSON=",
                    expectations={"ok": True, "nested.count": 0},
                    required_expectation_fields=["ok", "nested.count"],
                    expected_command_sha256=command_sha,
                    expected_compact_script_sha256=compact_sha,
                    declared_artifacts=manifest["declared_artifacts"],
                )
                self.assertEqual(result["status"], "STOPPED")

    def test_unsafe_payload_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, stdout='LPFS_GATE3_PRECHECK_JSON={"ok":false,"nested":{"count":0}}\n')
            self._manifest(root)
            result = self._verify_packet(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("safety expectation mismatch", " ".join(result["failures"]))

    def test_incomplete_expectation_set_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            result = self._verify_packet(
                root,
                profile_kwargs={"expectations": {"ok": True}, "required_fields": ["ok", "nested.count"]},
            )
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("expectation set mismatch", result["reason"])

    def test_incomplete_step_set_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            result = self._verify_packet(root, profile_kwargs={"required_steps": ["precheck", "strict"]})
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("step set mismatch", result["reason"])

    def test_unsupported_profile_version_and_unknown_field_stop(self) -> None:
        for mutate, pattern in (
            (lambda document: document["profiles"]["test_profile_v1"].update({"profile_version": 3}), "unsupported"),
            (lambda document: document["profiles"]["test_profile_v1"].update({"typo": True}), "keys mismatch"),
        ):
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._bundle(root)
                self._manifest(root)
                document = self._profile_document()
                mutate(document)
                profile_path = root / "profile.json"
                profile_path.write_text(json.dumps(document), encoding="utf-8")
                result = self._verify_packet(root, profile_path=profile_path)
                self.assertEqual(result["status"], "STOPPED")
                self.assertIn(pattern, result["reason"])

    def test_gate1_profile_requires_exact_position_inventories(self) -> None:
        profile = verifier.load_safety_profile(TRACKED_PROFILE_PATH, "stage5_gate1_dual_lane_contained_v1")
        ftmo = profile["steps"]["FTMO/strict_mt5_probe"]["expectations"]["strategy_positions"]
        ic = profile["steps"]["IC/strict_mt5_probe"]["expectations"]["strategy_positions"]
        self.assertEqual([item["ticket"] for item in ftmo], [259140457, 261720587, 262778049])
        self.assertEqual([item["ticket"] for item in ic], [4423126597, 4431268523])
        self.assertTrue(all({"ticket", "symbol", "magic", "comment", "volume", "sl", "tp"} <= set(item) for item in ftmo + ic))

    def test_future_gate1_and_separate_gate3_resumption_profiles_are_complete(self) -> None:
        profile_ids = (
            "stage5_gate1_dual_lane_contained_v2",
            "stage5_ftmo_gate3_resumption_v1",
            "stage5_ic_gate3_resumption_v1",
        )
        profiles = {
            profile_id: verifier.load_safety_profile(TRACKED_RESUMPTION_PROFILE_PATH, profile_id)
            for profile_id in profile_ids
        }
        gate1 = profiles["stage5_gate1_dual_lane_contained_v2"]
        self.assertEqual(gate1["profile_version"], 2)
        self.assertEqual(
            gate1["runtime_integrity_steps"],
            ["FTMO/compact_containment", "IC/compact_containment"],
        )
        self.assertEqual(gate1["steps"]["FTMO/bounded_status"]["contract_version"], 2)
        self.assertEqual(gate1["steps"]["IC/bounded_status"]["contract_version"], 2)
        self.assertTrue(gate1["steps"]["FTMO/compact_containment"]["expectations"]["tracked_worktree_clean"])
        self.assertTrue(gate1["steps"]["IC/compact_containment"]["expectations"]["tracked_worktree_clean"])
        self.assertEqual(
            [row["ticket"] for row in gate1["steps"]["FTMO/strict_mt5_probe"]["expectations"]["strategy_positions"]],
            [259140457, 261720587, 262778049],
        )
        self.assertEqual(
            [row["ticket"] for row in gate1["steps"]["IC/strict_mt5_probe"]["expectations"]["strategy_positions"]],
            [4423126597, 4431268523],
        )
        implementation = (SCRIPTS_ROOT / "Get-LpfsLiveStatus.ps1").read_bytes()
        implementation_sha = hashlib.sha256(implementation).hexdigest()

        def expected_command_sha(lane: str, journal_lines: int, log_lines: int) -> str:
            lane_args = (
                {
                    "ssh_alias": "lpfs-vps",
                    "runtime_root": r"C:\TradeAutomationRuntime",
                    "state_file_name": "lpfs_live_state.json",
                    "journal_file_name": "lpfs_live_journal.jsonl",
                    "heartbeat_file_name": "lpfs_live_heartbeat.json",
                    "log_filter": "lpfs_live_*.log",
                }
                if lane == "ftmo"
                else {
                    "ssh_alias": "lpfs-ic-vps",
                    "runtime_root": r"C:\TradeAutomationRuntimeIC",
                    "state_file_name": "lpfs_ic_live_state.json",
                    "journal_file_name": "lpfs_ic_live_journal.jsonl",
                    "heartbeat_file_name": "lpfs_ic_live_heartbeat.json",
                    "log_filter": "lpfs_ic_live_*.log",
                }
            )
            command = bounded_status_collector.build_remote_status_command(
                status_implementation=implementation,
                expected_status_sha256=implementation_sha,
                journal_lines=journal_lines,
                log_lines=log_lines,
                **lane_args,
            )
            return hashlib.sha256(bounded_status_collector.render_command(command).encode("utf-8")).hexdigest()

        self.assertEqual(
            gate1["steps"]["FTMO/bounded_status"]["expected_command_sha256"],
            expected_command_sha("ftmo", 5, 10),
        )
        self.assertEqual(
            gate1["steps"]["IC/bounded_status"]["expected_command_sha256"],
            expected_command_sha("ic", 5, 10),
        )

        for lane in ("ftmo", "ic"):
            profile = profiles[f"stage5_{lane}_gate3_resumption_v1"]
            self.assertEqual(profile["profile_version"], 2)
            self.assertEqual(profile["expected_packet_result"], "PASS")
            self.assertEqual(profile["runtime_integrity_steps"], ["precheck", "postcheck"])
            self.assertEqual(
                list(profile["steps"]),
                [
                    "precheck",
                    "pre_bounded_status",
                    "pre_strict_mt5",
                    "postcheck",
                    "post_bounded_status",
                    "post_strict_mt5",
                ],
            )
            self.assertTrue(profile["steps"]["precheck"]["expectations"]["critical_runtime_file_hashes"])
            self.assertTrue(profile["steps"]["postcheck"]["expectations"]["critical_runtime_file_hashes"])
            self.assertTrue(profile["steps"]["precheck"]["expectations"]["tracked_worktree_clean"])
            self.assertTrue(profile["steps"]["postcheck"]["expectations"]["tracked_worktree_clean"])
            self.assertEqual(profile["steps"]["pre_bounded_status"]["contract_version"], 2)
            self.assertEqual(profile["steps"]["post_bounded_status"]["contract_version"], 2)
            self.assertFalse(profile["steps"]["postcheck"]["expectations"]["kill_switch_active"])
            self.assertEqual(
                profile["steps"]["pre_bounded_status"]["expected_command_sha256"],
                expected_command_sha(lane, 10, 20),
            )
            self.assertEqual(
                profile["steps"]["post_bounded_status"]["expected_command_sha256"],
                expected_command_sha(lane, 20, 30),
            )

    def test_modified_tracked_profile_is_rejected_by_pinned_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            document = verifier._strict_json_file(TRACKED_PROFILE_PATH)
            document["profiles"]["stage5_gate1_dual_lane_contained_v1"]["steps"]["FTMO/strict_mt5_probe"][
                "expectations"
            ]["strategy_positions"] = []
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pinned reviewed candidate"):
                verifier.load_safety_profile(path, "stage5_gate1_dual_lane_contained_v1")

    def test_same_count_different_position_inventory_stops(self) -> None:
        expected = [{"ticket": 1}, {"ticket": 2}]
        actual = [{"ticket": 1}, {"ticket": 3}]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(
                root,
                stdout=f"LPFS_GATE3_PRECHECK_JSON={json.dumps({'strategy_positions': actual})}\n",
            )
            self._manifest(root)
            result = self._verify_packet(
                root,
                profile_kwargs={"expectations": {"strategy_positions": expected}},
            )
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("strategy_positions", " ".join(result["failures"]))

    def test_same_head_tracked_runtime_file_drift_stops(self) -> None:
        expected_hashes = {"scripts/run_lpfs_live_forever.ps1": "a" * 64}
        expectations = {
            "repo_head": "same-reviewed-head",
            "critical_runtime_file_hashes": expected_hashes,
            "tracked_worktree_clean": True,
            "tracked_worktree_status": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(
                root,
                stdout=(
                    "LPFS_GATE3_PRECHECK_JSON="
                    + json.dumps(
                        {
                            "repo_head": "same-reviewed-head",
                            "critical_runtime_file_hashes": expected_hashes,
                            "tracked_worktree_clean": False,
                            "tracked_worktree_status": [" M scripts/run_lpfs_live_forever.ps1"],
                        }
                    )
                    + "\n"
                ),
            )
            self._manifest(root)
            result = self._verify_packet(
                root,
                profile_kwargs={
                    "expectations": expectations,
                    "profile_version": 2,
                },
            )
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("tracked_worktree_clean", " ".join(result["failures"]))

    def test_future_profile_requires_runtime_integrity_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root, stdout='LPFS_GATE3_PRECHECK_JSON={"repo_head":"head","tracked_worktree_clean":true}\n')
            self._manifest(root)
            result = self._verify_packet(
                root,
                profile_kwargs={
                    "profile_version": 2,
                    "expectations": {"repo_head": "head", "tracked_worktree_clean": True},
                },
            )
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("tracked_worktree_clean=true or exact critical hashes", result["reason"])

    def test_exact_position_inventory_is_order_independent(self) -> None:
        expected = [{"ticket": 1, "symbol": "A"}, {"ticket": 2, "symbol": "B"}]
        actual = list(reversed(expected))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(
                root,
                stdout=f"LPFS_GATE3_PRECHECK_JSON={json.dumps({'strategy_positions': actual})}\n",
            )
            self._manifest(root)
            result = self._verify_packet(
                root,
                profile_kwargs={"expectations": {"strategy_positions": expected}},
            )
            self.assertEqual(result["status"], "PASS")
            expectation = result["steps"][0]["expectations"][0]
            self.assertEqual(expectation["comparison"], "exact_inventory_order_independent")

    def test_zero_step_profile_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            result = self._verify_packet(root, profile_kwargs={"required_steps": [], "steps": {}})
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("required_steps must be a nonempty list", result["reason"])

    def test_undeclared_checked_artifact_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root, excluded=("precheck.command.txt",))
            result = self._verify_packet(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("undeclared command artifact", " ".join(result["failures"]))

    def test_duplicate_json_keys_stop_in_manifest_summary_payload_and_profile(self) -> None:
        for target in ("manifest", "summary", "payload", "profile"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._bundle(root)
                self._manifest(root)
                profile_path = self._profile_file(root)
                if target == "manifest":
                    manifest_path = root / "manifest.json"
                    manifest_path.write_text('{"result":"PASS","result":"STOPPED","file_count":0,"files":[]}', encoding="utf-8")
                    (root / "manifest.sha256.txt").write_text(verifier._sha256(manifest_path) + "\n", encoding="ascii")
                elif target == "summary":
                    (root / "validation_summary.json").write_text('{"result":"PASS","result":"STOPPED"}', encoding="utf-8")
                    self._write_manifest_from_files(root)
                elif target == "payload":
                    self._bundle(root, stdout='LPFS_GATE3_PRECHECK_JSON={"ok":true,"ok":false,"nested":{"count":0}}\n')
                    self._write_manifest_from_files(root)
                else:
                    profile_path.write_text(
                        '{"schema_version":1,"schema_version":1,"profiles":{}}',
                        encoding="utf-8",
                    )
                result = self._verify_packet(root, profile_path=profile_path)
                self.assertEqual(result["status"], "STOPPED")
                self.assertIn("duplicate JSON key", result["reason"])

    def test_nonstandard_json_stops_in_manifest_summary_payload_and_profile(self) -> None:
        for target in ("manifest", "summary", "payload", "profile"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._bundle(root)
                self._manifest(root)
                profile_path = self._profile_file(root)
                if target == "manifest":
                    manifest_path = root / "manifest.json"
                    manifest_path.write_text('{"result":"PASS","file_count":NaN,"files":[]}', encoding="utf-8")
                    (root / "manifest.sha256.txt").write_text(verifier._sha256(manifest_path) + "\n", encoding="ascii")
                elif target == "summary":
                    (root / "validation_summary.json").write_text('{"result":"PASS","value":Infinity}', encoding="utf-8")
                    self._write_manifest_from_files(root)
                elif target == "payload":
                    self._bundle(root, stdout='LPFS_GATE3_PRECHECK_JSON={"ok":true,"nested":{"count":NaN}}\n')
                    self._write_manifest_from_files(root)
                else:
                    profile_path.write_text(
                        '{"schema_version":1,"profiles":{"test_profile_v1":{"profile_version":NaN}}}',
                        encoding="utf-8",
                    )
                result = self._verify_packet(root, profile_path=profile_path)
                self.assertEqual(result["status"], "STOPPED")
                self.assertIn("non-standard JSON constant", result["reason"])

    def test_manifest_tamper_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._bundle(root)
            self._manifest(root)
            (root / "precheck.stdout.txt").write_text("tampered\n", encoding="utf-8")
            result = verifier.verify_manifest(root)
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(result["bad_payloads"], ["precheck.stdout.txt"])

    def test_malformed_cli_writes_structured_stopped_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(tmpdir)
            output = Path(output_dir) / "receipt.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                exit_code = verifier.main(["--packet", str(root), "--output", str(output)])
            self.assertEqual(exit_code, 2)
            receipt = verifier._strict_json_file(output)
            self.assertEqual(receipt["status"], "STOPPED")
            self.assertFalse(receipt["proves_command_was_safe_to_run"])

    def test_receipt_inside_packet_is_rejected_without_packet_mutation(self) -> None:
        output = verifier._fallback_receipt_path()
        output.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                self._bundle(root)
                self._manifest(root)
                profile_path = self._profile_file(root)
                packet_output = root / "receipt.json"
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    exit_code = verifier.main(
                        [
                            "--packet",
                            str(root),
                            "--safety-profile",
                            str(profile_path),
                            "--profile-id",
                            "test_profile_v1",
                            "--output",
                            str(packet_output),
                        ]
                    )
                self.assertEqual(exit_code, 2)
                self.assertFalse(packet_output.exists())
                receipt = verifier._strict_json_file(output)
                self.assertIn("outside the immutable packet root", receipt["reason"])
        finally:
            output.unlink(missing_ok=True)


class Stage5BoundedStatusCollectorTests(unittest.TestCase):
    def _collector_args(self, implementation: bytes) -> dict[str, object]:
        return {
            "ssh_alias": "lpfs-vps",
            "status_implementation": implementation,
            "expected_status_sha256": hashlib.sha256(implementation).hexdigest(),
            "runtime_root": r"C:\TradeAutomationRuntime",
            "state_file_name": "state.json",
            "journal_file_name": "journal.jsonl",
            "heartbeat_file_name": "heartbeat.json",
            "log_filter": "*.log",
            "journal_lines": 5,
            "log_lines": 10,
        }

    def _expected_command_sha(self, args: dict[str, object]) -> str:
        command = bounded_status_collector.build_remote_status_command(**args)
        return hashlib.sha256(bounded_status_collector.render_command(command).encode("utf-8")).hexdigest()

    def _expected_compact_command_sha(self, *, ssh_alias: str, compact_sha: str) -> str:
        command = bounded_status_collector.build_remote_compact_containment_command(
            ssh_alias=ssh_alias,
            expected_compact_script_sha256=compact_sha,
        )
        return hashlib.sha256(bounded_status_collector.render_command(command).encode("utf-8")).hexdigest()

    def test_remote_command_executes_embedded_hash_approved_status_implementation(self) -> None:
        implementation = b"Write-Output 'LPFS live status'\n"
        args = self._collector_args(implementation)
        implementation_sha = args["expected_status_sha256"]
        command = bounded_status_collector.build_remote_status_command(**args)
        rendered = bounded_status_collector.render_command(command)
        self.assertIn("-EncodedCommand", rendered)
        self.assertNotIn("Get-LpfsLiveStatus.ps1", rendered)
        bootstrap = base64.b64decode(command[-1]).decode("utf-16le")
        self.assertIn(implementation_sha, bootstrap)
        self.assertIn("ScriptBlock]::Create", bootstrap)
        self.assertNotIn("Set-Content", bootstrap)
        self.assertNotIn("Get-LpfsLiveStatus.ps1", bootstrap)

    def test_collector_preserves_success_bundle_without_remote_file_execution(self) -> None:
        implementation = b"Write-Output 'LPFS live status'\n"
        implementation_sha = hashlib.sha256(implementation).hexdigest()
        stdout = f"LPFS_STATUS_IMPLEMENTATION_SHA256_VERIFIED={implementation_sha}\nLPFS live status\n"
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        command_args = self._collector_args(implementation)
        expected_command_sha = self._expected_command_sha(command_args)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            status_script = root / "status.ps1"
            status_script.write_bytes(implementation)
            output = root / "bundle"
            with mock.patch.object(bounded_status_collector.subprocess, "run", return_value=completed):
                result = bounded_status_collector.collect_status_bundle(
                    output_root=output,
                    step_name="FTMO/bounded_status",
                    ssh_alias="lpfs-vps",
                    status_script_path=status_script,
                    expected_status_sha256=implementation_sha,
                    expected_command_sha256=expected_command_sha,
                    runtime_root=r"C:\TradeAutomationRuntime",
                    state_file_name="state.json",
                    journal_file_name="journal.jsonl",
                    heartbeat_file_name="heartbeat.json",
                    log_filter="*.log",
                    journal_lines=5,
                    log_lines=10,
                    timeout_seconds=30,
                )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual((output / "FTMO" / "bounded_status.timeout.txt").read_text().strip(), "false")
            command = (output / "FTMO" / "bounded_status.command.txt").read_text()
            self.assertNotIn("Get-LpfsLiveStatus.ps1", command)

    def test_command_parameter_drift_stops_before_ssh_execution(self) -> None:
        implementation = b"Write-Output 'LPFS live status'\n"
        baseline = self._collector_args(implementation)
        expected_command_sha = self._expected_command_sha(baseline)
        mutations = {
            "ssh alias": {"ssh_alias": "wrong-vps"},
            "runtime root": {"runtime_root": r"C:\WrongRuntime"},
            "state filename": {"state_file_name": "wrong_state.json"},
            "journal filename": {"journal_file_name": "wrong_journal.jsonl"},
            "heartbeat filename": {"heartbeat_file_name": "wrong_heartbeat.json"},
            "log filter": {"log_filter": "wrong_*.log"},
            "journal line limit": {"journal_lines": 6},
            "log line limit": {"log_lines": 11},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                status_script = root / "status.ps1"
                status_script.write_bytes(implementation)
                args = dict(baseline)
                args.update(mutation)
                args.pop("status_implementation")
                args.pop("expected_status_sha256")
                with mock.patch.object(bounded_status_collector.subprocess, "run") as run:
                    result = bounded_status_collector.collect_status_bundle(
                        output_root=root / "bundle",
                        step_name="FTMO/bounded_status",
                        status_script_path=status_script,
                        expected_status_sha256=hashlib.sha256(implementation).hexdigest(),
                        expected_command_sha256=expected_command_sha,
                        timeout_seconds=30,
                        **args,
                    )
                run.assert_not_called()
                self.assertEqual(result["status"], "STOPPED")
                self.assertFalse(result["execution"]["execution_attempted"])
                self.assertFalse(result["execution"]["command_hash_matches_expected"])
                self.assertIn("SSH was not invoked", result["reason"])
                receipt = json.loads(
                    (root / "bundle" / "FTMO" / "bounded_status.execution.json").read_text(encoding="utf-8")
                )
                self.assertFalse(receipt["execution_attempted"])

    def test_compact_containment_command_uses_stdin_and_stays_below_safe_length(self) -> None:
        script = b"Write-Output 'LPFS_GATE1_CONTAINMENT_JSON={}'\n"
        compact_sha = hashlib.sha256(script).hexdigest()
        command = bounded_status_collector.build_remote_compact_containment_command(
            ssh_alias="lpfs-vps",
            expected_compact_script_sha256=compact_sha,
        )
        rendered = bounded_status_collector.render_command(command)
        bootstrap = base64.b64decode(command[-1]).decode("utf-16le")
        self.assertLess(len(rendered), bounded_status_collector.COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH)
        self.assertIn("[Console]::In.ReadToEnd()", bootstrap)
        self.assertIn(compact_sha, bootstrap)
        self.assertNotIn(script.decode("utf-8").strip(), rendered)
        self.assertNotIn(base64.b64encode(script).decode("ascii"), rendered)
        self.assertNotIn("Set-Content", bootstrap)

    def test_compact_containment_collector_preserves_success_bundle(self) -> None:
        script = b"Write-Output 'LPFS_GATE1_CONTAINMENT_JSON={}'\n"
        compact_sha = hashlib.sha256(script).hexdigest()
        stdout = (
            f"LPFS_COMPACT_CONTAINMENT_SCRIPT_SHA256_VERIFIED={compact_sha}\n"
            "LPFS_GATE1_CONTAINMENT_JSON={}\n"
        )
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
        expected_command_sha = self._expected_compact_command_sha(ssh_alias="lpfs-vps", compact_sha=compact_sha)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compact_script = root / "compact.ps1"
            compact_script.write_bytes(script)
            output = root / "bundle"
            with mock.patch.object(bounded_status_collector.subprocess, "run", return_value=completed):
                result = bounded_status_collector.collect_compact_containment_bundle(
                    output_root=output,
                    step_name="FTMO/compact_containment",
                    ssh_alias="lpfs-vps",
                    compact_script_path=compact_script,
                    expected_compact_script_sha256=compact_sha,
                    expected_command_sha256=expected_command_sha,
                    timeout_seconds=30,
                )
            self.assertEqual(result["status"], "PASS")
            execution = json.loads(
                (output / "FTMO" / "compact_containment.execution.json").read_text(encoding="utf-8")
            )
            self.assertTrue(execution["execution_attempted"])
            self.assertTrue(execution["remote_compact_script_sha256_verified"])
            command = (output / "FTMO" / "compact_containment.command.txt").read_text(encoding="utf-8")
            self.assertLess(len(command), bounded_status_collector.COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH)
            self.assertNotIn(script.decode("utf-8").strip(), command)

    def test_compact_containment_hash_mismatch_stops_before_ssh_execution(self) -> None:
        script = b"Write-Output 'LPFS_GATE1_CONTAINMENT_JSON={}'\n"
        compact_sha = hashlib.sha256(script).hexdigest()
        wrong_compact_sha = "0" * 64
        baseline_command_sha = self._expected_compact_command_sha(ssh_alias="lpfs-vps", compact_sha=compact_sha)
        wrong_script_command_sha = self._expected_compact_command_sha(
            ssh_alias="lpfs-vps",
            compact_sha=wrong_compact_sha,
        )
        cases = {
            "wrong command hash": {
                "expected_compact_script_sha256": compact_sha,
                "expected_command_sha256": "1" * 64,
            },
            "wrong script hash": {
                "expected_compact_script_sha256": wrong_compact_sha,
                "expected_command_sha256": wrong_script_command_sha,
            },
            "wrong ssh alias": {
                "ssh_alias": "wrong-vps",
                "expected_compact_script_sha256": compact_sha,
                "expected_command_sha256": baseline_command_sha,
            },
        }
        for label, overrides in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                compact_script = root / "compact.ps1"
                compact_script.write_bytes(script)
                kwargs = {
                    "output_root": root / "bundle",
                    "step_name": "FTMO/compact_containment",
                    "ssh_alias": "lpfs-vps",
                    "compact_script_path": compact_script,
                    "expected_compact_script_sha256": compact_sha,
                    "expected_command_sha256": baseline_command_sha,
                    "timeout_seconds": 30,
                }
                kwargs.update(overrides)
                with mock.patch.object(bounded_status_collector.subprocess, "run") as run:
                    result = bounded_status_collector.collect_compact_containment_bundle(**kwargs)
                run.assert_not_called()
                self.assertEqual(result["status"], "STOPPED")
                self.assertIn("SSH was not invoked", result["reason"])
                execution = json.loads(
                    (root / "bundle" / "FTMO" / "compact_containment.execution.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertFalse(execution["execution_attempted"])

    def test_compact_containment_cli_dispatches_to_reviewed_collector_path(self) -> None:
        script = b"Write-Output 'LPFS_GATE1_CONTAINMENT_JSON={}'\n"
        compact_sha = hashlib.sha256(script).hexdigest()
        expected_command_sha = self._expected_compact_command_sha(ssh_alias="lpfs-vps", compact_sha=compact_sha)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compact_script = root / "compact.ps1"
            compact_script.write_bytes(script)
            output_root = root / "bundle"
            with mock.patch.object(
                bounded_status_collector,
                "collect_compact_containment_bundle",
                return_value={"status": "PASS", "schema_version": 1},
            ) as collect, contextlib.redirect_stdout(io.StringIO()):
                exit_code = bounded_status_collector.main(
                    [
                        "--mode",
                        "compact-containment",
                        "--output-root",
                        str(output_root),
                        "--step-name",
                        "FTMO/compact_containment",
                        "--ssh-alias",
                        "lpfs-vps",
                        "--compact-script",
                        str(compact_script),
                        "--expected-compact-script-sha256",
                        compact_sha,
                        "--expected-command-sha256",
                        expected_command_sha,
                        "--timeout-seconds",
                        "30",
                        "--acknowledgement",
                        bounded_status_collector.READ_ONLY_ACKNOWLEDGEMENT,
                    ]
                )
            self.assertEqual(exit_code, 0)
            collect.assert_called_once_with(
                output_root=str(output_root),
                step_name="FTMO/compact_containment",
                ssh_alias="lpfs-vps",
                compact_script_path=str(compact_script),
                expected_compact_script_sha256=compact_sha,
                expected_command_sha256=expected_command_sha,
                timeout_seconds=30,
            )

    def test_compact_containment_cli_requires_compact_script_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with mock.patch.object(bounded_status_collector.subprocess, "run") as run:
                with self.assertRaisesRegex(SystemExit, "compact-containment mode requires"):
                    bounded_status_collector.main(
                        [
                            "--mode",
                            "compact-containment",
                            "--output-root",
                            str(root / "bundle"),
                            "--step-name",
                            "FTMO/compact_containment",
                            "--ssh-alias",
                            "lpfs-vps",
                            "--expected-command-sha256",
                            "0" * 64,
                            "--timeout-seconds",
                            "30",
                            "--acknowledgement",
                            bounded_status_collector.READ_ONLY_ACKNOWLEDGEMENT,
                        ]
                    )
            run.assert_not_called()


class Stage5Gate1V2ProducerTests(unittest.TestCase):
    def test_complete_six_step_bundle_is_local_only_and_contract_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(subprocess, "run") as run:
            root = Path(tmpdir) / "gate1_v2"
            manifest = gate1_v2_producer.build_gate1_v2_pre_execution_bundle(root)
            run.assert_not_called()

            self.assertFalse(manifest["executes_commands"])
            self.assertEqual(manifest["profile_id"], "stage5_gate1_dual_lane_contained_v2")
            self.assertEqual(manifest["contract_id"], "stage5_gate1_v2_complete_read_only_v1")
            self.assertEqual(manifest["artifact_count"], 13)

            expected_steps = {
                "FTMO/compact_containment",
                "FTMO/bounded_status",
                "FTMO/strict_mt5_probe",
                "IC/compact_containment",
                "IC/bounded_status",
                "IC/strict_mt5_probe",
            }
            produced_steps = {
                path.relative_to(root).as_posix().removesuffix(".command.txt")
                for path in root.rglob("*.command.txt")
            }
            self.assertEqual(produced_steps, expected_steps)

            contract = pre_execution.load_read_only_contract(
                TRACKED_RESUMPTION_PRE_EXECUTION_CONTRACT_PATH,
                "stage5_gate1_v2_complete_read_only_v1",
                expected_document_sha256=verifier._sha256(TRACKED_RESUMPTION_PRE_EXECUTION_CONTRACT_PATH),
            )
            result = pre_execution.verify_pre_execution_contract(root, contract)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["authorizes_execution"])
            self.assertEqual(set(result["artifacts"]), set(contract["artifacts"]))

    def test_compact_containment_emits_clean_tracked_status_and_exact_runtime_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "gate1_v2"
            gate1_v2_producer.build_gate1_v2_pre_execution_bundle(root)
            profile = verifier.load_safety_profile(
                TRACKED_RESUMPTION_PROFILE_PATH,
                "stage5_gate1_dual_lane_contained_v2",
            )
            for lane in ("FTMO", "IC"):
                with self.subTest(lane=lane):
                    script = (root / lane / "compact_containment.remote.ps1").read_text(encoding="utf-8")
                    self.assertIn("status --porcelain=v1 --untracked-files=no", script)
                    self.assertIn("tracked_worktree_clean", script)
                    self.assertIn("tracked_worktree_status", script)
                    self.assertIn("critical_runtime_file_hashes", script)
                    self.assertIn("Get-FileHash", script)
                    for relative in profile["steps"][f"{lane}/compact_containment"]["expectations"][
                        "critical_runtime_file_hashes"
                    ]:
                        self.assertIn(relative, script)
                    for unsafe in (
                        "Set-Content",
                        "Remove-Item",
                        "Disable-ScheduledTask",
                        "Enable-ScheduledTask",
                        "Start-ScheduledTask",
                        "order_send",
                        "order_check",
                    ):
                        self.assertNotIn(unsafe, script)

    def test_all_gate1_commands_pin_lane_identity_and_profile_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "gate1_v2"
            gate1_v2_producer.build_gate1_v2_pre_execution_bundle(root)
            profile = verifier.load_safety_profile(
                TRACKED_RESUMPTION_PROFILE_PATH,
                "stage5_gate1_dual_lane_contained_v2",
            )
            aliases = {"FTMO": "lpfs-vps", "IC": "lpfs-ic-vps"}
            for lane, alias in aliases.items():
                with self.subTest(lane=lane):
                    for step in ("compact_containment", "bounded_status", "strict_mt5_probe"):
                        command = (root / lane / f"{step}.command.txt").read_text(encoding="utf-8")
                        self.assertIn(alias, command)
                    compact_script = (root / lane / "compact_containment.remote.ps1").read_text(encoding="utf-8")
                    compact_command_path = root / lane / "compact_containment.command.txt"
                    compact_command = compact_command_path.read_text(encoding="utf-8")
                    self.assertLess(len(compact_command), verifier.COMPACT_CONTAINMENT_COMMAND_SAFE_LENGTH)
                    self.assertNotIn(compact_script.strip(), compact_command)
                    self.assertNotIn(
                        base64.b64encode(compact_script.encode("utf-16le")).decode("ascii"),
                        compact_command,
                    )
                    self.assertEqual(
                        verifier._sha256(compact_command_path),
                        profile["steps"][f"{lane}/compact_containment"]["expected_command_sha256"],
                    )
                    self.assertEqual(
                        hashlib.sha256(compact_script.encode("utf-8")).hexdigest(),
                        profile["steps"][f"{lane}/compact_containment"]["expected_compact_script_sha256"],
                    )
                    bounded = root / lane / "bounded_status.command.txt"
                    self.assertEqual(
                        verifier._sha256(bounded),
                        profile["steps"][f"{lane}/bounded_status"]["expected_command_sha256"],
                    )
                    strict_script = (root / lane / "strict_mt5_probe.py").read_text(encoding="utf-8")
                    self.assertIn(
                        base64.b64encode(strict_script.encode("utf-8")).decode("ascii"),
                        (root / lane / "strict_mt5_probe.command.txt").read_text(encoding="utf-8"),
                    )
                    for required_read in (
                        "account_info()",
                        "terminal_info()",
                        "orders_get()",
                        "positions_get()",
                        "history_orders_get(start, end)",
                        "history_deals_get(start, end)",
                    ):
                        self.assertIn(required_read, strict_script)
                    for forbidden_call in ("order_send(", "order_check(", "positions_close(", "order_delete("):
                        self.assertNotIn(forbidden_call, strict_script)


class Stage5PreExecutionContractTests(unittest.TestCase):
    def _contract_document(self, root: Path) -> dict[str, object]:
        command = root / "precheck.command.txt"
        script = root / "precheck.remote.ps1"
        return {
            "schema_version": 1,
            "contracts": {
                "test_read_only_v1": {
                    "contract_version": 1,
                    "gate": "test_gate",
                    "required_artifacts": [command.name, script.name],
                    "artifacts": {
                        command.name: {"bytes": command.stat().st_size, "sha256": verifier._sha256(command)},
                        script.name: {"bytes": script.stat().st_size, "sha256": verifier._sha256(script)},
                    },
                }
            },
        }

    def _staged(self, root: Path) -> Path:
        (root / "precheck.command.txt").write_text("powershell -File precheck.remote.ps1\n", encoding="utf-8")
        (root / "precheck.remote.ps1").write_text("Get-Item C:\\TradeAutomation\n", encoding="utf-8")
        return root

    def _contract_file(self, root: Path, document: dict[str, object] | None = None) -> Path:
        path = root.parent / "contract.json"
        path.write_text(json.dumps(document or self._contract_document(root)), encoding="utf-8")
        return path

    def _load_contract(self, path: Path) -> dict[str, object]:
        return pre_execution.load_read_only_contract(
            path,
            "test_read_only_v1",
            expected_document_sha256=verifier._sha256(path),
        )

    def test_pre_execution_contract_pass_is_hash_proof_not_execution_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "staged"
            root.mkdir()
            self._staged(root)
            contract = self._load_contract(self._contract_file(root))
            result = pre_execution.verify_pre_execution_contract(root, contract)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["approved_read_only_hashes_match"])
            self.assertFalse(result["authorizes_execution"])
            self.assertTrue(result["does_not_prove_post_execution_behavior"])

    def test_pre_execution_hash_mismatch_and_unapproved_script_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "staged"
            root.mkdir()
            self._staged(root)
            contract = self._load_contract(self._contract_file(root))
            (root / "precheck.remote.ps1").write_text("Set-Content unsafe.txt unsafe\n", encoding="utf-8")
            (root / "unapproved.py").write_text("print('unsafe')\n", encoding="utf-8")
            result = pre_execution.verify_pre_execution_contract(root, contract)
            self.assertEqual(result["status"], "STOPPED")
            self.assertIn("unapproved", result["reason"])
            self.assertIn("hash/size mismatch", result["reason"])

    def test_incomplete_pre_execution_contract_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "staged"
            root.mkdir()
            self._staged(root)
            document = self._contract_document(root)
            del document["contracts"]["test_read_only_v1"]["artifacts"]["precheck.remote.ps1"]
            with self.assertRaisesRegex(ValueError, "artifact set mismatch"):
                path = self._contract_file(root, document)
                pre_execution.load_read_only_contract(
                    path,
                    "test_read_only_v1",
                    expected_document_sha256=verifier._sha256(path),
                )

    def test_pre_execution_contract_rejects_duplicate_and_nonstandard_json(self) -> None:
        for content, pattern in (
            ('{"schema_version":1,"schema_version":1,"contracts":{}}', "duplicate JSON key"),
            ('{"schema_version":NaN,"contracts":{}}', "non-standard JSON constant"),
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "contract.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, pattern):
                    pre_execution.load_read_only_contract(
                        path,
                        "missing",
                        expected_document_sha256=verifier._sha256(path),
                    )

    def test_pre_execution_contract_rejects_unsupported_version_and_unknown_field(self) -> None:
        for mutate, pattern in (
            (
                lambda document: document["contracts"]["test_read_only_v1"].update({"contract_version": 2}),
                "unsupported",
            ),
            (
                lambda document: document["contracts"]["test_read_only_v1"].update({"typo": True}),
                "keys mismatch",
            ),
        ):
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "staged"
                root.mkdir()
                self._staged(root)
                document = self._contract_document(root)
                mutate(document)
                with self.assertRaisesRegex(ValueError, pattern):
                    path = self._contract_file(root, document)
                    pre_execution.load_read_only_contract(
                        path,
                        "test_read_only_v1",
                        expected_document_sha256=verifier._sha256(path),
                    )

    def test_modified_tracked_pre_execution_contract_is_rejected_by_pinned_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "contract.json"
            document = verifier._strict_json_file(TRACKED_PRE_EXECUTION_CONTRACT_PATH)
            document["contracts"]["stage5_gate1_dual_lane_read_only_v1"]["artifacts"][
                "FTMO/bounded_status.command.txt"
            ]["sha256"] = "0" * 64
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pinned reviewed candidate"):
                pre_execution.load_read_only_contract(path, "stage5_gate1_dual_lane_read_only_v1")

    def test_tracked_pre_execution_contracts_are_versioned_and_complete(self) -> None:
        gate1 = pre_execution.load_read_only_contract(
            TRACKED_PRE_EXECUTION_CONTRACT_PATH,
            "stage5_gate1_dual_lane_read_only_v1",
        )
        gate3 = pre_execution.load_read_only_contract(
            TRACKED_PRE_EXECUTION_CONTRACT_PATH,
            "stage5_ftmo_gate3_read_only_v1",
        )
        self.assertEqual(gate1["contract_version"], 1)
        self.assertEqual(gate3["contract_version"], 1)
        self.assertEqual(len(gate1["artifacts"]), 11)
        self.assertEqual(len(gate3["artifacts"]), 8)
        self.assertIn("scripts/Get-LpfsLiveStatus.ps1", gate1["artifacts"])
        self.assertIn("scripts/Get-LpfsLiveStatus.ps1", gate3["artifacts"])

    def test_future_bounded_status_contracts_pin_collector_and_status_implementation(self) -> None:
        for contract_id in (
            "stage5_gate1_bounded_status_read_only_v1",
            "stage5_ftmo_gate3_resumption_bounded_status_read_only_v1",
            "stage5_ic_gate3_resumption_bounded_status_read_only_v1",
        ):
            with self.subTest(contract_id=contract_id):
                contract = pre_execution.load_read_only_contract(
                    TRACKED_RESUMPTION_PRE_EXECUTION_CONTRACT_PATH,
                    contract_id,
                )
                self.assertEqual(
                    set(contract["artifacts"]),
                    {
                        "scripts/collect_lpfs_bounded_status_bundle.py",
                        "scripts/Get-LpfsLiveStatus.ps1",
                    },
                )
                self.assertEqual(
                    contract["artifacts"]["scripts/collect_lpfs_bounded_status_bundle.py"]["sha256"],
                    verifier._sha256(BOUNDED_STATUS_COLLECTOR_PATH),
                )
                self.assertEqual(
                    contract["artifacts"]["scripts/Get-LpfsLiveStatus.ps1"]["sha256"],
                    verifier._sha256(SCRIPTS_ROOT / "Get-LpfsLiveStatus.ps1"),
                )

    def test_complete_gate1_v2_contract_pins_all_six_step_producers(self) -> None:
        contract = pre_execution.load_read_only_contract(
            TRACKED_RESUMPTION_PRE_EXECUTION_CONTRACT_PATH,
            "stage5_gate1_v2_complete_read_only_v1",
            expected_document_sha256=verifier._sha256(TRACKED_RESUMPTION_PRE_EXECUTION_CONTRACT_PATH),
        )
        self.assertEqual(len(contract["artifacts"]), 13)
        for lane in ("FTMO", "IC"):
            for relative in (
                f"{lane}/compact_containment.command.txt",
                f"{lane}/compact_containment.remote.ps1",
                f"{lane}/bounded_status.command.txt",
                f"{lane}/strict_mt5_probe.command.txt",
                f"{lane}/strict_mt5_probe.py",
            ):
                self.assertIn(relative, contract["artifacts"])
        self.assertIn("scripts/build_lpfs_stage5_gate1_v2_pre_execution.py", contract["artifacts"])
        self.assertIn("scripts/collect_lpfs_bounded_status_bundle.py", contract["artifacts"])
        self.assertIn("scripts/Get-LpfsLiveStatus.ps1", contract["artifacts"])


if __name__ == "__main__":
    unittest.main()
