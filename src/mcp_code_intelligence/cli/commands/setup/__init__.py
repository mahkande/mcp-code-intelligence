
import typer

def get_setup_app():
    # Typer objesini ve main_setup_task fonksiyonunu sadece ihtiyaç olduğunda import et
    from .main import main_setup_task
    setup_app = typer.Typer()

    @setup_app.callback(invoke_without_command=True)
    def main(
        ctx: typer.Context,
        force: bool = typer.Option(False, "--force", "-f", help="Force re-indexing"),
        verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging")
    ):
        """Setup command entry point."""
        import asyncio
        asyncio.run(main_setup_task(ctx, force, verbose))

    return setup_app

# Dışarıdan import edildiğinde setup_app olarak kullanılabilsin
setup_app = get_setup_app()
