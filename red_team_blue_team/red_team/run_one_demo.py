#!/usr/bin/env python
"""Generate a single emergent playbook and evaluate it.

This script is a minimal reproducible example for the red‑team pipeline:
1️⃣ Pick a source playbook from the simulator library.
2️⃣ Inject AI techniques via the Bedrock generator (or fallback rules).
3️⃣ Run the synthetic_playbook evaluator on the freshly generated playbook
   with a single victim transaction.
4️⃣ Print the summary line that contains the threat score, tier, and
   whether the payment was flagged as normal or a breakthrough.

The script writes the generated playbook into
`red_team_blue_team/red_team/playbook_v2/` and uses the same environment
variables (`BEDROCK_MODEL_ID`, `AWS_DEFAULT_REGION`) that the UI uses.
"""

import os
import sys
import subprocess
from pathlib import Path

# Ensure the evaluator can find the backend, ml, data, and synthetic_playbook packages
os.environ["PYTHONPATH"] = "backend;ml;data;synthetic_playbook"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ---------------------------------------------------------------------------
# 1️⃣ Pick a source playbook (any existing one)
# ---------------------------------------------------------------------------
source_dir = Path("data/sim_v2/config/playbooks")
if not source_dir.is_dir():
    sys.exit(f"Source playbooks folder not found: {source_dir}")

# Use the first YAML file we find – deterministic for this demo
src_path = next(source_dir.glob("*.yaml"), None)
if not src_path:
    sys.exit(f"No playbook YAML files in {source_dir}")

# ---------------------------------------------------------------------------
# 2️⃣ Generate an emergent playbook using the red‑team generator
# ---------------------------------------------------------------------------
out_dir = Path("red_team_blue_team/red_team/playbook_v2")
out_dir.mkdir(parents=True, exist_ok=True)

# Import the generator function from the package (already in PYTHONPATH)
from red_team_blue_team.red_team.generator import generate_variant

# Use a fixed seed so the result is reproducible
seed = 42
generated_path = generate_variant(src_path, out_dir, seed)
print(f"Generated playbook: {generated_path}")

# ---------------------------------------------------------------------------
# 3️⃣ Evaluate the single playbook (1 victim) with the ML scorer
# ---------------------------------------------------------------------------
# The interface_script command `run` expects a path or a library name.
# We give it the absolute path of the generated file.
cmd = [
    sys.executable,
    "-m",
    "interface_script",
    "run",
    "--playbook", str(generated_path),
    # One victim gives one judged payment, which says nothing: a verdict needs a few dozen.
    "--victims", "15",
    "--honest-users", "25",
    "--server", "local",  # use the in-process server
]

print("Running evaluator…")
result = subprocess.run(cmd, capture_output=True, text=True)

# ---------------------------------------------------------------------------
# 4️⃣ Show the evaluator output (or error)
# ---------------------------------------------------------------------------
if result.returncode != 0:
    print("Evaluator failed:")
    print(result.stderr)
    sys.exit(result.returncode)

print("Evaluator output:\n")
print(result.stdout)

# The last line of the output contains the summary for the single victim.
# It looks like:
#   "playbook: <name>  scam_payments_judged: 1  scam_called_normal: 0  …"
# You can further parse it if needed.
