"""Command-line interface for the local dashboard and synthetic demo data.

Keep argument definitions separate from command execution so help is available
without importing the web server or mass spectrometry readers.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

DEFAULT_PORT = 8765


def build_parser() -> argparse.ArgumentParser:
    """Describe the commands, their inputs, and how to start a local session."""
    parser = argparse.ArgumentParser(
        prog="mzloupe",
        description=(
            "Inspect mzML signal and idXML peptide identifications in a local browser\n"
            "dashboard. Data stays on the machine running mzLoupe."
        ),
        epilog=(
            "Examples:\n"
            "  mzloupe serve\n"
            "  mzloupe serve --project ./project.json\n"
            "  mzloupe serve --project ./project.json --port 8766\n"
            "  mzloupe demo ./demo-data\n"
            "  mzloupe serve --project ./demo-data/project.json\n\n"
            "Use 'mzloupe COMMAND --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(
        title="commands",
        dest="command",
        required=True,
    )

    serve_parser = commands.add_parser(
        "serve",
        help="Start the local inspection dashboard.",
        description=(
            "Start the dashboard at http://127.0.0.1:8765 by default. "
            "Open that address in your browser. The server accepts connections "
            "only from this machine; press Ctrl+C to stop it."
        ),
    )
    serve_parser.add_argument(
        "--project",
        type=Path,
        metavar="FILE",
        help=(
            "Project JSON file to open at startup. Paths inside it are relative "
            "to the JSON file. Omit this option to select mzML and idXML files "
            "in the dashboard's Project setup view."
        ),
    )
    serve_parser.add_argument(
        "--cache",
        type=Path,
        metavar="DIRECTORY",
        help=(
            "Directory for scan indexes, acquisition maps, and prepared mzML "
            "working copies. Reuses matching prepared projects between sessions "
            "(default: ~/.cache/mzloupe)."
        ),
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        metavar="PORT",
        help=(
            "Local HTTP port. Choose another port to run a separate dashboard "
            f"session (default: {DEFAULT_PORT})."
        ),
    )

    demo_parser = commands.add_parser(
        "demo",
        help="Generate a synthetic two-fraction project.",
        description=(
            "Write two synthetic mzML fractions, sample-level Search and "
            "Validated idXML layers, and a project.json manifest. Prints the "
            "manifest path when finished."
        ),
        epilog="Then open the result with: mzloupe serve --project DIRECTORY/project.json",
    )
    demo_parser.add_argument(
        "directory",
        type=Path,
        metavar="DIRECTORY",
        help=(
            "Destination for the generated files. Creates the directory if "
            "needed and replaces demo files with the same names."
        ),
    )
    return parser


def serve_dashboard(*, project_path: Path | None, cache_directory: Path | None, port: int) -> None:
    """Run the loopback-only server until interrupted with Ctrl+C."""
    import uvicorn

    from mzloupe.app import create_app

    app = create_app(cache=cache_directory, project_path=project_path)
    uvicorn.run(app, host="127.0.0.1", port=port)


def write_demo(directory: Path) -> None:
    """Generate the synthetic project and print its absolute manifest path."""
    from mzloupe.demo import DemoProject

    project_path = DemoProject().write(directory.resolve())
    print(project_path)


def main(argv: Sequence[str] | None = None) -> None:
    """Parse explicit arguments, or the process arguments when argv is None."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "serve":
        serve_dashboard(
            project_path=arguments.project,
            cache_directory=arguments.cache,
            port=arguments.port,
        )
    elif arguments.command == "demo":
        write_demo(arguments.directory)


if __name__ == "__main__":
    main()
