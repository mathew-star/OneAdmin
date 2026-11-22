# ADR-0021: Rich Click for the management CLI

## Context

The command entry point used an `argparse` tree alongside separate handler functions. Its help was functional but hard to scan as the command count grew. The library needs discoverable top-level and per-command help without changing how commands load the user's site or execute work.

## Options

- Keep `argparse` and customize its formatter. This leaves command discovery and rich terminal presentation as bespoke code.
- Use Click alone. It provides a declarative command tree and generated help, but plain terminal output.
- Use Rich Click. It wraps Click's command model and formats the same definitions as terminal help.

## Decision

Use Rich Click for the CLI command tree and help. Keep the existing command handlers and `Console` injection; callbacks adapt parsed Click values to their current handler arguments. `oneadmin --help` lists every command, and `oneadmin COMMAND --help` shows its options without importing the user's site.

`createuser --grant` is a repeatable option: write `--grant orders.view --grant orders.change` for two grants. This is a pre-alpha CLI syntax change.

## Consequences

The runtime distribution gains Rich Click. CLI integration tests still exercise the existing handler behavior, and focused tests protect help discovery. When Click's output or API changes, review the help and exit-code tests before updating the dependency range.

## Revisit when

Revisit if Rich Click's dependency or terminal behavior becomes a material compatibility problem for consumers.
