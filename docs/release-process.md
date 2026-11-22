# Release process

OneAdmin is pre-alpha and has not been published to PyPI. This is the release checklist for a future `0.x` version; publishing requires the project's PyPI account and trusted-publisher configuration.

## Before tagging

1. Decide which changes are public or breaking. Update the guides, `CHANGELOG.md`, supported versions, and migration notes. During `0.x`, document breaking changes explicitly. For a stable release, provide a deprecation path.
2. Run the full CI matrix on the candidate commit. Include strict documentation build, frontend tests and bundle budget, PostgreSQL integration/security tests, and an installed-wheel smoke test.
3. Build both sdist and wheel from a clean checkout. Check the wheel's bundled UI, migrations, `py.typed`, metadata, and README rendering. Install the wheel in a clean virtual environment and run the documented quickstart against a sample app.
4. Test upgrade from the previous release, including OneAdmin's Alembic migrations and an existing admin account. Verify that a previously installed application can import and mount the new package.
5. Review dependencies and open security reports. Verify that the comparison and performance claims still name their exact versions, workload, and measurement method.

## Publish

Use a protected tag and GitHub Actions trusted publishing to PyPI. Build each artifact once, inspect it, and publish those same artifacts. Do not use a local token or rebuild after validation. Record the tag, artifact hashes, and release notes. The publish workflow is not yet configured; do not tag a release assuming it will publish automatically.

After publication, install the published distribution in a clean environment, run `oneadmin --version`, and follow the published quickstart. If that fails, publish a corrective release and document the failure.

The [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/tool-recommendations/) recommends trusted publishing for supported CI platforms. `SECURITY.md` defines the private vulnerability reporting channel.
