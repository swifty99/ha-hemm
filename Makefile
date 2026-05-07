.PHONY: test test-container test-pi test-slow ci ci-full lint format install-hactl

## Default: fast unit tests only
test:
	uv run pytest

## Container-based integration tests (Docker required)
test-container: install-hactl
	uv run pytest -m container

## Pi hardware tests (manual / self-hosted runner)
test-pi:
	uv run pytest -m pi

## Long-running simulation tests
test-slow:
	uv run pytest -m slow

## CI minimum: lint + unit tests
ci: lint test

## CI full: ci + container tests
ci-full: ci test-container

## Lint and format check
lint:
	uv run ruff check custom_components/ tests/
	uv run ruff format --check custom_components/ tests/

## Auto-format
format:
	uv run ruff format custom_components/ tests/
	uv run ruff check --fix custom_components/ tests/

## Install hactl binary (downloads latest release from GitHub)
install-hactl:
ifeq ($(OS),Windows_NT)
	@if not exist .bin mkdir .bin
	@powershell -Command "$$ProgressPreference='SilentlyContinue'; $$tag=(Invoke-RestMethod 'https://api.github.com/repos/swifty99/hactl/releases/latest').tag_name; $$v=$$tag.TrimStart('v'); $$url=\"https://github.com/swifty99/hactl/releases/download/$$tag/hactl_$${v}_windows_amd64.zip\"; Invoke-WebRequest -Uri $$url -OutFile '.bin/hactl.zip'; Expand-Archive -Path '.bin/hactl.zip' -DestinationPath '.bin' -Force; Remove-Item '.bin/hactl.zip'"
	@echo "hactl installed to .bin/hactl.exe"
else
	@mkdir -p .bin
	@TAG=$$(curl -sL https://api.github.com/repos/swifty99/hactl/releases/latest | grep tag_name | head -1 | cut -d'"' -f4); \
	 VERSION=$${TAG#v}; \
	 ARCH=$$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/'); \
	 OS_NAME=$$(uname -s | tr '[:upper:]' '[:lower:]'); \
	 curl -sL "https://github.com/swifty99/hactl/releases/download/$${TAG}/hactl_$${VERSION}_$${OS_NAME}_$${ARCH}.tar.gz" | tar xz -C .bin/
	@chmod +x .bin/hactl
	@echo "hactl installed to .bin/hactl"
endif

## Build (HACS compatible zip)
build:
	@echo "Build step: package custom_components/hemm for HACS"
	@mkdir -p dist
	@cd custom_components && zip -r ../dist/hemm.zip hemm/
