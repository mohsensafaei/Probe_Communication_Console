# Contributing to Probe

Thanks for helping improve Probe. Small bug fixes, documentation, reproducible
captures and tests on real hardware are all useful contributions.

## Before changing code

Search existing issues. For a significant feature or dependency, open an issue to
agree on the scope first. Keep user workflows simple and avoid speculative frameworks.
Follow the [code of conduct](CODE_OF_CONDUCT.md).

## Development workflow

1. Fork the repository and create a topic branch from `main`.
2. Follow [development setup](docs/development.md).
3. Make one focused change. Put protocol logic in its feature package and UI in `ui`.
4. Run the relevant tests and the [required checks](docs/testing.md).
5. Open a pull request against `main` using the supplied template.

Explain the problem, the resulting behavior and how you verified it. Include a
screenshot for visible UI changes and a small example for protocol changes. State
when a platform or real device was not available. Do not claim hardware coverage
from mocked COM ports alone.

## Code and documentation

Use ordinary Python functions and small modules. Reuse existing framing, capture,
comparison and plugin paths instead of adding parallel implementations. Keep
comments short and reserve them for behavior that code cannot make clear. Add tests
for meaningful regressions; avoid tests that merely repeat the implementation.

Write user-facing labels and documentation in English. Update the relevant guide
and the unreleased changelog entry when behavior changes. Do not commit settings,
credentials, captures from real users, build output or benchmark result dumps.
Keep third-party license and source notices when moving bundled components.

## Review and licensing

Maintainers review contributions before merging. Submitted contributions must be
compatible with the repository's MIT license. Identify copied third-party code and
its license explicitly. Releases and publishing are maintainer operations.
