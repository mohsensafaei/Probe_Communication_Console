# Development setup

Use Python 3.10+ with Tkinter and Git. Clone `main`, create a virtual environment,
activate it and install the project in editable mode:

```sh
git clone --branch main https://github.com/mohsensafaei/Probe_Communication_Console.git
cd Probe_Communication_Console
python -m venv .venv
```

Windows Command Prompt: `.venv\Scripts\activate`. Linux:
`source .venv/bin/activate`. Debian/Ubuntu users need `python3-tk` and `python3-venv`.
Then:

```sh
python -m pip install -e ".[dev]"
python -m probe
python -m probe --demo
```

`--demo` uses synthetic bytes and never opens a hardware/network connection.
The `src` layout deliberately requires installation (or an explicit `PYTHONPATH=src`)
so tests cannot accidentally depend on importing the checkout's root directory.
Run commands from the repository root. No custom bootstrap script is needed.

## Find the code

Read [architecture](architecture.md) for package ownership and runtime boundaries.
Start at `src/probe/cli.py`, then `app.py` for workspace lifecycle or the relevant
feature package. `ui` owns widgets; core packages must import without Tk.
`tests` mirrors feature behavior. `examples` contains portable sample inputs.
`packaging` owns the PyInstaller entry point/spec; `scripts` owns development tasks.

Public extension points are [plugin API 1](plugins.md) and the documented
[file formats](formats.md). Internal module paths are not a stable library API.

## Local checks

```sh
python -m ruff check src tests scripts packaging
python scripts/check_docs.py
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p "ui_*.py" -v
python -m probe --self-test
```

GUI tests need a display. On headless Linux use `xvfb-run -a` before the Python
command. See [testing](testing.md) for hardware opt-ins and benchmarks.

Keep changes small. Separate byte interpretation from UI, avoid global connection
state and do not add a new worker/thread for a task already served by an existing
bounded path. Update the relevant guide and regression test when behavior changes.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for pull requests and licensing.
