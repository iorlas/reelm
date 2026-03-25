.PHONY: check lint test coverage-diff fix fmt bootstrap

# ── Full quality gate ──
check: lint test

# ── Lint: check only — safe for AI, CI, pre-commit. Never modifies files. ──
lint:
	@uv run ruff format --check src/ tests/ || (echo "Formatting issues found. Run 'make fix' to auto-fix." && exit 1)
	@uv run ruff check src/ tests/ || (echo "Lint issues found. Fixable ones can be resolved with 'make fix'." && exit 1)
	@uv run ty check src/ || (echo "Type errors found." && exit 1)
	@git ls-files '*.yml' '*.yaml' | xargs uv run yamllint -s
	@hadolint Dockerfile
	@IMAGE_TAG=lint TRANSMISSION_USER=x TRANSMISSION_PASS=x JACKETT_API_KEY=x WEBDAV_URL=x WEBDAV_USER=x WEBDAV_PASS=x \
		TMDB_API_KEY=x AUTH0_DOMAIN=x AUTH0_CLIENT_ID=x AUTH0_CLIENT_SECRET=x AUTH0_AUDIENCE=x \
		docker compose -f docker-compose.prod.yml config --quiet
	@docker compose -f docker-compose.yml config --quiet
	@uv run python scripts/check-json.py
	@uv run python scripts/check-file-length.py
	@uv run python scripts/check-compose.py
	@uv run pip-audit --ignore-vuln CVE-2026-4539  # pygments: no fix available yet
	@conftest test Dockerfile --parser dockerfile -p .harness/policy/dockerfile/ --all-namespaces
	@conftest test docker-compose.prod.yml -p .harness/policy/compose/ --all-namespaces -d .harness/data.json
	@conftest test pyproject.toml -p .harness/policy/python/ --all-namespaces
	@conftest test .gitignore --parser ignore -p .harness/policy/gitignore/ --all-namespaces

# ── Fix: auto-fix formatting and import sorting, then verify with lint. ──
fix:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/
	$(MAKE) lint

# ── Tests (with 94% coverage gate, skip-covered output) ──
test:
	uv run python -m pytest

# ── Diff coverage: coverage of changed lines vs main. Fails below 95%. ──
coverage-diff:
	uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=95

# ── Bootstrap (idempotent) ──
bootstrap:
	uv sync
	@command -v prek >/dev/null 2>&1 && prek install || (command -v pre-commit >/dev/null 2>&1 && pre-commit install || echo "Install prek (brew install prek) or pre-commit for git hooks")
	@echo "Dev environment ready. Run 'make lint' to verify."

# ── Aliases ──
fmt: fix
