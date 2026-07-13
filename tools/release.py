"""
WakerVoice — script phát hành (build + manifest + blob delta + GitHub Release).

Dùng:
    python tools/release.py            # build + publish version trong version.py
    python tools/release.py --no-build # dùng dist/WakerVoice sẵn có
    python tools/release.py --dry-run  # in kế hoạch, không upload/tạo release

Nguyên tắc delta: kho blob địa-chỉ-theo-hash ở release cố định tag `blobs`
(asset đặt tên = sha256). Mỗi version release chỉ upload blob của file ĐỔI so với
release trước (release đầu có updater -> không upload blob nào, người dùng cài
bằng full zip). Manifest đi kèm cả full zip cho người cài mới.
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from version import __version__          # noqa: E402
from updater import sha256_file, _get_json, REPO, BLOBS_TAG  # noqa: E402

DIST = os.path.join(ROOT, "dist", "WakerVoice")


def run(cmd, **kw):
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def build():
    run([os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
         "-m", "PyInstaller",
         os.path.join(ROOT, "WakerVoice.spec"), "--noconfirm", "--clean"], cwd=ROOT)


def make_manifest():
    """sha256 mọi file trong dist/WakerVoice (trừ manifest.json). path dùng '/'.
    Ghi dist/WakerVoice/manifest.json, trả dict files."""
    files = {}
    for r, _d, fs in os.walk(DIST):
        for f in fs:
            full = os.path.join(r, f)
            rel = os.path.relpath(full, DIST).replace("\\", "/")
            if rel == "manifest.json":
                continue
            files[rel] = sha256_file(full)
    manifest = {"version": __version__, "files": files}
    with open(os.path.join(DIST, "manifest.json"), "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)
    return files


def prev_files():
    """files{} của release 'latest' hiện tại (trước khi publish). {} nếu chưa có."""
    try:
        rel = _get_json(f"https://api.github.com/repos/{REPO}/releases/latest")
        url = next((a["browser_download_url"] for a in rel.get("assets", [])
                    if a["name"] == "manifest.json"), None)
        if not url:
            return {}
        return _get_json(url).get("files", {})
    except Exception:
        return {}


def gh_json(args):
    out = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout) if out.stdout.strip() else None


def ensure_blobs_release():
    info = gh_json(["release", "view", BLOBS_TAG, "--repo", REPO, "--json", "tagName"])
    if info:
        return
    print("  tạo release blobs…")
    run(["gh", "release", "create", BLOBS_TAG, "--repo", REPO, "--title", "blobs",
         "--notes", "Content-addressed update blobs (sha256). Do not delete.",
         "--latest=false"])


def existing_blob_names():
    info = gh_json(["release", "view", BLOBS_TAG, "--repo", REPO, "--json", "assets"])
    if not info:
        return set()
    return {a["name"] for a in info.get("assets", [])}


def upload_blobs(to_upload):
    """to_upload: dict path->hash. Upload mỗi hash chưa có (asset name = hash)."""
    if not to_upload:
        print("  không có blob cần upload.")
        return
    ensure_blobs_release()
    have = existing_blob_names()
    tmp = tempfile.mkdtemp(prefix="wakervoice_blobs_")
    staged = []
    for rel, h in to_upload.items():
        if h in have:
            continue
        src = os.path.join(DIST, *rel.split("/"))
        dst = os.path.join(tmp, h)            # tên file = hash
        if not os.path.exists(dst):
            import shutil
            shutil.copy2(src, dst)
        staged.append((dst, rel))
    if not staged:
        print("  mọi blob đã tồn tại, bỏ qua upload.")
        return
    print(f"  upload {len(staged)} blob…")
    # upload theo lô để tránh dòng lệnh quá dài
    for i in range(0, len(staged), 20):
        batch = [p for p, _ in staged[i:i + 20]]
        run(["gh", "release", "upload", BLOBS_TAG, "--repo", REPO, "--clobber"] + batch)


def make_zip():
    out = os.path.join(ROOT, "dist", f"WakerVoice-v{__version__}-win64-cloud.zip")
    print(f"  nén {out}…")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as z:
        for r, _d, fs in os.walk(DIST):
            for f in fs:
                full = os.path.join(r, f)
                arc = os.path.join("WakerVoice", os.path.relpath(full, DIST))
                z.write(full, arc)
    return out


def publish_version(zip_path):
    tag = f"v{__version__}"
    manifest_path = os.path.join(DIST, "manifest.json")
    notes = (f"WakerVoice {tag}. Bản cài mới: tải zip bên dưới, giải nén, chạy WakerVoice.exe.\n"
             "Bản đã cài (>=1.1.0) sẽ tự đề xuất cập nhật delta.")
    print(f"  tạo release {tag}…")
    run(["gh", "release", "create", tag, "--repo", REPO, "--title", f"WakerVoice {tag}",
         "--notes", notes, "--latest",
         f"{manifest_path}#manifest.json",
         f"{zip_path}#WakerVoice {tag} (Windows 64-bit, cloud)"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"== Release WakerVoice v{__version__} ==")
    if not args.no_build:
        print("[1] build"); build()
    else:
        print("[1] build: bỏ qua (--no-build)")

    print("[2] manifest")
    new_files = make_manifest()
    prev = prev_files()
    to_upload = ({} if not prev
                 else {p: h for p, h in new_files.items() if prev.get(p) != h})
    print(f"    {len(new_files)} file; prev={len(prev)}; blob đổi cần upload={len(to_upload)}")

    if args.dry_run:
        for p in sorted(to_upload):
            print("    +", p)
        print("[dry-run] dừng — không upload/tạo release.")
        return

    print("[3] upload blob delta")
    upload_blobs(to_upload)
    print("[4] zip full")
    zip_path = make_zip()
    print("[5] publish")
    publish_version(zip_path)
    print("DONE:", f"https://github.com/{REPO}/releases/tag/v{__version__}")


if __name__ == "__main__":
    main()
