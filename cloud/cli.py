"""Advanced CLI interface with rich formatting and interactive commands."""

import click
import sys
from typing import Optional
from datetime import datetime

# Try to import rich, fall back to plain text if not available
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    class Console:
        def __init__(self, *args, **kwargs):
            pass
        def print(self, *args, **kwargs):
            print(' '.join(str(a) for a in args))
        def rule(self, *args, **kwargs):
            print("=" * 60)
    
    class Table:
        def __init__(self, *args, **kwargs):
            pass
        def add_column(self, *args, **kwargs):
            pass
        def add_row(self, *args, **kwargs):
            pass
    
    class Panel:
        def __init__(self, *args, **kwargs):
            pass


console = Console()


class AutoReelsCLI:
    """Advanced CLI for AutoReels Pro."""

    @staticmethod
    def print_banner():
        """Print colorful banner."""
        if HAS_RICH:
            console.print(Panel(
                "[bold cyan]AUTO-REELS PRO v10[/bold cyan]\n[dim]Production Video Pipeline[/dim]",
                style="bold green"
            ))
        else:
            print("AUTO-REELS PRO v10 - Production Video Pipeline")

    @staticmethod
    def print_status(status: str, items: dict):
        """Print status table."""
        if not HAS_RICH:
            for key, value in items.items():
                print(f"{key}: {value}")
            return

        table = Table(
            title=status,
            show_header=True,
            header_style="bold magenta"
        )
        table.add_column("Component", style="cyan")
        table.add_column("Status", justify="right")

        for key, value in items.items():
            status_str = "✓" if value else "✗"
            table.add_row(key, status_str)

        console.print(table)

    @staticmethod
    def print_metrics(metrics: dict):
        """Print metrics table."""
        if not HAS_RICH:
            for key, value in metrics.items():
                print(f"{key}: {value}")
            return

        table = Table(
            title="Pipeline Metrics",
            show_header=True,
            header_style="bold cyan"
        )
        table.add_column("Metric")
        table.add_column("Value", justify="right")

        for key, value in metrics.items():
            table.add_row(str(key), str(value))

        console.print(table)


@click.group()
@click.pass_context
def cli(ctx):
    """AutoReels Pro — Advanced Video Pipeline."""
    ctx.ensure_object(dict)
    AutoReelsCLI.print_banner()


@cli.command()
def status():
    """Check system status and health."""
    from src.health.observability import get_health_check
    
    health = get_health_check()
    status_data = health.status()
    
    print(f"\n[{datetime.utcnow().isoformat()}] System Health Check\n")
    
    AutoReelsCLI.print_status(
        "Component Status",
        {check: ("Healthy" if status else "Failed") 
         for check, status in status_data["checks"].items()}
    )
    
    if status_data["errors"]:
        print("\nErrors:")
        for component, error in status_data["errors"].items():
            print(f"  • {component}: {error}")


@cli.command()
@click.option('--mode', default='--once', help='Pipeline mode')
def run(mode):
    """Run the pipeline."""
    print(f"\nStarting pipeline with mode: {mode}")
    from src.api import run_pipeline_internal
    run_pipeline_internal(mode)


@cli.command()
def metrics():
    """Show collected metrics."""
    from src.health.observability import get_metrics
    
    metrics_collector = get_metrics()
    summary = metrics_collector.get_summary()
    
    print(f"\nMetrics Summary\n")
    print(f"Total metrics collected: {summary['total_metrics']}")
    print(f"\nCounters:")
    for name, value in summary['counters'].items():
        print(f"  • {name}: {value}")


@cli.command()
@click.option('--port', default=8000, help='API server port')
def serve(port):
    """Start API server."""
    print(f"\nStarting API server on port {port}...")
    import uvicorn
    from src.api import app
    uvicorn.run(app, host="0.0.0.0", port=port)


@cli.command()
def validate():
    """Validate environment and dependencies."""
    checks = {
        "Python": sys.version_info >= (3, 8),
        "FFmpeg": False,  # Would check in real implementation
        "yt-dlp": False,  # Would check in real implementation
        "Anthropic API": False,  # Would check in real implementation
        "Facebook API": False,  # Would check in real implementation
    }
    
    AutoReelsCLI.print_status("Environment Validation", checks)
    
    if all(checks.values()):
        print("\n✓ All checks passed!")
    else:
        print("\n✗ Some checks failed. Please review.")
        sys.exit(1)


@cli.command()
@click.option('--service', required=True, help='Service name')
def circuit_breaker_status(service):
    """Check circuit breaker status."""
    from src.resilience.advanced_patterns import get_circuit_breaker
    
    breaker = get_circuit_breaker(service)
    print(f"\nCircuit Breaker: {service}")
    print(f"  State: {breaker.state.value}")
    print(f"  Failures: {breaker.failure_count}")
    print(f"  Last failure: {breaker.last_failure_time}")


@cli.command()
@click.option('--threads', default=8, help='Number of worker threads')
def test_parallel(threads):
    """Test parallel execution."""
    from src.core.async_executor import AsyncExecutor
    
    print(f"\nTesting parallel execution with {threads} threads...")
    
    def dummy_task(i):
        import time
        time.sleep(0.1)
        return i * 2
    
    tasks = [(dummy_task, (i,), {}) for i in range(20)]
    
    async def run_tasks():
        executor = AsyncExecutor(max_workers=threads, executor_type="thread")
        try:
            results = await executor.batch_execute(tasks, batch_size=5)
            return results
        finally:
            executor.shutdown()
    
    import asyncio
    results = asyncio.run(run_tasks())
    print(f"✓ Processed {len(results)} tasks in parallel")
    print(f"  Results: {results[:5]}...")


if __name__ == '__main__':
    cli()
