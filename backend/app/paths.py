"""Path sandbox for note/HL7 reads (security-foundations §4.3).

All patient file access must go through safe_patient_file(); it only resolves
paths inside data/patient/ and rejects traversal tricks. Used by M2/M4 note
and HL7 endpoints; landed in M1 so the safe habit exists from the start.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATIENT_DATA_ROOT = (REPO_ROOT / "data" / "patient").resolve()


class SandboxViolation(ValueError):
    pass


def safe_patient_file(relative_path: str) -> Path:
    """Resolve a repo-relative or data/patient-relative path inside the sandbox.

    Accepts paths like 'data/patient/1/notes/004821_discharge.txt' or
    '1/notes/004821_discharge.txt'. Raises SandboxViolation for absolute
    paths, traversal attempts, or anything resolving outside data/patient/.
    """
    rel = Path(relative_path)
    if rel.is_absolute():
        raise SandboxViolation("absolute paths are not allowed")

    candidate = (REPO_ROOT / rel).resolve()
    if not str(candidate).startswith(str(PATIENT_DATA_ROOT) + "/"):
        candidate = (PATIENT_DATA_ROOT / rel).resolve()

    if not str(candidate).startswith(str(PATIENT_DATA_ROOT) + "/"):
        raise SandboxViolation(f"path escapes data/patient sandbox: {relative_path}")
    if not candidate.is_file():
        raise FileNotFoundError(f"no such patient file: {relative_path}")
    return candidate
