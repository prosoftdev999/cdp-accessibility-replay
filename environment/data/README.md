# Recording notes

`transcript.jsonl` is the DevTools-protocol traffic of one automated session against the
claims console at `desk.parcelline.test`, read off the page's own debugging socket. One line
per message, in the order they crossed the socket:

    {"seq": 12, "t_ms": 431, "dir": "send", "msg": {...}}

`msg` is the protocol message as it was: a command the recorder sent (`id`, `method`,
`params`), the browser's reply to one (`id` with `result` or `error`), or an event (`method`,
`params`). `dir` is `send` for commands, `recv` for replies and events. `seq` starts at 1
with no gaps. `t_ms` is milliseconds since the recorder attached.

The recorder drove the page with `Input` and `Emulation` commands and made the queries an
inspector front end makes. We did not keep network bodies, script sources or screenshots,
and the site can't be reached from here. The page was never scrolled.

Browser: Chromium 153.0.8010.12, the headless shell that Playwright 1.63.0 installs. This
image has the same build and the same Playwright (Python), under `/opt/pw-browsers`.

`audit_points.json` lists the audit points. `"after_seq": N` means the page as it stood once
message N had been handled and before message N+1. `nodes` are backend node ids of elements
that were in the page then: in the main document, in framed documents, and in shadow trees
attached by the page's own scripts.

A few accessibility queries were made by hand during the session, and their replies are in
the transcript. Each one was made while the page stood at one of the audit points.

What the transcript records is enough to settle every fact the audit asks for. The site
serves its pages minified and its scripts add no whitespace-only text nodes, so the page has
none. The protocol doesn't report the event listeners scripts attach; leaving them out
changes no audited fact. The page's scripts never move keyboard focus themselves, and they move
nodes with ordinary append and insert calls, never `moveBefore()`.
