"""The published CLI help must expose every command and its options."""

from __future__ import annotations

from click.testing import CliRunner

from oneadmin.cli import cli


def test_top_level_help_lists_all_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"], color=False)
    assert result.exit_code == 0
    for command in (
        "migrate",
        "createsuperuser",
        "createuser",
        "changepassword",
        "grant",
        "revoke",
        "perms",
        "check",
        "init",
        "demo",
        "convert",
        "explain",
        "schema",
    ):
        assert command in result.output


def test_command_help_includes_options_without_loading_site() -> None:
    result = CliRunner().invoke(cli, ["createuser", "--help"], color=False)
    assert result.exit_code == 0
    assert "--grant" in result.output
    assert "--password-stdin" in result.output
