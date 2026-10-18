"""Start with Windows, elevated, WITHOUT a UAC prompt, via Task Scheduler.

A Startup-folder shortcut to an admin exe would show a UAC dialog at every
logon, which is exactly the kind of thing that makes a user give up. A
scheduled task with "run with highest privileges" starts silently instead.
The task XML also removes the default 3-day kill limit, allows running on
battery, and restarts the app if it ever crashes.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from xml.sax.saxutils import escape

import config

log = logging.getLogger("ocr2heb.autostart")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _task_xml(exe_path: str) -> str:
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    user_id = f"{domain}\\{user}" if domain and user else user
    user_xml = f"<UserId>{escape(user_id)}</UserId>" if user_id else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>OCR2Heb - screen translator (starts at logon)</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled>{user_xml}</LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">{user_xml}<LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe_path)}</Command>
      <WorkingDirectory>{escape(os.path.dirname(exe_path))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def ensure_autostart(exe_path: str) -> bool:
    """Create or refresh the logon task so it points at exe_path. Idempotent."""
    fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="ocr2heb_task_")
    os.close(fd)
    try:
        with open(xml_path, "w", encoding="utf-16") as fh:
            fh.write(_task_xml(exe_path))
        proc = subprocess.run(["schtasks", "/Create", "/TN", config.TASK_NAME, "/XML", xml_path, "/F"],
                              capture_output=True, timeout=30, creationflags=_NO_WINDOW)
        ok = proc.returncode == 0
        log.info("autostart task %s (exit %s) %s", "ok" if ok else "FAILED", proc.returncode,
                 (proc.stderr or b"").decode("utf-8", "replace").strip())
        return ok
    except Exception:
        log.exception("could not create autostart task")
        return False
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


def remove_autostart() -> bool:
    try:
        proc = subprocess.run(["schtasks", "/Delete", "/TN", config.TASK_NAME, "/F"],
                              capture_output=True, timeout=30, creationflags=_NO_WINDOW)
        return proc.returncode == 0
    except Exception:
        log.exception("could not remove autostart task")
        return False
