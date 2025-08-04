# install.py
import os
import subprocess
import sys
import platform

is_windows = platform.system() == "Windows"
venv_dir = "venv"

print("Creating virtual environment...")
subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)

if is_windows:
    activate = os.path.join(venv_dir, "Scripts", "activate.bat")
else:
    activate = f"source {venv_dir}/bin/activate"

print("\nInstalling requirements...")
pip = os.path.join(venv_dir, "Scripts" if is_windows else "bin", "pip")
subprocess.run([pip, "install", "-r", "requirements.txt"], check=True)

print("\nInstallation completed!")
print("To activate environment and run:")
print(f"  {activate}")
print("  python main.py")
