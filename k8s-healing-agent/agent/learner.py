"""
K8s Healing Agent — Learner Module

LEARN phase of the Agent Loop.

Records the outcome of each healing cycle, prints a rich summary, and
maintains an in-memory history for the current session.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from agent.display import print_phase, print_info, print_section_header, Color, _c
from agent.reasoner import Diagnosis
from agent.executor import ExecutionResult
from agent.verifier import VerificationResult


@dataclass
class IncidentRecord:
    """A full record of a single healing incident."""

    timestamp:          str
    scenario_num:       int
    scenario_title:     str
    deployment_name:    str
    namespace:          str
    issue_type:         str
    root_cause:         str
    fix_applied:        str
    success:            bool
    time_to_resolution: float
    pod_name:           str = ""
    notes:              str = ""


class Learner:
    """
    Records healing outcomes and maintains an in-memory incident log.

    In a production system this would persist records to a database,
    update the runbook, and potentially feed a machine-learning model.
    """

    def __init__(self) -> None:
        self._history: List[IncidentRecord] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(
        self,
        scenario_num:    int,
        scenario_title:  str,
        deployment_name: str,
        namespace:       str,
        diag:            Optional[Diagnosis],
        exec_result:     ExecutionResult,
        verify_result:   VerificationResult,
        start_time:      float,
    ) -> IncidentRecord:
        """
        Build and store an IncidentRecord, then print the LEARN summary.

        Parameters
        ----------
        scenario_num:
            Integer scenario number (1-5).
        scenario_title:
            Human-readable name for the scenario.
        deployment_name:
            Name of the deployment that was fixed.
        namespace:
            Kubernetes namespace.
        diag:
            The Diagnosis produced by the Reasoner (may be None on failure).
        exec_result:
            The ExecutionResult from the Executor.
        verify_result:
            The VerificationResult from the Verifier.
        start_time:
            ``time.time()`` value taken at the start of the scenario.
        """
        elapsed = time.time() - start_time

        record = IncidentRecord(
            timestamp          = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            scenario_num       = scenario_num,
            scenario_title     = scenario_title,
            deployment_name    = deployment_name,
            namespace          = namespace,
            issue_type         = diag.pattern_id     if diag else "unknown",
            root_cause         = diag.summary        if diag else "Could not determine root cause",
            fix_applied        = exec_result.message,
            success            = verify_result.success,
            time_to_resolution = elapsed,
            pod_name           = verify_result.pod_name,
        )

        self._history.append(record)
        time.sleep(1)
        self._print_learn(record)
        return record

    def print_session_summary(self) -> None:
        """Print a summary table of all incidents recorded in this session."""
        if not self._history:
            return

        print_section_header("SESSION SUMMARY")
        total    = len(self._history)
        success  = sum(1 for r in self._history if r.success)
        failed   = total - success

        print_info(f"Total scenarios:  {total}")
        print_info(
            f"Resolved:         {_c(Color.GREEN, str(success))}  |  "
            f"Failed: {_c(Color.RED, str(failed))}"
        )
        print()
        for rec in self._history:
            status = _c(Color.GREEN, "✅ PASS") if rec.success else _c(Color.RED, "❌ FAIL")
            print_info(
                f"  Scenario {rec.scenario_num}: {rec.scenario_title:<35} "
                f"{status}  ({rec.time_to_resolution:.0f}s)"
            )
        print()

    @property
    def history(self) -> List[IncidentRecord]:
        """Return the list of recorded incidents (read-only copy)."""
        return list(self._history)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _print_learn(self, rec: IncidentRecord) -> None:
        """Print the LEARN phase output for one incident."""
        result_str = _c(Color.GREEN, "SUCCESS") if rec.success else _c(Color.RED, "FAILURE")
        print_phase("LEARN", "📚", "Outcome recorded:")
        print_info(f"Issue:    {rec.issue_type}")
        print_info(f"Fix:      {rec.fix_applied}")
        print_info(f"Result:   {result_str}")
        print_info(f"Duration: {rec.time_to_resolution:.0f} seconds")
