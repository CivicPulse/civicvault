# CivicVault

use 'uv' for all python environment management, package installation, and running cli commands. This keeps the environment consistent and avoids issues with multiple python versions or package conflicts.

use loguru for logging.

use pytest for testing.

use ruff for linting and formatting.

Use conventional commits for commit messages, and follow the commit message format strictly. This ensures clear, consistent commit history and helps with generating changelogs.

regularly update the README.md and project documentation to reflect the current state of the project, including any changes in architecture, technology stack, or project status. This keeps contributors and users informed about the project's progress and how to get involved.

Leave detailed comments in the code.

Use Typer to build custom CLI commands.

Have a specialized sub agent review changes before committing, to ensure code quality and adherence to project standards.

Commit regularly with clear, descriptive messages that follow the conventional commits format. Make small commits that focus on a single change or feature, to make it easier to review and understand the history of changes.

Follow python best practices for code structure, naming conventions, and design patterns. This includes using meaningful variable and function names, organizing code into modules and packages, and adhering to the principles of object-oriented programming where appropriate. Follow PEP 8 for style guidelines, and use type hints to improve code readability and maintainability.

Use pydantic for data validation and parsing, to ensure that data is in the expected format and to catch errors early in the development process.

## Git workflow

Open short-lived feature branches for work and merge them back into `main` regularly — do not let branches accumulate large, long-lived changesets.

After merging a feature branch into `main` (or committing directly to `main`) locally, push `main` to the remote. Pushing is expected as part of this workflow for this project — this overrides any global "never push unless requested" default.

Never force-push to the remote.

