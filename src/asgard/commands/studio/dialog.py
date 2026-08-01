"""시스템 폴더 고르기 — 이 기계에 그런 대화상자가 있는가, 있으면 어떤 명령인가.

`workspaces`(고르기)와 `snapshot`(능력 알리기)이 둘 다 이걸 묻는다. 어느 한쪽에 두면
다른 쪽이 그쪽을 부르게 되고, 그 순간 둘이 서로를 부른다 — 플랫폼을 묻는 일은 둘 다의
아래에 있으므로 여기 따로 선다.
"""

from __future__ import annotations

import os
import shutil
import sys

_FOLDER_DIALOG = {
    "darwin": [
        "osascript",
        "-e",
        'POSIX path of (choose folder with prompt "Asgard 작업 공간으로 쓸 폴더를 고르세요")',
    ],
    "win32": [
        "powershell",
        "-NoProfile",
        "-Command",
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d=New-Object System.Windows.Forms.FolderBrowserDialog;"
        "if($d.ShowDialog() -eq 'OK'){Write-Output $d.SelectedPath}",
    ],
}


def folder_dialog_available() -> bool:
    if sys.platform in _FOLDER_DIALOG:
        return bool(shutil.which(_FOLDER_DIALOG[sys.platform][0]))
    return bool(shutil.which("zenity") or shutil.which("kdialog"))


def _folder_dialog_command() -> list[str] | None:
    if sys.platform in _FOLDER_DIALOG:
        return _FOLDER_DIALOG[sys.platform] if shutil.which(_FOLDER_DIALOG[sys.platform][0]) else None
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", "--directory", "--title=Asgard 작업 공간"]
    if shutil.which("kdialog"):
        return ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]
    return None
