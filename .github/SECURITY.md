# Security Policy

## Reporting security issues

> [!IMPORTANT]
> **Please do not publish security vulnerabilities in public issues.**

Any vulnerability found should be reported directly to the maintainer listed
in [README.md](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/README.md#11-contacts) (David Lima, david.lima@inesctec.pt).
If you are still waiting for a response within 48 hours, please send a
follow-up email to confirm the initial message was received.

Please write reports in English.

## Security best practices

We encourage all contributors to follow security best practices when
contributing code:

- **Validate input**: Always sanitize and validate user input to prevent
  injection attacks (SQL injection, XSS, etc.). In particular, never
  interpolate request-derived values directly into SQL strings -- use
  parameterized queries (`cursor.execute(query, params)`), as is done
  throughout `gridarena/database/` and `gridarena/routers/`.
- **Use secure protocols**: Prefer HTTPS over HTTP for all external
  communication.
- **Minimize permissions**: Follow the principle of least privilege when
  assigning database and system permissions.
- **Never hardcode secrets**: Database credentials and other secrets must
  come from environment variables (see `GRID_DB_DSN` / `DATABASE_URL` in
  `gridarena/database/database_connection.py`), never committed to the repo.
- **Regularly update dependencies**: Keep `requirements.txt` dependencies
  up to date and free from known vulnerabilities.

## Security vulnerability lifecycle

- **Acknowledgment**: We will acknowledge receipt of your report within 48
  hours.
- **Assessment**: We will assess the severity and potential impact of the
  vulnerability.
- **Fix and mitigation**: We will implement a fix or mitigation strategy and
  document it in [CHANGELOG.md](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/CHANGELOG.md).
- **Disclosure**: After the fix is deployed, we will provide a public
  disclosure with details of the vulnerability, its severity, and the fix.

## Security fixes and changelog updates

> [!IMPORTANT]
> **Once a security issue is resolved or mitigated, the fix must be recorded
> in [CHANGELOG.md](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/CHANGELOG.md).**

Each entry should include:

- **Severity level** (e.g., moderate, high, critical).
- **Publication timeline**: an estimated release date for the security fix,
  typically 30 to 60 days after the code is made public.

This ensures transparency and informs users about the actions taken to
mitigate security risks.

---

## Report format

If you have encountered a security issue or vulnerability, please include
the following information in your report to help us address it efficiently:

| Field | Description |
|---|---|
| **Title** | A concise, clear summary of the issue. |
| **Description** | The issue in detail, including expected vs. actual behavior. |
| **Environment** | OS, software versions, browser, and other relevant system information. |
| **Screenshots/Logs** | Any screenshots, logs, or files that help illustrate the issue. |
| **Impact** | Severity and potential consequences, and how it affects users or systems. |
| **Mitigation** | Any known workarounds or steps that limit exposure. |
| **Steps to Reproduce** | A clear, complete list of reproduction steps, if applicable. |
| **Additional Information** | Anything else relevant, such as recent related changes. |

Thank you for helping us improve the security of the project.
