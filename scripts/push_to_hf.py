"""
Push URAAS to Hugging Face Spaces — Lordkiki/APA-URAAS

Usage:
    python scripts/push_to_hf.py

What it does:
  1. Logs you into HF (paste your write token when prompted)
  2. Stages a clean copy of the project:
       Dockerfile.hf  → Dockerfile   (HF Spaces Dockerfile, not the prod one)
       README.hf.md   → README.md    (has the HF Space frontmatter)
  3. Uploads everything to the Space via huggingface_hub.upload_folder
  4. HF triggers an auto-build — app is live in ~5 minutes
"""

import os
import shutil
import sys
import tempfile

# ── Config ────────────────────────────────────────────────────────────────────
REPO_ID   = "Lordkiki/APA-URAAS"
REPO_TYPE = "space"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories/files to never push
IGNORE_DIRS = {
    ".git", ".claude", "__pycache__", ".pytest_cache", ".mypy_cache",
    "storage", "logs", "data", "backups", "node_modules",
    ".venv", "venv", "env",
}
IGNORE_FILES = {
    ".env", ".env.prod", ".env.prod.example",
    "uraas.db",                  # DB lives on /data in HF, not in image
    "Dockerfile",                # replaced by Dockerfile.hf
    "README.md",                 # replaced by README.hf.md (has HF frontmatter)
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.replica.yml",
    "docker-compose.demo.yml",
}
IGNORE_EXTS = {
    ".pyc", ".pyo", ".pyd",
    # Database files/backups — belt-and-suspenders beyond the exact
    # "uraas.db" name check below and the startswith("uraas.db") check,
    # since a missed pattern here means real crawled data (author names,
    # DOIs, institutional affiliations, emails) goes to a PUBLIC repo.
    # Confirmed this actually happened (2026-07-19): uraas.db.bak, a
    # 1819-item/14MB snapshot, was uploaded because only "uraas.db" itself
    # was excluded, not the ".bak" variant — deleted from the live Space
    # after the fact, but should never have gone up in the first place.
    ".bak", ".backup", ".old", ".orig", ".db", ".sqlite", ".sqlite3",
}


def should_skip(rel_path: str, is_dir: bool) -> bool:
    parts = rel_path.replace("\\", "/").split("/")
    name  = parts[-1]
    if is_dir:
        return name in IGNORE_DIRS
    # Catches any suffix variant regardless of extension — uraas.db-wal,
    # uraas.db-shm, uraas.db-journal, timestamped backups like
    # uraas.db.20260629, etc. — not just the exact names/extensions above.
    if name.startswith("uraas.db"):
        return True
    return (
        name in IGNORE_FILES
        or os.path.splitext(name)[1].lower() in IGNORE_EXTS
    )


def stage_project(src: str, dst: str) -> int:
    """Copy src → dst with HF-specific renames and exclusions."""
    count = 0
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)

        # Prune excluded directories in-place so os.walk doesn't recurse
        dirs[:] = [
            d for d in dirs
            if not should_skip(
                os.path.join(rel_root, d) if rel_root != "." else d,
                is_dir=True,
            )
        ]

        for fname in files:
            rel = os.path.join(rel_root, fname) if rel_root != "." else fname
            if should_skip(rel, is_dir=False):
                continue

            src_file = os.path.join(root, fname)

            # HF-specific renames
            if fname == "Dockerfile.hf":
                dest_rel = os.path.join(os.path.dirname(rel), "Dockerfile") if os.path.dirname(rel) else "Dockerfile"
            elif fname == "README.hf.md":
                dest_rel = "README.md"
            else:
                dest_rel = rel

            dst_file = os.path.join(dst, dest_rel)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
            count += 1
    return count


def main():
    # ── Ensure huggingface_hub is available ────────────────────────────────
    try:
        from huggingface_hub import HfApi, login
    except ImportError:
        print("Installing huggingface_hub...")
        os.system(f"{sys.executable} -m pip install huggingface_hub -q")
        from huggingface_hub import HfApi, login  # type: ignore

    _SEP = "=" * 55
    print()
    print(_SEP)
    print("  URAAS -> Hugging Face Spaces")
    print(f"  Space: {REPO_ID}")
    print(_SEP)

    # ── Auth ───────────────────────────────────────────────────────────────
    # Live-verified 2026-08-04: with no HF_TOKEN env var, this used to always
    # call login() with no token, which prompts interactively for one — in
    # any non-interactive shell (CI, a background task, this script run
    # without a TTY) that blocks forever waiting for input that can never
    # arrive, even when a valid token is already cached from a previous
    # `huggingface-cli login` on the same machine. Try the cached credential
    # first; only fall back to an interactive prompt when actually attached
    # to a terminal.
    token = os.getenv("HF_TOKEN")
    if token:
        login(token=token, add_to_git_credential=True)
        print("  Logged in via HF_TOKEN env var.")
    else:
        from huggingface_hub import HfFolder
        cached = HfFolder.get_token()
        if cached:
            try:
                HfApi().whoami(token=cached)
                print("  Logged in via cached HF credential.")
            except Exception:
                cached = None
        if not cached:
            if not sys.stdin.isatty():
                print()
                print("  No HF_TOKEN env var, no cached credential, and no terminal to prompt on.")
                print("  Set HF_TOKEN=hf_... and re-run, e.g.:")
                print(f"    HF_TOKEN=hf_... python {os.path.basename(__file__)}")
                sys.exit(1)
            print()
            print("  Paste your HF write token below.")
            print("  (Get one at: https://huggingface.co/settings/tokens)")
            print()
            login(add_to_git_credential=True)

    api = HfApi()

    # ── Stage files ────────────────────────────────────────────────────────
    print()
    print("Staging project files…")
    with tempfile.TemporaryDirectory() as staging:
        n = stage_project(REPO_ROOT, staging)
        staged_names = os.listdir(staging)
        print(f"  {n} files staged across {len(staged_names)} top-level items")

        # Sanity checks
        has_dockerfile = "Dockerfile" in staged_names
        has_readme     = "README.md" in staged_names
        has_start_sh   = os.path.exists(os.path.join(staging, "scripts", "start_hf.sh"))

        print(f"  Dockerfile   : {'OK' if has_dockerfile else 'MISSING -- check Dockerfile.hf exists'}")
        print(f"  README.md    : {'OK' if has_readme else 'MISSING -- check README.hf.md exists'}")
        print(f"  start_hf.sh  : {'OK' if has_start_sh else 'MISSING -- check scripts/start_hf.sh'}")

        if not has_dockerfile:
            print()
            print("ERROR: Dockerfile missing from staging. Aborting.")
            sys.exit(1)

        # ── Upload ─────────────────────────────────────────────────────────
        # Skip HF's remote YAML validation — it times out on some networks.
        # README.hf.md is already valid so this is safe to skip.
        api._validate_yaml = lambda *a, **kw: None

        print()
        print(f"Uploading to {REPO_ID}...")
        api.upload_folder(
            folder_path=staging,
            repo_id=REPO_ID,
            repo_type=REPO_TYPE,
            commit_message="Deploy URAAS — African Research Archival & Analytics System",
        )

    # ── Done ───────────────────────────────────────────────────────────────
    print()
    print(_SEP)
    print("  Upload complete! Build starting on HF (~5 min).")
    print()
    print("  Watch build: https://huggingface.co/spaces/Lordkiki/APA-URAAS")
    print("  App URL    : https://lordkiki-apa-uraas.hf.space")
    print()
    print("  --- Secrets to set in Space Settings -> Variables & Secrets ---")
    secrets = [
        ("URAAS_ENV",              "production"),
        ("DASHBOARD_SECRET_KEY",   "307790fc5aff3fe1e766303f6b94e2fc28c831582bfba5b34802e2c9cbbac0ce"),
        ("ADMIN_USERNAME",         "admin"),
        ("ADMIN_PASSWORD_HASH",    "scrypt:32768:8:1$r2KZFX32rJ2twbfV$16f394a253c2b505a215ff2747f7dafbb098eb0eb8b4e6bb9fb521f0ea38af8ce71f33d2354245d68cc383678257367bf410aa45f835b5e848bff95a746878c8"),
        ("VIEWER_USERNAME",        "viewer"),
        ("VIEWER_PASSWORD_HASH",   "scrypt:32768:8:1$M8OjWxX64B38akos$2803ad5b29508c4d69df115579630b2a4cbdf2c8406157598c088d5511a7b3d79f91399035040660705413c63fdc41aa0d020cbd7b45038c8ed51d20092ea609"),
        ("SMTP_HOST",              "smtp.gmail.com"),
        ("SMTP_PORT",              "587"),
        ("SMTP_USE_TLS",           "true"),
        ("SMTP_USER",              "lawalgiyath200716@gmail.com"),
        ("SMTP_PASSWORD",          "ufwqbdrecpfrzppn"),
        ("SMTP_FROM",              "URAAS UNILAG <lawalgiyath200716@gmail.com>"),
        ("DASHBOARD_BASE_URL",     "https://lordkiki-apa-uraas.hf.space"),
        ("DASHBOARD_CORS_ORIGINS", "https://lordkiki-apa-uraas.hf.space"),
        ("ARK_NAAN",               "99999"),
        ("ARK_SHOULDER",           "z1"),
        ("OPENALEX_MAILTO",        "lawalgiyath200716@gmail.com"),
        ("DSPACE_API_URL",         "https://api-ir.unilag.edu.ng/server"),
        ("DSPACE_USERNAME",        "<professor email — set as Secret, not Variable>"),
        ("DSPACE_PASSWORD",        "<professor password — set as Secret, not Variable>"),
    ]
    max_k = max(len(k) for k, _ in secrets)
    for k, v in secrets:
        print(f"  {k:<{max_k}} = {v}")
    print()
    print("  Admin login : admin / URAAS2024demo")
    print("  Viewer login: viewer / view2024")
    print(_SEP)


if __name__ == "__main__":
    main()
