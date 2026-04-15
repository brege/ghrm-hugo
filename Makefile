PREFIX  := $(HOME)/.local/bin
BINNAME := ghrm
VENV    := $(CURDIR)/.venv
SRCBIN  := $(VENV)/bin/ghrm

.PHONY: install uninstall assets clean

install: assets
	@if [ ! -d "$(PREFIX)" ]; then \
		echo "error: $(PREFIX) does not exist; create it and add to PATH" >&2; \
		exit 1; \
	fi
	ln --symbolic --force "$(SRCBIN)" "$(PREFIX)/$(BINNAME)"
	@echo "installed $(PREFIX)/$(BINNAME) -> $(SRCBIN)"

uninstall:
	rm --force "$(PREFIX)/$(BINNAME)"
	@echo "removed $(PREFIX)/$(BINNAME)"

assets:
	@uv sync
	@uv run python -m ghrm.assets

clean:
	rm --recursive --force theme/gh-readme/static/vendor
