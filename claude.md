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

use agent teams where appropriate to minimize context window usage and maximize parallelism (for speed).

## Design context

Frontend/UI work has two root context files; read them before designing or building any screen:

- `PRODUCT.md` — strategic. Register is **product** (design serves the task). Users are anonymous public (residents, journalists, researchers). Guiding principle: **provenance** — every fact links to its source. Accessibility bar: **WCAG 2.2 AA** with dark-surface contrast care.
- `DESIGN.md` — visual system (currently a `<!-- SEED -->`; re-run `/impeccable document` once there's real CSS to capture tokens). North Star: **"The Open Dossier"** — an intelligence-database feel for the *public* record. Cold **Signal Cyan on near-black** (committed dark surface, one accent), **grotesk for prose + mono for data** (IDs, timestamps, dollar amounts, vote tallies, citations), responsive-but-restrained motion. The relationship graph is the signature component. NOT SaaS-startup, NOT literal redaction theater (no CLASSIFIED stamps/redaction bars), NOT dreary gov-portal, NOT Hollywood-HUD cosplay.