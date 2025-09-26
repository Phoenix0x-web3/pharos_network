import argparse
import os
import platform
import subprocess
import sys


parser = argparse.ArgumentParser()
parser.add_argument(
    "-d",
    "--dev",
    action="store_true",
    help="Use it to install development dependencies",
)
args = parser.parse_args()


def install_dependencies(pip_path: str):
    if args.dev:
        print("\nInstalling dev dependencies...")
        subprocess.run([pip_path, "install", "-r", "requirements-dev.txt"], check=True)
    else:
        print("\nInstalling base dependencies...")
        subprocess.run([pip_path, "install", "-r", "requirements.txt"], check=True)


is_windows = platform.system() == "Windows"
venv_dir = "venv"

print("Creating virtual environment...")
subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)

if is_windows:
    activate = os.path.join(venv_dir, "Scripts", "activate")
    python_path = os.path.join(venv_dir, "Scripts", "python")
    pip_path = os.path.join(venv_dir, "Scripts", "pip")
else:
    activate = f"source {venv_dir}/bin/activate"
    python_path = f"{venv_dir}/bin/python"
    pip_path = os.path.join(venv_dir, "bin", "pip")

install_dependencies(pip_path)

subprocess.run([python_path, "-m", "utils.create_files"], check=True)

print("\nInstallation completed!")
print("To activate environment and run:")
print(f"  {activate}")

print("  python main.py")
