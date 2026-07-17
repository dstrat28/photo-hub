# Contributing to Photo Hub

Thanks for helping improve Photo Hub. Bug reports, compatibility findings,
documentation improvements, and focused code changes are welcome.

## Before opening an issue

- Search existing issues for the same behavior.
- Do not include Gmail App Passwords, TV pairing tokens, email addresses,
  private photos, or unredacted network traces.
- For a security vulnerability, follow `SECURITY.md` instead of opening a
  public issue.

Samsung TV behavior varies by model and firmware. Compatibility reports should
include the model family, firmware version, command used, and redacted output.
Private IP addresses can be replaced with an address such as `192.168.1.50`.

## Local development

Install uv, then create the locked test environment:

```bash
uv sync --locked --extra test
uv run --frozen pytest
```

The test suite must pass before a pull request is opened. Add regression tests
for behavior changes and keep changes scoped to one concern where practical.

## Pull requests

In the pull request description:

- explain the user-visible change and motivation;
- describe how the change was tested;
- call out any device or firmware assumptions; and
- confirm that logs, fixtures, screenshots, and configuration contain no
  credentials or personal data.

By contributing, you agree that your contribution is licensed under the MIT
License included with this repository.
