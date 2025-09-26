import json
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Optional, Tuple

import git
from loguru import logger

from data.settings import Settings
from utils.browser import Browser


def get_local_commit(repo_path: str = ".") -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetches the current HEAD commit information from the local Git repository.
    Args:
        repo_path: Path to the Git repository (default: current directory).

    Returns:
        Tuple containing (commit_hash, commit_date, commit_message) or (None, None, None) if not a Git repo.
    """
    try:
        repo = git.Repo(repo_path)
        head_commit = repo.head.commit
        commit_date = datetime.fromtimestamp(head_commit.committed_date, tz=timezone.utc).isoformat()
        return head_commit.hexsha[:7], commit_date, head_commit.message.strip()
    except git.InvalidGitRepositoryError:
        logger.debug(f"No valid Git repository at {repo_path}")
        return None, None, None
    except Exception as e:
        logger.error(f"Error fetching local commit: {e}")
        return None, None, None


def get_latest_commit_from_git(repo_path: str = ".", remote_name: str = "origin") -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetches the latest commit information from a remote Git repository using gitpython.

    Args:
        repo_path: Path to the Git repository (default: current directory).
        remote_name: Name of the remote (default: "origin").

    Returns:
        Tuple containing (commit_hash, commit_date, commit_message) or (None, None, None) on error.
    """
    try:
        repo = git.Repo(repo_path)
        remote = repo.remotes[remote_name]
        remote.fetch()

        remote_head = repo.refs[f"{remote_name}/{repo.active_branch.name}"]
        commit = repo.commit(remote_head)

        commit_date = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc).isoformat()
        return commit.hexsha[:7], commit_date, commit.message.strip()
    except git.InvalidGitRepositoryError:
        logger.debug(f"No valid Git repository at {repo_path}")
        return None, None, None
    except Exception as e:
        logger.error(f"Error fetching from Git: {e}. Ensure SSH/HTTPS credentials are configured for private repositories.")
        return None, None, None


async def get_latest_commit_from_api(repo_owner: str, repo_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Fetches the latest commit information from a GitHub repository using the Browser class.

    Args:
        repo_owner: The owner of the repository.
        repo_name: The name of the repository.

    Returns:
        Tuple containing (commit_hash, commit_date, commit_message) or (None, None, None) on error.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    browser = Browser()
    try:
        repo_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        response = await browser.get(url=repo_url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to fetch repository info: HTTP {response.status_code}")
            if response.status_code == 403:
                logger.warning("Access to private repository may require authentication.")
            return None, None, None
        data = response.json()
        default_branch = data.get("default_branch", "main")

        commit_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/{default_branch}"
        response = await browser.get(url=commit_url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to fetch commit: HTTP {response.status_code}")
            if response.status_code == 403:
                logger.warning("Access to private repository may require authentication.")
            return None, None, None
        data = response.json()
        return (
            data.get("sha", "")[:7],
            data.get("commit", {}).get("author", {}).get("date"),
            data.get("commit", {}).get("message", "").strip(),
        )
    except Exception as e:
        logger.error(f"Error fetching commit from API: {e}")
        return None, None, None


def read_local_version(version_file: str = "files/version.json") -> Tuple[Optional[str], Optional[str]]:
    """
    Reads the local version information from a file.

    Args:
        version_file: Path to the version file (default: "files/version.json").

    Returns:
        Tuple containing (commit_hash, commit_date) or (None, None) on error.
    """
    try:
        if os.path.exists(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("hash"), data.get("date")
        logger.debug(f"No version file found at {version_file}")
        return None, None
    except Exception as e:
        logger.error(f"Error reading local version from {version_file}: {e}")
        return None, None


def save_local_version(commit_hash: str, commit_date: str, version_file: str = "files/version.json") -> None:
    """
    Saves the current version information to a file.

    Args:
        commit_hash: The commit hash.
        commit_date: The commit date.
        version_file: Path to the version file (default: "version.json").
    """
    try:
        with open(version_file, "w", encoding="utf-8") as f:
            json.dump({"hash": commit_hash, "date": commit_date}, f, indent=2)
        logger.debug(f"Saved version info to {version_file}: {commit_hash}")
    except Exception as e:
        logger.error(f"Error saving version to {version_file}: {e}")


def perform_git_pull(repo_path: str = ".", remote_name: str = "origin") -> bool:
    """
    Performs a git pull operation to update the repository.

    Args:
        repo_path: Path to the Git repository (default: current directory).
        remote_name: Name of the remote (default: "origin").

    Returns:
        True if the pull was successful, False otherwise.
    """
    try:
        repo = git.Repo(repo_path)
        remote = repo.remotes[remote_name]
        remote.pull()
        logger.info("Successfully performed git pull")
        return True
    except Exception as e:
        logger.error(f"Error performing git pull: {e}")
        return False


def restart_program():
    """
    Restarts the current program with the same arguments.
    """
    is_windows = platform.system() == "Windows"
    if is_windows:
        exit("Please restart the program on Windows after GitHub updates.")

    logger.info("Restarting program after update")
    python = sys.executable
    os.execv(python, [python] + sys.argv)


async def check_for_updates(
    repo_name: str,
    repo_owner: str = "Phoenix0x-web3",
    version_file: str = "files/version.json",
    repo_path: str = ".",
    remote_name: str = "origin",
    repo_private: bool = False,
) -> None:
    """
    Checks for updates using gitpython if a Git repo exists, otherwise falls back to GitHub API via Browser.
    Notifies the user if a newer version is available. On first run, saves local HEAD commit for Git repos.
    For Git repos, prompts to perform git pull and restarts the program if user agrees.

    Args:
        repo_name: The name of the repository.
        repo_owner: The owner of the repository (default: "Phoenix0x-web3").
        version_file: Path to the version file (default: "files/version.json").
        repo_path: Path to the Git repository (default: current directory).
        remote_name: Name of the remote (default: "origin").
    """

    if not Settings().check_git_updates:
        return

    repo_name = repo_name.strip().lower().replace(" ", "_")

    logger.debug(f"Checking for updates in {repo_owner}/{repo_name}")

    is_git_repo = os.path.exists(os.path.join(repo_path, ".git"))
    latest_hash = None
    latest_date = None
    latest_message = None
    local_hash = None
    local_date = None

    if is_git_repo:
        logger.debug("Detected Git repository. Fetching local HEAD commit...")
        local_hash, local_date, _ = get_local_commit(repo_path)
        logger.debug("Fetching updates from remote...")
        if repo_private:
            latest_hash, latest_date, latest_message = get_latest_commit_from_git(repo_path, remote_name)
            if not latest_hash:
                logger.warning(
                    "Warning: Failed to fetch updates via Git. Ensure SSH/HTTPS credentials are configured for private repositories."
                )
            if local_hash == latest_hash:
                latest_dt = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
                formatted_date = latest_dt.strftime("%d.%m.%Y %H:%M UTC")
                logger.info(f"You are using the latest version (commit from {formatted_date})")
                return
    else:
        logger.debug("No Git repository detected (possibly downloaded as ZIP). Using GitHub API for update check.")

    if not latest_hash or not latest_date:
        latest_hash, latest_date, latest_message = await get_latest_commit_from_api(repo_owner, repo_name)

    if not latest_hash or not latest_date:
        return

    local_version_hash, local_version_date = read_local_version(version_file)

    if not local_version_hash or not local_version_date:
        if is_git_repo and local_hash and local_date:
            save_local_version(local_hash, local_date, version_file)
            if local_hash == latest_hash:
                latest_dt = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
                formatted_date = latest_dt.strftime("%d.%m.%Y %H:%M UTC")
                logger.debug(f"You are using the latest version (commit from {formatted_date})")
                return
        else:
            # For non-Git (e.g., ZIP), initialize with latest remote commit
            save_local_version(latest_hash, latest_date, version_file)
            latest_dt = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
            formatted_date = latest_dt.strftime("%d.%m.%Y %H:%M UTC")
            logger.debug(f"Initializing version tracking: {formatted_date} (commit {latest_hash})")
            return

    if local_version_hash == latest_hash:
        latest_dt = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
        formatted_date = latest_dt.strftime("%d.%m.%Y %H:%M UTC")
        logger.info(f"You are using the latest version (commit from {formatted_date})")
        return

    # Update available
    latest_dt = datetime.fromisoformat(latest_date.replace("Z", "+00:00"))
    formatted_date = latest_dt.strftime("%d.%m.%Y %H:%M UTC")
    repo_url = f"https://github.com/{repo_owner}/{repo_name}"
    print(
        f"Update available!\n"
        f"Latest update: {formatted_date} (commit {latest_hash})\n"
        f"Commit message: {latest_message}\n"
        f"Use: git pull (if cloned via Git)\n"
        f"Or download update: {repo_url}"
    )
    logger.warning(f"Update available: {latest_hash} from {formatted_date}")

    if is_git_repo:
        while True:
            response = input("Perform update y/N? ").strip().lower()
            if response in ("y", "n", ""):
                break
            print("Please enter 'y' or 'n'.")

        if response == "y":
            if perform_git_pull(repo_path, remote_name):
                save_local_version(latest_hash, latest_date, version_file)
                print("Update successful. Restarting program...")
                restart_program()
            else:
                print("Update failed. Continuing with current version.")
        else:
            print("Update skipped. Continuing with current version.")
    else:
        save_local_version(latest_hash, latest_date, version_file)
