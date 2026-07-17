# Security Policy

## Supported versions

Photo Hub is currently pre-1.0. Security fixes are made on the latest revision
of the default branch; older revisions are not maintained separately.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

After this repository is published, use GitHub's **Report a vulnerability**
option in the repository's Security tab. If private vulnerability reporting is
not available, contact the repository maintainer privately using the contact
method listed on their GitHub profile.

Include a concise description, affected component, reproduction steps, and
impact. Remove Gmail App Passwords, Samsung pairing tokens, email addresses,
private photos, and identifying network details from all reports.

You should receive an acknowledgement within seven days. Please allow time for
a fix and coordinated disclosure before publishing details.

## Deployment security

- Use a dedicated Gmail account and an App Password.
- Store `config.json` outside the checkout with mode `0600`.
- Keep the state directory private; it can contain sender addresses, images,
  device content IDs, and operational errors.
- Run Photo Hub as an unprivileged user on a trusted local network.
- Review configuration files, logs, database files, and probe output before
  attaching them to an issue.
