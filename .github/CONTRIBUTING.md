# Contributing Guidelines

Welcome, and thank you for your interest in contributing to Low Voltage Grid Play (gridarena)! Your contributions are valuable for improving the project.

These guidelines outline the contribution process. Whether you're fixing a bug, adding a feature, or suggesting improvements, please review the steps below. If you have questions, contact the maintainer listed in [README.md](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/README.md#11-contacts).

By participating in this project, you agree to abide by our [Code of Conduct](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/.github/CODE_OF_CONDUCT.md).

## Step-by-step

1. **Fork the repository**

   Fork the repository to your own account.

2. **Clone your fork**

   ```bash
   git clone <your-fork-url>
   cd gridarena
   ```

3. **Set up the development environment**

   ```bash
   # Create and activate a virtual environment
   python -m venv .venv

   # Linux / macOS
   source .venv/bin/activate

   # Windows
   .venv\Scripts\activate

   # Install dependencies
   pip install -r requirements.txt
   ```

   You'll also need a running PostgreSQL server and a configured database
   connection -- see [README.md](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/README.md#4-installation) for details.

4. **Create a branch**

   Branch from `main`, and name your branch based on the type of change:
   - `feature/<short-description>` for new functionality
   - `fix/<short-description>` or `bug/<short-description>` for bug fixes

   ```bash
   git checkout -b feature/<short-description>
   ```

5. **Make your changes**

   Make the necessary changes using your preferred editor or IDE.

6. **Run tests**

   ```bash
   pytest
   ```

   Make sure existing tests still pass, and add new tests for any new
   behavior where practical.

7. **Commit your changes**

   ```bash
   git add .
   git commit -m "Your descriptive commit message"
   ```

8. **Push your changes**

   ```bash
   git push origin feature/<short-description>
   ```

9. **Open a Pull Request**

   Open a PR against `main`, describing what changed and why.

10. **Review and address feedback**

    A maintainer will review your PR. Please address any requested changes
    with additional commits on the same branch.

11. **Merge**

    Once approved, a maintainer will merge your PR.

## Reporting bugs and security issues

- For regular bugs, open an issue describing the problem, expected
  behavior, and steps to reproduce.
- For security vulnerabilities, do **not** open a public issue -- follow
  the process in [SECURITY.md](https://gitlab.inesctec.pt/cpes/european-projects/aieffect/gridarena/-/blob/main/.github/SECURITY.md) instead.
