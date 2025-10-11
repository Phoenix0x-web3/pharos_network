import asyncio
import platform

import inquirer
from colorama import Fore
from inquirer.themes import Default
from rich.console import Console

from check_python import check_python_version
from data.constants import PROJECT_NAME
from functions.activity import activity
from utils.create_files import create_files
from utils.db_api.models import Wallet
from utils.db_api.wallet_api import db
from utils.db_import_export_sync import Export, Import, Sync
from utils.git_version import check_for_updates
from utils.output import show_channel_info

console = Console()


PROJECT_ACTIONS = [
    "1. Run All Tasks In Random Order",
    "2. Twitter Tasks",
    "3. Join and Bind Discord",
    "4. Update Points",
    "5. Mint All Badges",
    "6. Transfer from Monad",
    "Back",
]


async def choose_action():
    cat_question = [
        inquirer.List(
            "category",
            message=Fore.LIGHTBLACK_EX + "Choose action",
            choices=["DB Actions", PROJECT_NAME, "Exit"],
        )
    ]

    answers = inquirer.prompt(cat_question, theme=Default())
    category = answers.get("category")

    if category == "Exit":
        console.print(f"[bold red]Exiting {PROJECT_NAME}...[/bold red]")
        raise SystemExit(0)

    if category == "DB Actions":
        actions = ["Import wallets to Database", "Sync wallets with tokens and proxies", "Export Database to CSV", "Back"]

    if category == PROJECT_NAME:
        actions = PROJECT_ACTIONS

    act_question = [
        inquirer.List(
            "action",
            message=Fore.LIGHTBLACK_EX + f"Choose action in '{category}'",
            choices=actions,
        )
    ]

    act_answer = inquirer.prompt(act_question, theme=Default())
    action = act_answer["action"]

    if action == "Import wallets to Database":
        console.print(f"[bold blue]Starting Import Wallets to DB[/bold blue]")
        await Import.wallets()
    elif action == "Sync wallets with tokens and proxies":
        console.print(f"[bold blue]Starting sync data in DB[/bold blue]")
        await Sync.sync_wallets_with_tokens_and_proxies()
    elif action == "Export Database to CSV":
        console.print(f"[bold blue]Starting Export Database to CSV[/bold blue]")
        await Export.data_to_csv()

    elif "1" in action:
        await activity(action=1)

    elif "2" in action:
        await activity(action=2)

    elif "3" in action:
        await activity(action=3)

    elif "4" in action:
        await activity(action=4)
    elif "5" in action:
        await activity(action=5)
    elif "6" in action:
        await activity(action=6)

    elif action == "Exit":
        console.print(f"[bold red]Exiting {PROJECT_NAME}...[/bold red]")
        raise SystemExit(0)

    await choose_action()


async def main():
    check_python_version()
    create_files()
    await check_for_updates(repo_name=PROJECT_NAME, repo_private=False)
    db.ensure_model_columns(Wallet)
    await choose_action()


if __name__ == "__main__":
    show_channel_info(PROJECT_NAME)

    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
