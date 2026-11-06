# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| `main`  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability or credential leak within this repository:

1. **Do not create a public GitHub issue.**
2. Report the vulnerability privately via GitHub Security Advisories or contact the repository maintainer directly.
3. Provide a detailed summary, including steps to reproduce, affected files, and potential impact.

## Credential Safety Guidelines

This repository interacts with web authentication and API endpoints. Follow these hygiene practices:
- Store API keys in environment variables or `.env` files (never commit them).
- Check that `.env`, `.config/`, and token files are ignored by git before running.
- In Docker environments, mount secrets as read-only volumes or pass via environment variables.
