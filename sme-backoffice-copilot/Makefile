.PHONY: install format lint test backend-install backend-format backend-lint backend-test backend-test-unit backend-test-integration frontend-install frontend-format frontend-lint frontend-test

install: backend-install frontend-install

format: backend-format frontend-format

lint: backend-lint frontend-lint

test: backend-test frontend-test

backend-format:
	$(MAKE) -C backend format

backend-install:
	$(MAKE) -C backend install

backend-lint:
	$(MAKE) -C backend lint

backend-test:
	$(MAKE) -C backend test

backend-test-unit:
	$(MAKE) -C backend test-unit

backend-test-integration:
	$(MAKE) -C backend test-integration

frontend-format:
	npm --prefix frontend run format

frontend-install:
	npm --prefix frontend install

frontend-lint:
	npm --prefix frontend run lint

frontend-test:
	npm --prefix frontend run test
