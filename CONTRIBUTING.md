# Contributing to BetterVoice

Thanks for helping improve BetterVoice. Start with the [development guide](docs/development/README.md) and the [architecture overview](docs/architecture/overview.md).

## Before you start

Search the [issues](https://github.com/kerim0x1/bettervoice/issues) for existing reports. For a new engine, a larger feature, or an architectural change, describe the problem and your proposed approach in an issue first. Small, focused fixes can go straight to a pull request.

## Local workflow

1. Fork the repository and create a branch for one change.
2. Follow [INSTALL.md](INSTALL.md) to set up a virtual environment and run the app.
3. Keep changes focused and preserve existing behavior outside the task.
4. Add or update tests when behavior changes. Use the existing suite for the affected area.
5. Run `ruff check .` and `python -m pytest` before opening a pull request. If you touched an engine, also run its integration test with a real key.

Do not commit virtual environments, build output, downloaded models, `.env` files, logs, or real API keys.

## Project conventions

- Keep engine-specific behavior in its module under `src/bettervoice/stt/`, behind the session interface described in `stt/__init__.py`.
- Raise `SttError` with a short, user-facing message for anything the user should see; put technical detail in the second argument, which goes to the log.
- Never log or send what the user dictated, beyond the chosen engine.
- Touch tkinter only from the main thread. Background work reports back through the existing queues.
- Keep system-specific code in `src/bettervoice/desktop/` (`windows.py`, `macos.py`, `linux.py`, behind the interface in `desktop/__init__.py`). Test it on the systems you change; CI runs the tests on all three.
- Take names, colors, and the mark from `bettervoice.brand`; regenerate the icons with `scripts/generate_brand_assets.py` instead of editing them.
- After changing `packaging/` or `scripts/build.py`, build on the systems you touched: on Windows `python scripts/build.py --installer` (needs Inno Setup), then install and uninstall once; on macOS and Linux `python scripts/build.py`, then start the result with `--check`.
- Update the user-facing guides when setup, behavior, or data handling changes, and add an entry to [CHANGELOG.md](CHANGELOG.md).

## Pull requests

CI lints and tests every pull request on Python 3.10 and 3.13 and builds the app with its installer; the build is attached to the run as an artifact. Explain the problem, the resulting behavior, and how you checked it. Include screenshots for visible UI changes and note anything you could not test, such as an engine you have no key for. Avoid unrelated formatting changes or dependency upgrades.

Keep discussion respectful and focused on the work. For suspected vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
