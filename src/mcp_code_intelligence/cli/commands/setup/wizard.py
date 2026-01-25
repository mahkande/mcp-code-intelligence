import typer
from rich.console import Console
from rich.panel import Panel

class SetupWizard:
    """Handles the user interface and interactive summary."""

    def __init__(self, console: Console):
        self.console = console

    def show_header(self):
        """Prints the setup header."""
        self.console.print(
            Panel.fit(
                "[bold cyan]🚀 Smart Setup for mcp-code-intelligence[/bold cyan]\n"
                "[dim]Zero-config installation with auto-detection[/dim]",
                border_style="cyan",
            )
        )

    def show_discovery_summary(self, project_name: str, languages: list, tools: list, planned_actions: list):
        """Displays a summary of detected items and planned actions."""
        summary_panel = [
            f"[bold]Project:[/bold] {project_name}",
            f"[bold]Detected Languages:[/bold] {', '.join(languages) if languages else 'Generic'}",
            f"[bold]Detected AI Tools:[/bold] {', '.join(tools) if tools else 'None'}",
            "",
            "[bold cyan]Planned Actions:[/bold cyan]"
        ]
        
        for action in planned_actions:
            summary_panel.append(f"• {action}")
            
        self.console.print(Panel("\n".join(summary_panel), title="🚀 Setup Summary", border_style="green"))

    def confirm_execution(self) -> bool:
        """Asks for user confirmation before proceeding."""
        return typer.confirm("\nDo you want to proceed with these actions?")
        
    def show_completion(self, next_steps: list):
        """Displays completion message and next steps."""
        self.console.print("\n[bold green]🎉 Setup Complete![/bold green]")
        self.console.print("\n[bold]Ready to Use:[/bold]")
        for step in next_steps:
            self.console.print(f"  • {step}")
