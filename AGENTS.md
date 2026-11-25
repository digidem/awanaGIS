# Repository Guidelines

## Project Structure

- `__init__.py` is the QGIS plugin entry point. `plugin.py` manages the plugin lifecycle, and
  `config.py` handles settings.
- `core/` contains GIS tools, main-thread execution, and session state. `backends/` integrates model
  APIs and local agent CLIs. `gui/` contains the chat dock and widgets, and `server/` contains the
  localhost MCP bridge and stdio adapter.
- `resources/` holds plugin icons. `i18n/` holds Qt translation sources and compiled catalogs.
  `tests/` covers localization, permissions, and UI presentation.

## Local Development and Checks

- Clone the checkout as `awanagis` under the QGIS profile's `python/plugins/` directory. Restart
  QGIS, enable the plugin in the Plugins menu, and open it from the toolbar. See the README for
  platform-specific profile paths.
- Run the headless suite from the repository root with QGIS's Python.

  ```sh
  QT_QPA_PLATFORM=offscreen PYTHONPATH=.. /usr/bin/python3 -m unittest discover -s tests
  ```
- Run `flake8` from the repository root to check Python style using `.flake8`.

## Python and Qt Conventions

Use four-space indentation, `snake_case` for Python functions and variables, and `PascalCase` for
classes. Follow the 120-character Flake8 limit. Import Qt through `qgis.PyQt` and use
`core/qt_compat.py` for Qt version differences. Keep coverage for QGIS 3 and QGIS 4 behavior when
changing Qt code.

Wrap user-visible strings with `QCoreApplication.translate`, using named placeholders where needed.
Register new translatable modules in `i18n/awanagis.pro` and commit both the updated `.ts` and
compiled `.qm` catalogs.

## Testing

Put regression tests in `tests/test_*.py` with `unittest.TestCase` and `test_*` methods. Follow the
existing offscreen QGIS setup for GUI tests. Mock external calls so tests can run without model
credentials.

## Commits and Pull Requests

Use short, imperative subjects such as `fix(i18n): harden permission prompts` or `feat: add chart
options`. Describe the user-facing change and checks run in the PR, link related issues when
available, and include screenshots for visible UI changes. Keep API keys out of commits and
screenshots.
