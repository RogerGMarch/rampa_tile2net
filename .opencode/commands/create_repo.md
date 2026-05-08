Development Best Practices
This file describes the conventions and tooling used in this project.
Follow these practices when writing, reviewing, or extending any code.
***Project Structure
All projects follow the Cookiecutter Data Science template:
├── data/
│   ├── raw/            # Original, immutable source data — never modify
│   ├── interim/        # Intermediate transformed data
│   ├── processed/      # Final datasets ready for analysis
│   └── external/       # Third-party data sources
├── src/<project_name>/ # Source code as an installable Python package
├── notebooks/          # Exploratory use only — never as pipeline steps
├── reports/
│   └── figures/        # Generated outputs for publication or documentation
├── models/             # Trained model artefacts
│   └── <model_name>/
│       ├── config.yaml # Model parameters — single source of truth
│       └── <artefacts> # Weights, checkpoints, etc.
├── docs/               # Project and API documentation
├── tests/              # Automated test suite
├── pyproject.toml      # Project metadata and dependency declaration
├── justfile            # Task runner — see Commands section below
├── README.md           # Entry point for any new collaborator
├── AGENT.md            # Conventions for this repository (this file)
├── .gitignore          # Ignore .venv, caches, local artefacts — see Data and Git
├── uv.lock             # Lockfile — always commit
└── Dockerfile          # Optional — full runtime for external collaborators
Also include LICENSE and CONTRIBUTING.md when the project is public or multi-contributor; add .github/workflows/ (or GitLab CI) if you use continuous integration.
***Repo bootstrap
Use this checklist when creating a new repository so scaffolding matches the rest of this document.
Create the directory tree above; use .gitkeep in empty data/* folders so Git tracks them.
Choose <project_name>: a valid Python import name, usually the Git repo name with hyphens replaced by underscores (e.g. diba-trajectories → diba_trajectories).
Add src/<project_name>/: at minimum __init__.py, a pipeline module (or equivalent) as the target of just run, and a small smoke test under tests/ that imports that code.
Add pyproject.toml: declare requires-python to match the Python version in Dockerfile (e.g. python:3.11-slim → requires-python = ">=3.11").
Use Hatchling as [build-system] with a src layout: the installable package is only under src/<project_name>/ (configure Hatchling so the wheel includes that package).
Declare dev-only tools (e.g. pytest, ruff) under [project.optional-dependencies] with a dev extra. Install them with uv sync --extra dev or uv sync --all-extras; just install should use the same flags so CI and laptops match.
Run uv lock (or uv sync) and commit uv.lock.
Add an example models/<model_name>/config.yaml (and folder) even before training artefacts exist.
Initialise Git on main and keep AGENT.md in the repo so agents and humans share one source of truth.
***Dependency Management
Use uv for all Python dependency management.
All dependencies must be declared in pyproject.toml.
Always commit the uv.lock lockfile so environments are fully reproducible.
Never install packages ad-hoc without updating pyproject.toml.
# Install the project and all dependencies
uv sync
# Add a new dependency
uv add <package>
# Add a dev-only dependency
uv add --dev <package>
After adding dev dependencies, sync with uv sync --extra dev or uv sync --all-extras so linters and test runners are available (see Repo bootstrap).
***Task Runner
This project uses just as the task runner.
All common operations are defined as named recipes in the justfile.
just          # List all available recipes
just install  # Install dependencies
just test     # Run the test suite
just run      # Execute the full pipeline
just lint     # Run linter / formatter
When adding new operations, add them to the justfile with a comment explaining what they do.
Default mapping to uv (adjust names to match your package):
Recipe	Typical command
just install	uv sync --all-extras (or --extra dev if you only use a dev extra)
just test	uv run pytest
just run	uv run python -m <project_name>.pipeline (or your pipeline entry module)
just lint	uv run ruff check / ruff format --check (or your chosen tools)
***Code Style
No notebooks in the pipeline. Notebooks (*.ipynb) are for exploration only.
  Finalized logic must be moved into src/ as proper Python modules.
Write modular code: small, single-responsibility functions and classes.
Follow a clear layered structure: ingestion → processing → analysis → output.
No hardcoded paths. Use paths relative to the project root, driven by config.
Document all public functions and classes with docstrings (NumPy or Google style).
***Version Control
All projects are tracked with Git from day one.
Use GitHub or GitLab depending on institutional requirements.
Follow a branch-based workflow:
main — stable, reproducible state only
feature/<name> — new work
fix/<name> — bug fixes
Open a pull request for all changes; do not commit directly to main.
Write meaningful commit messages that explain why, not just what.
Maintain a .gitignore that excludes .venv/, __pycache__/, build outputs (dist/, *.egg-info) and local IDE/OS noise so those are never committed.
Data and Git
data/raw/ and other large or binary datasets usually must not be committed to Git. Keep canonical data on institutional storage, object storage, or a data registry; document how to obtain or mount it in README.md. If versioned data in-repo is required, use DVC, Git LFS, or an equivalent workflow—never bloat the history with multi-gigabyte files unless that is an explicit, team-wide choice. Do not commit secrets, credentials, or personally identifiable data.
***Reproducibility
Every analysis must be reproducible end-to-end from raw data with a single just command.
Results must be deterministic: set and document all random seeds.
Never mutate files in data/raw/ — treat them as read-only.
When sharing code with external collaborators, provide a Dockerfile that
  encapsulates the full runtime environment.
The python:3.11-slim image does not include just. Either install just in the image (see the just installation docs) and keep ENTRYPOINT ["just", "run"], or avoid just in the container and call the same command your just run recipe uses—for example:
# Minimal example — mirrors `just run` without installing `just`
FROM python:3.11-slim
RUN pip install --no-cache-dir uv
COPY . /app
WORKDIR /app
RUN uv sync --frozen --all-extras
ENTRYPOINT ["uv", "run", "python", "-m", "<project_name>.pipeline"]
Replace <project_name>.pipeline with your real pipeline module. Use uv sync --frozen in Docker so the image respects the committed uv.lock.
***Model Configuration
All model parameters must be defined in a config.yaml file inside the model's folder under models/, never hardcoded in the source code.
Each model or experiment variant lives in its own subfolder with its config alongside its artefacts.
models/
└── random_forest_v1/
    ├── config.yaml
    └── model.pkl
# models/random_forest_v1/config.yaml
model:
  name: random_forest
  n_estimators: 200
  max_depth: 10
  random_state: 42
training:
  test_size: 0.2
  cv_folds: 5
features:
  scaling: standard
  selection: variance_threshold
Load configs explicitly at runtime — do not merge or override values silently.
When logging experiments, always log or store the full config file alongside the results.
***Testing
All core logic in src/ must have corresponding tests in tests/.
Run tests before opening a pull request: just test.
Tests should cover edge cases and, where applicable, validate output shapes and types.
***Documentation
Keep README.md up to date. It must always explain how to:
Install the environment
Run the full pipeline
Understand the project structure
For projects that expose APIs or reusable interfaces, generate HTML docs from docstrings.
Continuous integration (optional)
For GitHub or GitLab, add a minimal workflow that runs just test and just lint on every pull request so the default recipes stay green.