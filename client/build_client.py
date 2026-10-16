from __future__ import annotations


import subprocess
import sys



CMD = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--onefile",
    "--noconsole",
    "--name",
    "THLProClient",
    "--collect-all",
    "pystray",
    "--collect-all",
    "PIL",
    "--hidden-import",
    "thlpro_client.rtd_client",
    "--hidden-import",
    "thlpro_client.capture_service",
    "--hidden-import",
    "thlpro_client.sender_service",
    "--hidden-import",
    "thlpro_client.config_poller",
    "thlpro_client/__main__.py",
]



if __name__ == "__main__":
    subprocess.check_call(CMD)


    print("Build concluído. Arquivo em dist/THLProClient.exe")