"""Answer the accessibility audit from the protocol transcript alone.

The session is replayed into a live page in the same Chromium build. Recorded events are
applied to the page as DOM operations, recorded Input and Emulation commands are sent to
it again so that the browser's own behaviour (typing, ticking, focus, fragment
navigation, popovers) happens for real, and CSS animations are held to the transcript's
clock. At each audit point the page is asked for the accessibility node of every listed
element.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import Error as PlaywrightError, async_playwright

from report import audit_facts

DATA = Path("/app/data")
OUTPUT = Path("/app/output/ax_audit.json")
PAGE_REPLAY = (Path(__file__).parent / "page_replay.js").read_text(encoding="utf-8")

# Messages closer together than this were produced by one burst of script in the page.
SAME_BURST_MS = 8
# An audit point must not sit this close to the instant an animation changes its effect.
CLOCK_MARGIN_MS = 1500

EVENT_HANDLERS = {
    "DOM.setChildNodes": "setChildNodes", "DOM.childNodeInserted": "childNodeInserted",
    "DOM.childNodeRemoved": "childNodeRemoved", "DOM.attributeModified": "attributeModified",
    "DOM.attributeRemoved": "attributeRemoved", "DOM.characterDataModified": "characterDataModified",
    "DOM.shadowRootPushed": "shadowRootPushed", "DOM.pseudoElementAdded": "pseudoElementAdded",
    "DOM.adoptedStyleSheetsModified": "adoptedStyleSheetsModified",
    "DOM.distributedNodesUpdated": "distributedNodesUpdated",
}


def load_transcript(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def linked_sheet_texts(rows):
    """Text of every stylesheet the page loaded from a URL, keyed by that URL."""
    headers, requests, texts = {}, {}, {}
    for row in rows:
        msg = row["msg"]
        if msg.get("method") == "CSS.styleSheetAdded" and row["dir"] == "recv":
            headers[msg["params"]["header"]["styleSheetId"]] = msg["params"]["header"]
        elif row["dir"] == "send" and msg["method"] == "CSS.getStyleSheetText":
            requests[msg["id"]] = msg["params"]["styleSheetId"]
        elif row["dir"] == "recv" and msg.get("id") in requests and "result" in msg:
            header = headers[requests[msg["id"]]]
            if header["sourceURL"] and not header["isInline"] and not header["isConstructed"]:
                assert texts.setdefault(header["sourceURL"], msg["result"]["text"]) == msg["result"]["text"]
    return texts


def recorded_spot_checks(rows):
    """Accessibility replies that survived in the transcript, with the seq of their request."""
    requests, checks = {}, []
    for row in rows:
        msg = row["msg"]
        if row["dir"] == "send" and msg["method"] == "Accessibility.getPartialAXTree":
            requests[msg["id"]] = (row["seq"], msg["params"]["backendNodeId"])
        elif row["dir"] == "recv" and msg.get("id") in requests:
            seq, backend_id = requests.pop(msg["id"])
            checks.append((seq, backend_id, msg["result"]["nodes"][0]))
    return checks


def changes_page(row):
    msg = row["msg"]
    return row["dir"] == "recv" and "id" not in msg and msg["method"].split(".")[0] in ("DOM", "CSS")


class Replay:
    def __init__(self, page, session, rows):
        self.page = page
        self.session = session
        self.rows = rows
        self.sheet_texts = linked_sheet_texts(rows)
        self.constructed = {}        # protocol id -> current text of each constructed sheet
        self.sheet_owner = {}        # protocol id -> backend id of the element that owns the sheet
        self.owner_sheets = {}       # backend id -> ids of its sheets that are active
        self.calls = {}              # command id -> the command, until its reply arrives
        self.ready = False           # a document has been rebuilt and events can be applied
        self.shell = ""
        self.address = None
        self.clock = 0               # transcript time of the last message applied

    async def serve(self, route):
        # The page lives at the recorded address so relative URLs resolve as they did. It may
        # load the stylesheet texts held in the transcript and nothing else, and navigations
        # started by replayed clicks must leave it in place.
        request = route.request
        if request.url == self.address and request.resource_type == "document" and self.shell:
            body, self.shell = self.shell, ""
            await route.fulfill(body=body, content_type="text/html; charset=utf-8")
        elif request.url in self.sheet_texts:
            await route.fulfill(body=self.sheet_texts[request.url], content_type="text/css; charset=utf-8")
        elif request.is_navigation_request() and request.frame == self.page.main_frame:
            await route.fulfill(status=204, body="")
        else:
            await route.abort()

    async def in_page(self, kind, params):
        await self.page.evaluate("([kind, params]) => window.pageReplay.apply(kind, params)", [kind, params])

    async def rebuild_document(self, root):
        doctype = next((c for c in root["children"] if c["nodeType"] == 10), None)
        shell = self.shell = (f"<!DOCTYPE {doctype['nodeName']}>" if doctype else "") + "<html><head></head><body></body></html>"
        self.address = root["documentURL"].partition("#")[0]
        # A navigation started by a replayed click may still be finishing; it cancels ours once.
        for attempt in range(5):
            try:
                await self.page.goto(self.address)
                break
            except PlaywrightError:
                if attempt == 4:
                    raise
                self.shell = self.shell or shell
                await asyncio.sleep(0.2)
        await self.page.evaluate(PAGE_REPLAY)
        await self.in_page("document", {"root": root, "constructed": list(self.constructed.items())})
        for owner, active in self.owner_sheets.items():
            await self.in_page("sheetState", {"owner": owner, "enabled": bool(active)})
        self.ready = True

    async def sheet_in_use(self, sheet_id, owner):
        # A sheet that leaves the active set while its owner element stays in the page was
        # switched off from script; nothing in the DOM says so.
        if owner is None:
            owner = self.sheet_owner.pop(sheet_id, None)
            if owner is None:
                return
            self.owner_sheets[owner].discard(sheet_id)
        else:
            self.sheet_owner[sheet_id] = owner
            self.owner_sheets.setdefault(owner, set()).add(sheet_id)
        if self.ready:
            await self.in_page("sheetState", {"owner": owner, "enabled": bool(self.owner_sheets[owner])})

    async def stamp_clocks(self):
        if self.ready:
            await self.page.evaluate("at => window.pageReplay.stampClocks(at)", self.clock)

    async def apply(self, row):
        msg = row["msg"]
        if row["t_ms"] - self.clock > SAME_BURST_MS:
            await self.stamp_clocks()
        self.clock = row["t_ms"]

        if row["dir"] == "send":
            self.calls[msg["id"]] = msg
            if msg["method"].split(".")[0] in ("Input", "Emulation"):
                await self.session.send(msg["method"], msg.get("params", {}))
            return
        if "id" in msg:
            call = self.calls.pop(msg["id"])
            if "result" in msg:
                await self.on_reply(call["method"], call.get("params", {}), msg["result"])
            return
        await self.on_event(msg["method"], msg.get("params", {}))

    async def on_reply(self, method, params, result):
        if method == "DOM.getDocument":
            await self.rebuild_document(result["root"])
        elif method == "CSS.getStyleSheetText" and params["styleSheetId"] in self.constructed:
            self.constructed[params["styleSheetId"]] = result["text"]
            if self.ready:
                await self.in_page("sheetAdded", {"id": params["styleSheetId"], "text": result["text"]})
        elif method == "DOM.getAttributes" and self.ready:
            await self.in_page("attributes", {"nodeId": params["nodeId"], "attributes": result["attributes"]})
        elif method == "DOM.getTopLayerElements" and self.ready:
            await self.in_page("topLayer", result)

    async def on_event(self, method, params):
        if method == "DOM.documentUpdated":
            # Every node id is void until the recorder's next DOM.getDocument is answered.
            self.ready = False
        elif method == "CSS.styleSheetAdded":
            header = params["header"]
            if header["isConstructed"]:
                self.constructed[header["styleSheetId"]] = None
            elif "ownerNode" in header:
                await self.sheet_in_use(header["styleSheetId"], header["ownerNode"])
        elif method == "CSS.styleSheetRemoved":
            self.constructed.pop(params["styleSheetId"], None)
            await self.sheet_in_use(params["styleSheetId"], None)
        elif not self.ready:
            return
        elif method == "Page.navigatedWithinDocument":
            if params["url"].partition("#")[0] == self.address:
                await self.in_page("fragment", params)
        elif method in EVENT_HANDLERS:
            await self.in_page(EVENT_HANDLERS[method], params)

    async def audit(self, point, until):
        """Facts for one audit point; `until` is the transcript time of the next message."""
        await self.stamp_clocks()
        margins = await self.page.evaluate("([at, until]) => window.pageReplay.setClocks(at, until)", [self.clock, until])
        assert all(m >= CLOCK_MARGIN_MS for m in margins), f"{point['id']}: an animation changes within {min(margins)} ms"
        unknown = await self.page.evaluate("window.pageReplay.unknown")
        assert not unknown, f"{point['id']}: events for nodes that were never described: {unknown[:5]}"

        facts = {}
        for backend_id in point["nodes"]:
            handle = await self.session.send("Runtime.evaluate", {"expression": f"window.pageReplay.node({backend_id})"})
            object_id = handle["result"].get("objectId")
            assert object_id, f"{point['id']}: node {backend_id} is not in the replayed page"
            tree = await self.session.send("Accessibility.getPartialAXTree", {"objectId": object_id, "fetchRelatives": False})
            facts[str(backend_id)] = audit_facts(tree["nodes"][0])
            await self.session.send("Runtime.releaseObject", {"objectId": object_id})
        return facts


def check_against_recorded(point, facts, rows, spot_checks):
    # Every reply the session itself recorded while the page stood at this point must come
    # out of the replayed page unchanged; otherwise the replay is not faithful.
    for seq, backend_id, recorded in spot_checks:
        at_this_point = seq > point["after_seq"] and not any(changes_page(r) for r in rows[point["after_seq"]:seq - 1])
        if at_this_point and str(backend_id) in facts:
            assert facts[str(backend_id)] == audit_facts(recorded), (point["id"], backend_id)


async def main():
    rows = load_transcript(DATA / "transcript.jsonl")
    points = sorted(json.loads((DATA / "audit_points.json").read_text(encoding="utf-8"))["points"],
                    key=lambda p: p["after_seq"])
    spot_checks = recorded_spot_checks(rows)
    report = {}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        session = await context.new_cdp_session(page)
        replay = Replay(page, session, rows)
        await page.route("**/*", replay.serve)

        for row in rows:
            while points and points[0]["after_seq"] < row["seq"]:
                point = points.pop(0)
                report[point["id"]] = await replay.audit(point, until=row["t_ms"])
                check_against_recorded(point, report[point["id"]], rows, spot_checks)
            await replay.apply(row)
        for point in points:
            report[point["id"]] = await replay.audit(point, until=replay.clock)
            check_against_recorded(point, report[point["id"]], rows, spot_checks)
        await browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"points": report}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
