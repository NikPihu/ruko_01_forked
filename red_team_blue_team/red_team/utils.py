import yaml, copy, random
from pathlib import Path

# Catalogue of AI‑enabled techniques that can be injected into a playbook.

import shutil
import pandas as pd

def filter_breakthroughs(csv_path: Path, src_dir: Path, dst_dir: Path) -> list:
    """Copy breakthrough playbooks listed in *csv_path* from *src_dir* to *dst_dir*.
    Returns a list of the destination Path objects for the copied files.
    The CSV is expected to have a boolean ``breakthrough`` column and a ``playbook``
    column containing the filename (e.g., ``my_playbook.yaml``)."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    df = pd.read_csv(csv_path)
    if "breakthrough" not in df.columns or "playbook" not in df.columns:
        raise ValueError("CSV must contain 'breakthrough' and 'playbook' columns")
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for _, row in df.iterrows():
        if bool(row["breakthrough"]):
            src_file = src_dir / row["playbook"]
            if src_file.exists():
                dst_file = dst_dir / src_file.name
                shutil.copy2(src_file, dst_file)
                copied.append(dst_file)
    return copied

TECHNIQUES = [
    {
        "name": "video_deepfake",
        "description": (
            "Add a step with `type: video_call`, `deepfake: true`, "
            "`script: \"hospital emergency\"`"
        ),
    },
    {
        "name": "ai_chatbot",
        "description": (
            "Insert a `chatbot` step that sends short burst messages "
            "asking for amounts."
        ),
    },
    {
        "name": "ai_kyc_video",
        "description": (
            "Add a `kyc_video` step where a fake bank officer asks for a screen‑share."
        ),
    },
    {
        "name": "split_payment",
        "description": "Break the total amount into 3‑5 small transfers.",
    },
    {
        "name": "qr_only",
        "description": "Replace typed UPI entry with a QR‑code payment.",
    },
    {
        "name": "early_hangup",
        "description": "End the call before the payment is entered.",
    },
]


def load_yaml(path: Path) -> dict:
    """Load a YAML file and return a Python dict."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(data: dict, path: Path) -> None:
    """Write *data* as YAML to *path* (preserves order, no sorting)."""
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def uniq_name(base: str, out_dir: Path) -> str:
    """Return a filename that does not already exist in *out_dir*.
    The returned string includes the ``.yaml`` suffix.
    """
    candidate = f"{base}.yaml"
    i = 1
    while (out_dir / candidate).exists():
        candidate = f"{base}_{i}.yaml"
        i += 1
    return candidate
