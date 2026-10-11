PREFIX ?= /usr/local
SOURCES := $(shell sed -n 's/^@include //p' foie-gras.in)

foie-gras: foie-gras.in $(SOURCES)
	awk '/^@include /{while ((getline line < $$2) > 0) print line; close($$2); next} 1' $< > $@
	chmod +x $@

claude/foie-gras/feed.py: codex/feed.py
	cp $< $@

install: foie-gras
	mkdir -p $(DESTDIR)$(PREFIX)/bin
	install -m 755 foie-gras $(DESTDIR)$(PREFIX)/bin/

.PHONY: install
.DELETE_ON_ERROR:
