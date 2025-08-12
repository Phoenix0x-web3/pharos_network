import sys
from rich.console import Console
from rich.table import Table
from rich import box
from loguru import logger
from data.settings import Settings

settings = Settings()

# Configure the logger based on the settings
if settings.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
    raise ValueError(f"Invalid log level: {settings.log_level}. Must be one of: DEBUG, INFO, WARNING, ERROR")
logger.remove()  # Remove the default logger
logger.add(sys.stderr, level=settings.log_level)

def show_channel_info(project_name):
    console = Console()
    
    table = Table(
        show_header=False,
        box=box.DOUBLE,
        border_style="orange3",
        pad_edge=False,
        width=85,
        highlight=True,
    )

    table.add_column("Content", style="orange3", justify="center")

    table.add_row("─" * 50)
    table.add_row(f" {project_name} - Phoenix")
    table.add_row("")
    table.add_row("[link]https://t.me/phoenix_w3[/link]")
    table.add_row("")
    table.add_row("─" * 50)
 
    print("   ", end="")
    print()
    console.print(table)
    print()