"""Build source ZIP and a dependency-free Python zipapp from an allowlist."""
import argparse
import hashlib
from pathlib import Path
import tempfile
import shutil
import zipapp
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def source_files():
    fixed = [".gitignore", "pyproject.toml", "LICENSE", "README.md", "README.en.md",
             "CHANGELOG.md", "CONTRIBUTING.md", ".github/workflows/tests.yml",
             ".github/workflows/release.yml", "scripts/build_release.py"]
    paths = [ROOT / name for name in fixed]
    paths += sorted((ROOT / "w3compat").glob("*.py"))
    paths += sorted((ROOT / "tests").glob("test_*.py"))
    paths += sorted((ROOT / "docs").glob("*.md"))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or linked release source: " + path.name)
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    version = (ROOT / "w3compat/__init__.py").read_text("utf-8").split('__version__ = "', 1)[1].split('"', 1)[0]
    name = "witcher3-compat-tool-" + version
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.out / (name + ".zip")
    app = args.out / (name + ".pyz")
    hashes = args.out / "SHA256SUMS.txt"
    if any(path.exists() for path in (source, app, hashes)):
        raise ValueError("Release outputs already exist; use a fresh output directory")
    files = source_files()
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, name + "/" + path.relative_to(ROOT).as_posix())
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        shutil.copytree(ROOT / "w3compat", directory / "w3compat", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "LICENSE", directory / "LICENSE")
        zipapp.create_archive(directory, target=app, main="w3compat.cli:main", compressed=True)
    hashes.write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in (source, app)), encoding="utf-8", newline="\n")
    print(f"Source: {source}\nZipapp: {app}\nChecksums: {hashes}")


if __name__ == "__main__":
    main()
