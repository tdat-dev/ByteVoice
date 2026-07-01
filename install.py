"""
Sottra — tích hợp Windows
=========================
App ship dạng zip portable (không installer) -> tự lo phần "cài":
  * Lối tắt Start Menu + Desktop trỏ tới Sottra.exe (mở nhanh, tìm được ở Start).
  * Chạy cùng Windows qua HKCU\\...\\Run (đăng nhập là bật sẵn ở khay).

Chỉ có ý nghĩa khi chạy bản đóng gói (frozen). Mọi hàm đều nuốt lỗi -> không
bao giờ làm app chết vì không ghi được registry/shortcut.
"""

import os
import sys
import subprocess

APP_NAME = "Sottra"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_CREATE_NO_WINDOW = 0x08000000


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def _exe_path():
    """Đường dẫn Sottra.exe hiện tại (frozen). Dev: python.exe -> đừng dùng để cài."""
    return sys.executable


# ----------------------- chạy cùng Windows (registry Run) -----------------------
def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, APP_NAME)
        return os.path.normcase(val.strip('"')) == os.path.normcase(_exe_path())
    except Exception:
        return False


def set_startup(on):
    """Bật/tắt tự chạy lúc đăng nhập. Trả True nếu thành công."""
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{_exe_path()}"')
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


# ----------------------- lối tắt (.lnk) -----------------------
def _start_menu_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")


def _desktop_dir():
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _make_lnk(dest_dir):
    """Tạo <dest_dir>\\Sottra.lnk trỏ tới exe (qua WScript.Shell trong PowerShell —
    không cần pywin32). Trả path .lnk hoặc None nếu lỗi."""
    exe = _exe_path()
    lnk = os.path.join(dest_dir, APP_NAME + ".lnk")

    def q(s):                                   # bọc single-quote cho PowerShell an toàn
        return "'" + s.replace("'", "''") + "'"

    ps = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut({q(lnk)});"
        f"$s.TargetPath={q(exe)};"
        f"$s.WorkingDirectory={q(os.path.dirname(exe))};"
        f"$s.IconLocation={q(exe + ',0')};"
        "$s.Description='Sottra — voice to text';"
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-Command", ps],
            creationflags=_CREATE_NO_WINDOW, timeout=15, check=False,
        )
        return lnk if os.path.exists(lnk) else None
    except Exception:
        return None


def create_shortcuts():
    """Tạo lối tắt ở Start Menu + Desktop. Trả list path đã tạo."""
    made = []
    for d in (_start_menu_dir(), _desktop_dir()):
        try:
            if os.path.isdir(d):
                p = _make_lnk(d)
                if p:
                    made.append(p)
        except Exception:
            pass
    return made
