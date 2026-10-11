# Monika VPet Desktop Auto Launcher for MAS / Ren'Py 6.99
# Put this file in game/Submods/monika vpet/
init -10 python:
    import os
    import glob
    import subprocess
    import shutil

    _monika_vpet_process = None
    _monika_vpet_log_handle = None

    def _monika_vpet_log(message):
        global _monika_vpet_log_handle
        try:
            log_path = os.path.join(renpy.config.gamedir, "monika_vpet_autostart.log")
            with open(log_path, "a") as log_file:
                log_file.write(str(message) + "\n")
        except Exception:
            pass

    def _monika_vpet_find_pythonw():
        # Explicit override wins, if supplied.
        custom = os.environ.get("MONIKA_PYTHONW", "")
        if custom and os.path.isfile(custom):
            return custom

        candidates = []
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            # Microsoft Store Python installs often place python.exe/pythonw.exe here.
            candidates += glob.glob(os.path.join(
                local, "Microsoft", "WindowsApps",
                "PythonSoftwareFoundation.Python.3.11_*", "pythonw.exe"))
            candidates += glob.glob(os.path.join(
                local, "Microsoft", "WindowsApps",
                "PythonSoftwareFoundation.Python.3.*_*", "pythonw.exe"))
            candidates += glob.glob(os.path.join(
                local, "Programs", "Python", "Python*", "pythonw.exe"))

        candidates += glob.glob(r"C:\Python*\pythonw.exe")
        candidates += glob.glob(r"C:\Program Files\Python*\pythonw.exe")
        candidates += glob.glob(r"C:\Program Files (x86)\Python*\pythonw.exe")

        # Prefer real-looking discovered paths over the WindowsApps command alias.
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

        # Last resort: PATH lookup (may be an app execution alias).
        if hasattr(shutil, "which"):
            found = shutil.which("pythonw.exe") or shutil.which("pythonw")
            if found and os.path.isfile(found):
                return found
        return None

    def _monika_vpet_start():
        global _monika_vpet_process, _monika_vpet_log_handle
        try:
            script = os.path.join(renpy.config.gamedir, "Submods", "monika vpet", "monika_desktop.py")
            _monika_vpet_log("Launcher callback fired.")
            _monika_vpet_log("Looking for script: " + script)
            if not os.path.isfile(script):
                _monika_vpet_log("ERROR: desktop script not found.")
                try:
                    renpy.notify("Monika VPet: không tìm thấy monika_desktop.py")
                except Exception:
                    pass
                return

            if _monika_vpet_process is not None and _monika_vpet_process.poll() is None:
                _monika_vpet_log("Desktop process already running.")
                return

            pythonw = _monika_vpet_find_pythonw()
            _monika_vpet_log("Selected pythonw: " + str(pythonw))
            if not pythonw:
                _monika_vpet_log("ERROR: pythonw.exe not found.")
                try:
                    renpy.notify("Monika VPet: không tìm thấy pythonw.exe; xem monika_vpet_autostart.log")
                except Exception:
                    pass
                return

            log_path = os.path.join(renpy.config.gamedir, "monika_vpet_desktop.log")
            log_handle = open(log_path, "a")
            # Pass MAS PID so the desktop pet can close itself even if Ren'Py
            # quit callbacks do not run (for example, if MAS crashes).
            # Ren'Py/MAS may expose non-string entries in os.environ.
            # subprocess.Popen on Windows requires every environment key/value
            # to be a string, so sanitize the inherited environment first.
            child_env = {}
            for env_key, env_value in os.environ.items():
                if env_key is None or env_value is None:
                    continue
                try:
                    env_key = str(env_key)
                    env_value = str(env_value)
                    child_env[env_key] = env_value
                except Exception:
                    _monika_vpet_log("Skipping invalid environment entry: " + repr(env_key))
            child_env["MONIKA_MAS_PID"] = str(os.getpid())
            try:
                # First try with the MAS PID so the pet can detect a crashed MAS.
                _monika_vpet_process = subprocess.Popen(
                    [pythonw, script, "--mas-pid", str(os.getpid())],
                    cwd=os.path.dirname(script),
                    stdout=log_handle,
                    stderr=log_handle,
                    env=child_env
                )
            except TypeError as env_error:
                # Some Ren'Py 6.99/Python 2 Windows builds reject the inherited
                # environment mapping even after sanitizing it. Retry without
                # an explicit env; Popen then inherits the process environment.
                _monika_vpet_log("Environment launch failed; retrying without explicit env: " + repr(env_error))
                _monika_vpet_process = subprocess.Popen(
                    [pythonw, script, "--mas-pid", str(os.getpid())],
                    cwd=os.path.dirname(script),
                    stdout=log_handle,
                    stderr=log_handle
                )
            # Keep the handle alive for the child process output stream.
            _monika_vpet_log_handle = log_handle
            _monika_vpet_log("Started desktop process; PID=" + str(_monika_vpet_process.pid))
        except Exception as e:
            _monika_vpet_log("EXCEPTION while starting: " + repr(e))
            try:
                renpy.notify("Monika VPet không khởi động được; xem monika_vpet_autostart.log")
            except Exception:
                pass

    def _monika_vpet_stop():
        global _monika_vpet_process, _monika_vpet_log_handle
        try:
            if _monika_vpet_process is not None and _monika_vpet_process.poll() is None:
                _monika_vpet_process.terminate()
                _monika_vpet_log("Terminated desktop process when MAS quit.")
        except Exception as e:
            _monika_vpet_log("Exception stopping desktop: " + repr(e))
        try:
            if _monika_vpet_log_handle is not None:
                _monika_vpet_log_handle.close()
                _monika_vpet_log_handle = None
        except Exception:
            pass

    # Try the normal start callback and after-load callback. Duplicate calls are
    # harmless because _monika_vpet_start checks whether the process is alive.
    if hasattr(config, "start_callbacks"):
        config.start_callbacks.append(_monika_vpet_start)
    if hasattr(config, "after_load_callbacks"):
        config.after_load_callbacks.append(_monika_vpet_start)
    if hasattr(config, "quit_callbacks"):
        config.quit_callbacks.append(_monika_vpet_stop)
