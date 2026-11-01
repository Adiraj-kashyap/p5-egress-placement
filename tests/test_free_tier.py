"""Free-tier guard (D-001, D-023): read-only scans that fail if a secret, a cloud SDK/CLI
provisioning call, an unlisted network host or a fixture snapshot is ever committed.

Runs inside the normal `pytest -q`. Scans the working tree, so it needs no git on PATH.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories whose text files must never contain a credential.
DATA_DIRS = ["logs", "evidence/logs", "snapshots", "tests/data", "results", "docs"]
# Directories holding our own code (seed/ and agent/ belong to the human and are not scanned).
CODE_DIRS = ["pricing", "placement", "experiments", "analysis", "testbed/measure"]

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),                       # Google API key
    re.compile(r"(?i)\bkey=[A-Za-z0-9_-]{8,}"),                  # key=<value> in a logged URL
    re.compile(r"AKIA[0-9A-Z]{16}"),                             # AWS access key id
]
FORBIDDEN_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:boto3|botocore|azure\.mgmt|azure\.identity|google\.cloud)\b", re.M)
FORBIDDEN_CLI = re.compile(
    r"""(?:subprocess\.\w+|os\.system|os\.popen)\(\s*\[?\s*["'](?:aws|az|gcloud)\b""")
# Hosts the code may talk to or cite (01_CONVENTIONS §6 plus documentation hosts).
ALLOWED_HOSTS = {
    "prices.azure.com", "pricing.us-east-1.amazonaws.com", "cloudbilling.googleapis.com",
    "cloudpricingcalculator.appspot.com",
    "learn.microsoft.com", "azure.microsoft.com", "aws.amazon.com", "docs.aws.amazon.com",
    "cloud.google.com", "pypi.org", "github.com", "hub.docker.com",
}
URL_HOST = re.compile(r"https?://([A-Za-z0-9.-]+)")
TEXT_SUFFIXES = {".txt", ".log", ".json", ".csv", ".md", ".py", ".yaml", ".yml"}


def find_secrets(text):
    """Return the list of secret-looking substrings found in `text`."""
    return [m.group(0) for p in SECRET_PATTERNS for m in p.finditer(text)]


def _files(dirs, suffixes):
    for d in dirs:
        base = ROOT / d
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts:
                    yield p


def test_secret_scanner_flags_fake_keys():
    """Negative control: the scanner must catch keys, else the scan below proves nothing."""
    assert find_secrets("GET https://x/v1/services?key=" + "AIza" + "S" * 35)
    assert find_secrets("...&key=abcdef123456&pageSize=1")
    assert find_secrets("AKIA" + "A" * 16)
    assert not find_secrets("GET https://prices.azure.com/api/retail/prices -> HTTP 200")


def test_no_secrets_in_data_dirs():
    hits = {str(p.relative_to(ROOT)): find_secrets(p.read_text(encoding="utf-8", errors="ignore"))
            for p in _files(DATA_DIRS, TEXT_SUFFIXES)}
    assert {k: v for k, v in hits.items() if v} == {}


def test_no_secrets_in_own_code():
    hits = {str(p.relative_to(ROOT)): find_secrets(p.read_text(encoding="utf-8", errors="ignore"))
            for p in _files(CODE_DIRS, {".py"})}
    assert {k: v for k, v in hits.items() if v} == {}


def test_env_and_logs_are_gitignored():
    lines = {ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert ".env" in lines
    assert "logs/*.log" in lines


def test_no_cloud_sdk_or_provisioning_cli_in_own_code():
    bad = {}
    for p in _files(CODE_DIRS, {".py"}):
        text = p.read_text(encoding="utf-8", errors="ignore")
        found = FORBIDDEN_IMPORT.findall(text) + FORBIDDEN_CLI.findall(text)
        if found:
            bad[str(p.relative_to(ROOT))] = found
    assert bad == {}


def test_pricing_code_only_uses_allowed_hosts():
    bad = {}
    for p in _files(["pricing"], {".py"}):
        hosts = set(URL_HOST.findall(p.read_text(encoding="utf-8", errors="ignore")))
        extra = hosts - ALLOWED_HOSTS
        if extra:
            bad[str(p.relative_to(ROOT))] = sorted(extra)
    assert bad == {}


def test_no_fixture_snapshot_is_committed():
    """I2: a snapshot flagged FIXTURE must never sit in snapshots/ where results could read it."""
    flagged = []
    for p in _files(["snapshots"], {".json"}):
        meta = json.loads(p.read_text(encoding="utf-8")).get("meta", {})
        if meta.get("FIXTURE") or "FIXTURE" in json.dumps(meta):
            flagged.append(str(p.relative_to(ROOT)))
    assert flagged == []
