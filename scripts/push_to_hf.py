"""
Push URAAS to Hugging Face Spaces - Lordkiki/APA-URAAS

Usage:
    python scripts/push_to_hf.py

What it does:
  1. Logs you into HF (paste your write token when prompted)
  2. Stages a clean copy of the project:
       deploy/hf/Dockerfile -> Dockerfile  (HF Spaces build, not the prod one)
       deploy/hf/README.md  -> README.md   (has the HF Space frontmatter)
  3. Uploads everything to the Space via huggingface_hub.upload_folder
  4. HF triggers an auto-build - app is live in ~5 minutes
"""

import os
import shutil
import sys
import tempfile

# -- Config --------------------------------------------------------------------
REPO_ID = "Lordkiki/APA-URAAS"
REPO_TYPE = "space"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories/files to never push
IGNORE_DIRS = {
    ".git",
    ".claude",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "storage",
    "logs",
    "data",
    "scratch",
    ".vscode",
    ".idea",
    "backups",
    "node_modules",
    ".venv",
    "venv",
    "env",
}
IGNORE_FILES = {
    ".env",
    ".env.prod",
    ".env.prod.example",
    "uraas.db",  # DB lives on /data in HF, not in image
}

# Files staged at a different path on the Space than they live at in the repo.
# HF Spaces requires the Dockerfile and the frontmatter-bearing README at the
# repo root, so the HF-specific copies under deploy/hf/ are promoted there.
HF_RENAMES = {
    "deploy/hf/Dockerfile": "Dockerfile",
    "deploy/hf/README.md": "README.md",
}

# Repo-root files the HF copies above replace. Matched on the full relative
# path, not the basename, so deploy/hf/Dockerfile is not caught by them.
IGNORE_REL_PATHS = {
    "Dockerfile",  # production Dockerfile; deploy/hf/Dockerfile wins on HF
    "README.md",  # GitHub README; deploy/hf/README.md wins on HF
}
IGNORE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
    # Presentation and document sources: reference material for humans,
    # dead weight in a container image.
    ".pptx",
    ".docx",
    # Database files/backups - belt-and-suspenders beyond the exact
    # "uraas.db" name check below and the startswith("uraas.db") check,
    # since a missed pattern here means real crawled data (author names,
    # DOIs, institutional affiliations, emails) goes to a PUBLIC repo.
    # Confirmed this actually happened (2026-07-19): uraas.db.bak, a
    # 1819-item/14MB snapshot, was uploaded because only "uraas.db" itself
    # was excluded, not the ".bak" variant - deleted from the live Space
    # after the fact, but should never have gone up in the first place.
    ".bak",
    ".backup",
    ".old",
    ".orig",
    ".db",
    ".sqlite",
    ".sqlite3",
}


def should_skip(rel_path: str, is_dir: bool) -> bool:
    rel = rel_path.replace("\\", "/")
    name = rel.split("/")[-1]
    if is_dir:
        if name in IGNORE_DIRS:
            return True
        # Descend into deploy/ only as far as deploy/hf/ - the compose, k8s,
        # nginx and Render configs next to it target other platforms entirely.
        return rel.startswith("deploy/") and not rel.startswith("deploy/hf")
    if rel in HF_RENAMES:
        return False
    if rel in IGNORE_REL_PATHS:
        return True
    if rel.startswith("deploy/") and not rel.startswith("deploy/hf/"):
        return True
    # Catches any suffix variant regardless of extension - uraas.db-wal,
    # uraas.db-shm, uraas.db-journal, timestamped backups like
    # uraas.db.20260629, etc. - not just the exact names/extensions above.
    if name.startswith("uraas.db"):
        return True
    # Any dotenv variant, not just the exact names above. Live-verified
    # 2026-09: scratch/test.env carried real password hashes and Postgres
    # and Redis passwords, and was being uploaded to the public Space on
    # every deploy because only the literal ".env" was excluded.
    if name.endswith(".env"):
        return True
    return name in IGNORE_FILES or os.path.splitext(name)[1].lower() in IGNORE_EXTS


def stage_project(src: str, dst: str) -> int:
    """Copy src -> dst with HF-specific renames and exclusions."""
    count = 0
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)

        # Prune excluded directories in-place so os.walk doesn't recurse
        dirs[:] = [
            d
            for d in dirs
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

            dest_rel = HF_RENAMES.get(rel.replace("\\", "/"), rel)

            dst_file = os.path.join(dst, dest_rel)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
            count += 1
    return count


def main():
    # -- Ensure huggingface_hub is available --------------------------------
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

    # -- Auth ---------------------------------------------------------------
    # Live-verified 2026-08-04: with no HF_TOKEN env var, this used to always
    # call login() with no token, which prompts interactively for one - in
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
                print(
                    "  No HF_TOKEN env var, no cached credential, and no terminal to prompt on."
                )
                print("  Set HF_TOKEN=hf_... and re-run, e.g.:")
                print(f"    HF_TOKEN=hf_... python {os.path.basename(__file__)}")
                sys.exit(1)
            print()
            print("  Paste your HF write token below.")
            print("  (Get one at: https://huggingface.co/settings/tokens)")
            print()
            login(add_to_git_credential=True)

    api = HfApi()

    # -- Stage files --------------------------------------------------------
    print()
    print("Staging project files...")
    with tempfile.TemporaryDirectory() as staging:
        n = stage_project(REPO_ROOT, staging)
        staged_names = os.listdir(staging)
        print(f"  {n} files staged across {len(staged_names)} top-level items")

        # Sanity checks
        has_dockerfile = "Dockerfile" in staged_names
        has_readme = "README.md" in staged_names
        has_start_sh = os.path.exists(os.path.join(staging, "deploy", "hf", "start.sh"))

        print(
            f"  Dockerfile   : {'OK' if has_dockerfile else 'MISSING -- check deploy/hf/Dockerfile exists'}"
        )
        print(
            f"  README.md    : {'OK' if has_readme else 'MISSING -- check deploy/hf/README.md exists'}"
        )
        print(
            f"  start.sh     : {'OK' if has_start_sh else 'MISSING -- check deploy/hf/start.sh'}"
        )

        if not has_dockerfile:
            print()
            print("ERROR: Dockerfile missing from staging. Aborting.")
            sys.exit(1)

        # -- Upload ---------------------------------------------------------
        # Skip HF's remote YAML validation - it times out on some networks.
        # README.hf.md is already valid so this is safe to skip.
        api._validate_yaml = lambda *a, **kw: None

        print()
        print(f"Uploading to {REPO_ID}...")
        api.upload_folder(
            folder_path=staging,
            repo_id=REPO_ID,
            repo_type=REPO_TYPE,
            commit_message="Deploy URAAS - African Research Archival & Analytics System",
            # upload_folder only adds and updates - without this, a file
            # deleted locally lives on in the Space forever. Live-verified
            # 2026-09: 10 duplicate institution configs were removed here and
            # the deployed registry still served all 53 afterwards, because
            # the deletions never propagated. Scoped to config/ (the tree
            # this actually matters for) rather than "*", so a stray delete
            # pattern can't wipe Space-side runtime state such as the
            # persistent database.
            delete_patterns=["config/institutions/*.json"],
        )

    # -- Done ---------------------------------------------------------------
    print()
    print(_SEP)
    print("  Upload complete! Build starting on HF (~5 min).")
    print()
    print("  Watch build: https://huggingface.co/spaces/Lordkiki/APA-URAAS")
    print("  App URL    : https://lordkiki-apa-uraas.hf.space")
    print()
    print("  --- Secrets to set in Space Settings -> Variables & Secrets ---")
    print(_secrets_checklist())
    print(_SEP)


# Every variable the Space needs, and where its value comes from. Values are
# read from the local environment (.env included) at print time and are
# deliberately NOT in this file: it is committed to a public repository, and
# it previously carried a live Gmail app password, both dashboard password
# hashes and the session secret key in plain source.
SPACE_VARIABLES = [
    ("URAAS_ENV", "production"),
    ("DASHBOARD_BASE_URL", "https://lordkiki-apa-uraas.hf.space"),
    ("DASHBOARD_CORS_ORIGINS", "https://lordkiki-apa-uraas.hf.space"),
    ("DSPACE_API_URL", "https://api-ir.unilag.edu.ng/server"),
    ("ARK_NAAN", "99999"),
    ("ARK_SHOULDER", "z1"),
    ("SMTP_HOST", "smtp.gmail.com"),
    ("SMTP_PORT", "587"),
    ("SMTP_USE_TLS", "true"),
]

# Set as HF *Secrets*, never Variables - a Variable is readable by anyone who
# can open the Space settings.
SPACE_SECRETS = [
    "DASHBOARD_SECRET_KEY",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD_HASH",
    "VIEWER_USERNAME",
    "VIEWER_PASSWORD_HASH",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "OPENALEX_MAILTO",
    "DSPACE_USERNAME",
    "DSPACE_PASSWORD",
]


def _secrets_checklist() -> str:
    """The Space configuration checklist, filled in from the local .env.

    Anything not set locally prints as a placeholder rather than a value, so
    running this on a machine without the .env still produces the full list
    of what the Space needs.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(REPO_ROOT, ".env"))
    except Exception:
        pass

    lines = []
    width = max(len(k) for k, _ in SPACE_VARIABLES + [(s, "") for s in SPACE_SECRETS])
    lines.append("  Variables (safe to set as plain Variables):")
    for key, default in SPACE_VARIABLES:
        lines.append(f"    {key:<{width}} = {os.getenv(key) or default}")
    lines.append("")
    lines.append("  Secrets (set as Secrets, not Variables):")
    for key in SPACE_SECRETS:
        value = os.getenv(key)
        lines.append(f"    {key:<{width}} = {value if value else '<not set locally>'}")
    lines.append("")
    lines.append("  Dashboard logins are whatever ADMIN_PASSWORD_HASH and")
    lines.append("  VIEWER_PASSWORD_HASH above were generated from. To rotate:")
    lines.append(
        '    python -c "from werkzeug.security import generate_password_hash as h;'
        " print(h(input('new password: ')))\""
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
