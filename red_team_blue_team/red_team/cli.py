import argparse, sys, os
from pathlib import Path
from .generator import generate_variant


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m red_team generate",
        description="Generate AI‑enabled emerging playbooks using AWS Bedrock GPT‑OSS‑120B."
    )
    ap.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/sim_v2/config/playbooks"),
        help="Folder containing existing playbooks to augment.",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("red_team_blue_team/red_team/playbook_v2"),
        help="Folder where generated playbooks will be written.",
    )
    ap.add_argument(
        "--target-count",
        type=int,
        default=30,
        help="Total number of emerging playbooks to create (approx.).",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("RED_TEAM_SEED", "42")),
        help="Base random seed for reproducibility.",
    )
    args = ap.parse_args()

    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Grab a *small* random sample of source playbooks to keep the run fast.
    # The full repo contains ~12 k playbooks, which makes the naive loop
    # generate thousands of failed attempts before reaching the desired count.
    import random
    all_sources = list(args.source_dir.glob("*.yaml"))
    if not all_sources:
        sys.exit(f"No playbooks found in {args.source_dir}")
    # Limit to the first 30 (or fewer) random sources – enough diversity for a demo.
    sample_size = min(30, len(all_sources))
    sources = random.sample(all_sources, k=sample_size)

    created = 0
    src_index = 0
    while created < args.target_count:
        src_path = sources[src_index % len(sources)]
        seed = args.seed + created
        try:
            out_path = generate_variant(src_path, out_dir, seed)
            print(f"Created {out_path.relative_to(Path.cwd())}")
            created += 1
        except Exception as e:
            print(f"[WARN] Failed to generate from {src_path.name}: {e}")
        src_index += 1
        # If we have exhausted the sampled sources without success, break to avoid infinite loop.
        if src_index >= len(sources) * 5:  # allow a few retries per source
            print("[WARN] Unable to reach target count with the sampled sources; stopping early.")
            break

    print(f"\n[OK] Finished – {created} emerging playbooks written to {out_dir}")


if __name__ == "__main__":
    main()
