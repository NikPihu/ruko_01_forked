import random, copy, json, yaml
from pathlib import Path
from .utils import load_yaml, dump_yaml, uniq_name, TECHNIQUES
from .bedrock_client import invoke


def build_prompt(base_pb: dict, technique: dict) -> str:
    """Create a succinct prompt that asks Bedrock to inject *technique* into *base_pb*.
    The prompt explicitly asks for a complete YAML document with `emerging: true`.
    """
    title = base_pb.get("title", "Untitled")
    steps_json = json.dumps(base_pb.get("steps", []), indent=2)
    return (
        f"You are designing a scam playbook. The current playbook is titled:\n"
        f"\n    \"{title}\"\n"
        f"It has {len(base_pb.get('steps', []))} steps. The existing steps are:\n"
        f"{steps_json}\n\n"
        f"Inject the following AI‑enabled technique into the playbook:\n"
        f"{technique['description']}\n\n"
        f"Keep all original steps, add the new step(s) where appropriate, and set the top‑level flag "
        f"`emerging: true`. Return ONLY the full YAML document (no explanations)."
    )


def generate_variant(src_path: Path, out_dir: Path, seed: int) -> Path:
    """Generate one emerging variant from *src_path* and write it into *out_dir*.
    The function uses a deterministic *seed* for reproducibility.
    Returns the path of the created file.
    """
    random.seed(seed)
    base_pb = load_yaml(src_path)

    # Choose a random non‑empty subset of techniques (1‑3 techniques).
    k = random.choice([1, 2, 3])
    chosen = random.sample(TECHNIQUES, k=k)

    # Build a single prompt that lists all chosen techniques.
    prompt = "\n---\n".join(build_prompt(base_pb, t) for t in chosen)

    try:
        raw_yaml = invoke(prompt)
        new_pb = yaml.safe_load(raw_yaml)
    except Exception as exc:
        # Fallback: deterministic mutation – add a custom step listing the chosen techniques.
        new_pb = copy.deepcopy(base_pb)
        new_pb.setdefault("steps", []).append({
            "id": f"ai_tech_{seed}",
            "type": "custom",
            "note": f"AI techniques injected: {', '.join(t['name'] for t in chosen)}"
        })
        # Log the fallback in a real deployment; here we just continue.

    # Ensure required keys exist.
    new_pb["emerging"] = True
    # Give a unique filename based on the source name and the seed.
    base_name = f"{src_path.stem}_emerging_{seed}"
    filename = uniq_name(base_name, out_dir)
    out_path = out_dir / filename
    dump_yaml(new_pb, out_path)
    return out_path
