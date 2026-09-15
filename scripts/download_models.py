import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.workflow_packs import install_workflow_pack, list_workflow_packs, resolve_models_root


def parse_args():
    parser = argparse.ArgumentParser(description="Install model dependencies for an Orange workflow pack.")
    parser.add_argument("--pack", default="z-image-turbo", help="Workflow pack id to install")
    parser.add_argument("--models-root", help="Path to the ComfyUI models directory")
    parser.add_argument("--list", action="store_true", help="List available workflow packs and exit")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.list:
        print(json.dumps(list_workflow_packs(), indent=2))
        return 0

    models_root = resolve_models_root(args.models_root)
    if not models_root:
        if args.models_root:
            print(f"Models directory not found: {args.models_root}", file=sys.stderr)
            return 2
        entered = input("ComfyUI models directory: ").strip()
        models_root = resolve_models_root(entered)
        if not models_root:
            print("Could not find that ComfyUI models directory.", file=sys.stderr)
            return 2

    print(f"Installing Orange workflow pack '{args.pack}' into {models_root}")
    result = install_workflow_pack(args.pack, models_root)
    for path in result["skipped"]:
        print(f"Already installed: {path}")
    for path in result["installed"]:
        print(f"Installed: {path}")
    if result["failures"]:
        print("Some downloads failed:", file=sys.stderr)
        for failure in result["failures"]:
            print(f" - {failure['filename']}: {failure['error']}", file=sys.stderr)
        return 1
    print("Workflow pack dependencies are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
