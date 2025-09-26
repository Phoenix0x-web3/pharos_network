import logging
import platform
import sys

logger = logging.getLogger(__name__)


def get_allowed_python_versions() -> list[str]:
    try:
        with open("python-version", "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        logger.warning("No python-version file found")
        return []

    versions = [line.strip() for line in lines if line.strip()]
    logger.debug("Allowed python versions: %s", versions)
    return versions


def get_current_major_minor() -> str:
    major, minor, _ = platform.python_version_tuple()
    return f"{major}.{minor}"


def check_python_version():
    allowed_versions = get_allowed_python_versions()
    if not allowed_versions:
        sys.exit("No allowed Python versions specified in python-version")

    current_version = get_current_major_minor()
    if current_version not in allowed_versions:
        sys.exit(f"Incompatible Python version {platform.python_version()}.\nAllowed versions: {', '.join(allowed_versions)}")

    logger.debug("Python version %s is allowed", current_version)
