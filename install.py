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
    activate = os.path.join(venv_dir, "Scripts", "activate")
    python_path = os.path.join(venv_dir, "Scripts", "python")
else:
    activate = f"source {venv_dir}/bin/activate"
    python_path = f"{venv_dir}/bin/python"

print("\nInstalling requirements...")
pip = os.path.join(venv_dir, "Scripts" if is_windows else "bin", "pip")
subprocess.run([pip, "install", "-r", "requirements.txt"], check=True)


subprocess.run([python_path, "-m", "utils.create_files"], check=True)

print("\nInstallation completed!")
print("To activate environment and run:")
print(f"  {activate}")
print("  python main.py")
