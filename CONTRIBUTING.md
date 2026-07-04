# Contributing to Resonate AI Studio 🎙️

First off, thank you for considering contributing to Resonate AI Studio! It's people like you who make this local media automation tool better for everyone.

Below is a set of guidelines to help you contribute smoothly.

---

## 🛠️ How Can I Contribute?

### 1. Reporting Bugs
* Check the existing issues to ensure the bug hasn't already been reported.
* Open a new issue using our **Bug Report** template.
* Include detailed steps to reproduce, your system environment (OS, CPU/GPU, Python version), and log files from the terminal or `/outputs/`.

### 2. Suggesting Enhancements
* Check if there is already a similar feature request in the issues list.
* Open an issue using the **Feature Request** template.
* Explain the use case, why this feature would be valuable, and how it fits the "local-first, zero-cloud-fee" philosophy of the project.

### 3. Pull Requests (PRs)
* Fork the repository and create your feature branch from `main`:
  `git checkout -b feature/amazing-feature`
* Make your changes, keeping the code clean and well-documented.
* Run compilation checks on python files before staging:
  `python3 -m py_compile server.py core/*.py`
* Commit your changes using [Conventional Commits](https://www.conventionalcommits.org/):
  * `feat: ...` for new features
  * `fix: ...` for bug fixes
  * `docs: ...` for documentation
  * `refactor: ...` for structural rewrites
* Push to your fork and submit a PR to our repository. Ensure you fill out the Pull Request template completely.

---

## 💻 Coding Standards

* **Python**: Follow PEP8. Keep all logic processes isolated from the main FastAPI thread using asynchronous subprocess spawns where appropriate.
* **Frontend**: Keep the frontend lightweight. Use vanilla HTML, CSS grids/variables, and client-side JavaScript. Avoid adding massive node module bundlers or frame libraries unless absolutely required.
* **Dependencies**: Minimize external packages to keep installation fast and portable across Mac/Windows/Linux systems.
