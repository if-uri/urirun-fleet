PYTHON ?= python3

.PHONY: doctor-setup doctor-build doctor-test doctor-health

doctor-setup:
	$(PYTHON) -m pip install -e ".[yaml]" pytest

doctor-build:
	$(PYTHON) -m compileall -q urirun_fleet tests

doctor-test:
	$(PYTHON) -m pytest -q

doctor-health:
	$(PYTHON) -m urirun_fleet.cli --help
