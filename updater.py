"""
WakerVoice — delta auto-update (Windows, PyInstaller onedir).

Ý tưởng: mỗi release kèm `manifest.json` (path -> sha256). App so manifest mới với
manifest local (đóng trong bundle) -> chỉ tải file đã đổi từ kho blob
địa-chỉ-theo-hash (một GitHub Release cố định tag `blobs`, asset đặt tên = sha256).
Một helper PowerShell đợi app thoát rồi đè file + khởi động lại.

Các hàm THUẦN (is_newer / diff_manifest) tách riêng để unit-test không cần mạng.
"""

import os
import sys
import json
import hashlib
import tempfile
import subprocess
import urllib.request

from version import __version__

REPO = "tdat-dev/ByteVoice"
BLOBS_TAG = "blobs"
_UA = {"User-Agent": "WakerVoice-Updater"}


# ----------------------- hàm thuần (test được) -----------------------
def _parse_version(s):
    """'v1.10.2' -> (1, 10, 2). Bỏ tiền tố 'v', cắt phần pre-release."""
    s = (s or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in s.split("."):
        num = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(remote, local):
    """remote mới hơn local? (semver, an toàn với chuỗi rác)."""
    return _parse_version(remote) > _parse_version(local)


def diff_manifest(local, remote):
    """(fetch, delete): file cần tải (đổi/mới) và file cần xoá (thừa)."""
    fetch = {p for p, h in remote.items() if local.get(p) != h}
    delete = {p for p in local if p not in remote}
    return fetch, delete


# ----------------------- môi trường -----------------------
def current_version():
    return __version__


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def install_dir():
    """Thư mục cài (chứa WakerVoice.exe + _internal). Chỉ ý nghĩa khi frozen."""
    return os.path.dirname(sys.executable)


def app_data_dir():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "WakerVoice")
    os.makedirs(d, exist_ok=True)
    return d


def sha256_file(path, _buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


def local_manifest():
    """Manifest của bản đang cài (ghi cạnh exe lúc release). {} nếu thiếu."""
    p = os.path.join(install_dir(), "manifest.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("files", {})
    except Exception:
        return {}


# ----------------------- mạng -----------------------
def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url, dest, timeout=60):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)


def check_latest(timeout=8):
    """Trả {version, manifest_url, html_url} nếu có bản mới hơn, else None.
    Không bao giờ raise (lỗi mạng -> None)."""
    try:
        rel = _get_json(
            f"https://api.github.com/repos/{REPO}/releases/latest", timeout
        )
        tag = rel.get("tag_name", "")
        if not is_newer(tag, current_version()):
            return None
        manifest_url = None
        for a in rel.get("assets", []):
            if a.get("name") == "manifest.json":
                manifest_url = a.get("browser_download_url")
                break
        return {
            "version": _fmt_version(tag),
            "manifest_url": manifest_url,
            "html_url": rel.get("html_url", ""),
        }
    except Exception:
        return None


def _fmt_version(tag):
    return ".".join(str(x) for x in _parse_version(tag))


def _blob_url(sha):
    return f"https://github.com/{REPO}/releases/download/{BLOBS_TAG}/{sha}"


def download_blob(sha, dest):
    """Tải 1 blob theo hash -> verify sha256 -> ghi dest. Thử lại 1 lần."""
    for attempt in range(2):
        try:
            _download(_blob_url(sha), dest)
            if sha256_file(dest) == sha:
                return
        except Exception:
            pass
    raise RuntimeError(f"Tải/verify blob thất bại: {sha[:12]}")


def stage_update(remote_manifest, progress_cb=None):
    """Tải các file đổi về staging; ghi manifest.json + delete.txt.
    Trả (staging_dir, delete_set). Raise nếu lỗi (chưa đụng bản đang cài)."""
    files = remote_manifest.get("files", {})
    fetch, delete = diff_manifest(local_manifest(), files)

    staging = os.path.join(app_data_dir(), "staging")
    # dọn staging cũ
    import shutil
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)

    total = len(fetch)
    for i, rel in enumerate(sorted(fetch), 1):
        dest = os.path.join(staging, *rel.split("/"))
        download_blob(files[rel], dest)
        if progress_cb:
            progress_cb(int(i * 100 / max(1, total)), rel)

    with open(os.path.join(staging, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(remote_manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(staging, "delete.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(delete)))
    return staging, delete


_HELPER_PS1 = r"""
param([int]$ProcPid, [string]$Install, [string]$Staging)
$ErrorActionPreference = 'Continue'
$log = Join-Path $env:LOCALAPPDATA 'WakerVoice\update.log'
function Log($m) { "$(Get-Date -Format o)  $m" | Out-File -FilePath $log -Append -Encoding utf8 }
Log "apply start pid=$ProcPid install=$Install staging=$Staging"
try { Wait-Process -Id $ProcPid -Timeout 30 -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Milliseconds 400
# Đè file đổi (giữ nguyên file không đổi đã có sẵn)
robocopy $Staging $Install /E /NFL /NDL /NJH /NJS /R:3 /W:1 /XF manifest.json delete.txt | Out-Null
Copy-Item (Join-Path $Staging 'manifest.json') (Join-Path $Install 'manifest.json') -Force
# Xoá file thừa
$del = Join-Path $Staging 'delete.txt'
if (Test-Path $del) {
  Get-Content $del | Where-Object { $_ -ne '' } | ForEach-Object {
    $t = Join-Path $Install $_
    if (Test-Path $t) { Remove-Item $t -Force -ErrorAction SilentlyContinue; Log "del $_" }
  }
}
Remove-Item $Staging -Recurse -Force -ErrorAction SilentlyContinue
Log "relaunch"
Start-Process -FilePath (Join-Path $Install 'WakerVoice.exe')
Log "done"
"""


def write_helper_and_spawn(staging_dir):
    """Sinh helper PowerShell, chạy nền. Gọi xong app nên quit() ngay.

    QUAN TRỌNG (app windowed/noconsole): PHẢI gắn stdin/stdout/stderr=DEVNULL
    và dùng CREATE_NO_WINDOW. Nếu không, PowerShell thừa kế handle console
    không hợp lệ -> chết ngay khi khởi động, không kịp ghi log (update "kẹt":
    đã tải staging xong, app thoát, nhưng file không được thay)."""
    ps1 = os.path.join(app_data_dir(), "apply_update.ps1")
    with open(ps1, "w", encoding="utf-8") as f:
        f.write(_HELPER_PS1)
    import shutil
    exe = (shutil.which("powershell")
           or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "WindowsPowerShell", "v1.0",
                           "powershell.exe"))
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        [exe, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-ExecutionPolicy", "Bypass", "-File", ps1,
         str(os.getpid()), install_dir(), staging_dir],
        creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True,
    )
