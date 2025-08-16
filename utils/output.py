import sys
from rich.console import Console
from rich.table import Table
from rich import box

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