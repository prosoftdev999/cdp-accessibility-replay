// Installed in the replayed page. Holds the map from protocol node ids to live nodes and
// applies recorded protocol messages to the live document, one call per message.
() => {
  const SVG = 'http://www.w3.org/2000/svg';
  const ATTRIBUTE_NAMESPACES = {
    xlink: 'http://www.w3.org/1999/xlink',
    xml: 'http://www.w3.org/XML/1998/namespace',
    xmlns: 'http://www.w3.org/2000/xmlns/',
  };
  const byNodeId = new Map();
  const byBackendId = new Map();
  const notMirrored = new Set();   // ids the browser reported for nodes it creates itself
  const frameOf = new Map();       // node id of a framed document -> its iframe element
  const pendingFrames = [];        // [iframe element, child payloads of its document]
  const sheets = new Map();        // constructed stylesheets by protocol id
  const sheetStates = new Map();   // owner backend id -> whether its sheet is in use
  const clocks = new WeakMap();    // animation -> transcript time at which it started
  const slotted = new Map();       // slot element -> backend ids the browser said it holds
  const unknown = [];

  const register = (payload, node) => {
    byNodeId.set(payload.nodeId, node);
    byBackendId.set(payload.backendNodeId, node);
  };

  const ignore = (payload) => {
    notMirrored.add(payload.nodeId);
    for (const key of ['children', 'shadowRoots', 'pseudoElements']) (payload[key] || []).forEach(ignore);
    for (const key of ['contentDocument', 'templateContent']) if (payload[key]) ignore(payload[key]);
  };

  const setAttribute = (element, name, value) => {
    const prefix = name.includes(':') ? name.split(':')[0] : name;
    const namespaced = element.namespaceURI === SVG && ATTRIBUTE_NAMESPACES[prefix] && (name.includes(':') || name === 'xmlns');
    if (namespaced) element.setAttributeNS(ATTRIBUTE_NAMESPACES[prefix], name, value);
    else element.setAttribute(name, value);
  };

  const watchLoad = (frame) => {
    frame.loaded = new Promise((resolve) => frame.addEventListener('load', resolve, { once: true }));
  };

  // The adopted list can be announced one message before the sheet's text arrives, so a
  // sheet named there is created empty and filled when the text comes.
  const adoptSheets = (root, ids) => {
    root.adoptedStyleSheets = (ids || []).map((id) => {
      if (!sheets.has(id)) sheets.set(id, new CSSStyleSheet());
      return sheets.get(id);
    });
  };

  // Returns the live node for a protocol node description, creating it on first sight.
  // A node the page moved comes back under a new node id with the same backend id, and
  // must stay the same live node so that what it holds (values, running animations of
  // untouched descendants) is kept.
  const adopt = (payload, doc) => {
    if (payload.nodeType === 10) { ignore(payload); return null; }
    let node = byBackendId.get(payload.backendNodeId);
    if (!node) {
      if (payload.nodeType === 3 || payload.nodeType === 4) node = doc.createTextNode(payload.nodeValue);
      else if (payload.nodeType === 8) node = doc.createComment(payload.nodeValue);
      else if (payload.nodeType === 7) node = doc.createProcessingInstruction(payload.nodeName, payload.nodeValue);
      else {
        node = payload.isSVG ? doc.createElementNS(SVG, payload.localName) : doc.createElement(payload.localName);
        const attributes = payload.attributes || [];
        for (let i = 0; i < attributes.length; i += 2) setAttribute(node, attributes[i], attributes[i + 1]);
        if (payload.localName === 'iframe') watchLoad(node);
      }
    }
    register(payload, node);
    if (payload.nodeType !== 1) return node;
    if (payload.localName === 'slot' && payload.distributedNodes) {
      slotted.set(node, payload.distributedNodes.map((n) => n.backendNodeId));
    }
    for (const shadow of payload.shadowRoots || []) pushShadowRoot(node, shadow, doc);
    (payload.pseudoElements || []).forEach(ignore);
    if (payload.templateContent) {
      register(payload.templateContent, node.content);
      if (payload.templateContent.children) syncChildren(node.content, payload.templateContent.children, node.content.ownerDocument);
    }
    if (payload.contentDocument) {
      frameOf.set(payload.contentDocument.nodeId, node);
      if (payload.contentDocument.children) pendingFrames.push([node, payload.contentDocument.children]);
    }
    if (payload.children) syncChildren(node, payload.children, doc);
    return node;
  };

  const shadowRoots = new WeakMap();
  const pushShadowRoot = (host, payload, doc) => {
    // Shadow trees of built-in controls are created by the engine itself.
    if (payload.shadowRootType === 'user-agent') { ignore(payload); return; }
    let root = shadowRoots.get(host);
    if (!root) {
      // Slots are filled from what the browser reported, not by matching slot names: a
      // page may assign them by hand, and then names say nothing about where a node shows.
      root = host.attachShadow({ mode: payload.shadowRootType, slotAssignment: 'manual' });
      shadowRoots.set(host, root);
    }
    register(payload, root);
    if (payload.children) syncChildren(root, payload.children, doc);
    adoptSheets(root, payload.adoptedStyleSheets);
  };

  const syncChildren = (parent, payloads, doc) => {
    const wanted = payloads.map((p) => adopt(p, doc)).filter(Boolean);
    const present = [...parent.childNodes];
    if (present.length !== wanted.length || present.some((n, i) => n !== wanted[i])) parent.replaceChildren(...wanted);
  };

  const fillDocument = (doc, payloads) => {
    const root = adopt(payloads.find((p) => p.nodeType === 1), doc);
    payloads.filter((p) => p.nodeType !== 1).forEach(ignore);
    if (doc.documentElement !== root) {
      if (doc.documentElement) doc.replaceChild(root, doc.documentElement);
      else doc.append(root);
    }
  };

  const drainFrames = async () => {
    while (pendingFrames.length) {
      // A frame swaps in its own document when it loads; fill it only after that.
      const [frame, payloads] = pendingFrames.shift();
      await Promise.race([frame.loaded, new Promise((resolve) => setTimeout(resolve, 3000))]);
      fillDocument(frame.contentDocument, payloads);
    }
  };

  const assignSlots = () => {
    for (const [slot, backendIds] of slotted) {
      const host = slot.getRootNode().host;
      const wanted = backendIds.map((id) => byBackendId.get(id)).filter((n) => n && host && n.parentNode === host);
      const current = slot.assignedNodes();
      if (wanted.length !== current.length || wanted.some((n, i) => n !== current[i])) slot.assign(...wanted);
    }
  };

  // An owner's sheet object is replaced whenever the element is re-inserted or its text
  // changes, so the recorded state is applied again after every message.
  const switchSheets = () => {
    for (const [owner, enabled] of sheetStates) {
      const sheet = byBackendId.get(owner)?.sheet;
      if (sheet && sheet.disabled === enabled) sheet.disabled = !enabled;
    }
  };

  const lookup = (nodeId) => {
    const node = byNodeId.get(nodeId);
    if (!node && !notMirrored.has(nodeId) && !frameOf.has(nodeId)) unknown.push(nodeId);
    return node;
  };
  const documentOf = (node) => (node.nodeType === 9 ? node : node.ownerDocument);

  const allDocuments = () => {
    const docs = [document];
    for (const frame of new Set(frameOf.values())) if (frame.contentDocument) docs.push(frame.contentDocument);
    return docs;
  };

  const handlers = {
    document({ root, constructed }) {
      for (const [id, text] of constructed) handlers.sheetAdded({ id, text });
      register(root, document);
      fillDocument(document, root.children);
      adoptSheets(document, root.adoptedStyleSheets);
      const fragment = root.documentURL.split('#')[1];
      if (fragment) location.hash = fragment;
    },
    setChildNodes({ parentId, nodes }) {
      if (frameOf.has(parentId)) {
        const frame = frameOf.get(parentId);
        pendingFrames.push([frame, nodes]);
        frame.loaded.then(() => byNodeId.set(parentId, frame.contentDocument));
        return;
      }
      const parent = lookup(parentId);
      if (!parent) { nodes.forEach(ignore); return; }
      if (parent.nodeType === 9) fillDocument(parent, nodes);
      else syncChildren(parent, nodes, documentOf(parent));
    },
    childNodeInserted({ parentNodeId, previousNodeId, node }) {
      const parent = lookup(parentNodeId);
      if (!parent || parent.nodeType === 9) { ignore(node); return; }
      const live = adopt(node, documentOf(parent));
      const previous = previousNodeId ? lookup(previousNodeId) : null;
      if (live.localName === 'iframe') watchLoad(live);
      parent.insertBefore(live, previous ? previous.nextSibling : parent.firstChild);
    },
    childNodeRemoved({ nodeId }) {
      const node = lookup(nodeId);
      if (node && node.parentNode) node.remove();
      byNodeId.delete(nodeId);
    },
    attributeModified({ nodeId, name, value }) {
      const element = lookup(nodeId);
      if (element) setAttribute(element, name, value);
    },
    attributeRemoved({ nodeId, name }) {
      const element = lookup(nodeId);
      if (!element) return;
      // Taking `open` off a modal dialog is how the protocol reports dialog.close().
      if (element.localName === 'dialog' && name === 'open' && element.matches(':modal')) element.close();
      else element.removeAttribute(name);
    },
    attributes({ nodeId, attributes }) {
      // Reply to DOM.getAttributes: the whole attribute list, which is the only place a
      // style changed through script shows up.
      const element = lookup(nodeId);
      if (!element) return;
      const names = new Set();
      for (let i = 0; i < attributes.length; i += 2) {
        names.add(attributes[i]);
        if (element.getAttribute(attributes[i]) !== attributes[i + 1]) setAttribute(element, attributes[i], attributes[i + 1]);
      }
      for (const name of element.getAttributeNames()) if (!names.has(name)) element.removeAttribute(name);
    },
    characterDataModified({ nodeId, characterData }) {
      const node = lookup(nodeId);
      if (node) node.data = characterData;
    },
    shadowRootPushed({ hostId, root }) {
      const host = lookup(hostId);
      if (host) pushShadowRoot(host, root, documentOf(host));
      else ignore(root);
    },
    pseudoElementAdded({ pseudoElement }) { ignore(pseudoElement); },
    distributedNodesUpdated({ insertionPointId, distributedNodes }) {
      const slot = lookup(insertionPointId);
      if (slot) slotted.set(slot, distributedNodes.map((n) => n.backendNodeId));
    },
    adoptedStyleSheetsModified({ nodeId, adoptedStyleSheets }) {
      const root = lookup(nodeId);
      if (root) adoptSheets(root, adoptedStyleSheets);
    },
    sheetAdded({ id, text }) {
      if (!sheets.has(id)) sheets.set(id, new CSSStyleSheet());
      if (text !== null) sheets.get(id).replaceSync(text);
    },
    topLayer({ nodeIds }) {
      // Being in the top layer is not an attribute: a dialog is modal only if it was shown
      // with showModal(), and a popover is rendered only while it is showing.
      const shown = new Set(nodeIds.map((id) => byNodeId.get(id)).filter(Boolean));
      for (const doc of allDocuments()) {
        for (const dialog of doc.querySelectorAll('dialog')) {
          if (shown.has(dialog) && !dialog.matches(':modal')) { dialog.removeAttribute('open'); dialog.showModal(); }
          if (!shown.has(dialog) && dialog.matches(':modal')) dialog.close();
        }
        for (const popover of doc.querySelectorAll('[popover]')) {
          if (shown.has(popover) && !popover.matches(':popover-open')) popover.showPopover();
          if (!shown.has(popover) && popover.matches(':popover-open')) popover.hidePopover();
        }
      }
    },
    sheetState({ owner, enabled }) {
      sheetStates.set(owner, enabled);
    },
    fragment({ url }) {
      if (location.href !== url) location.hash = url.split('#')[1] || '';
    },
  };

  const animations = () => allDocuments().flatMap((doc) => doc.getAnimations());

  window.pageReplay = {
    async apply(kind, params) {
      handlers[kind](params);
      await drainFrames();
      assignSlots();
      switchSheets();
    },
    // Animations and transitions that appeared since the last call began at transcript
    // time `at`. They are held paused so that replay speed has no effect on them.
    stampClocks(at) {
      for (const animation of animations()) {
        if (clocks.has(animation)) continue;
        clocks.set(animation, at);
        animation.pause();
      }
    },
    // Puts every animation where it stood at transcript time `at`, and reports how far
    // each is from the instants at which its effect changes.
    setClocks(at, until) {
      const margins = [];
      for (const animation of animations()) {
        const timing = animation.effect.getComputedTiming();
        const elapsed = at - clocks.get(animation);
        animation.currentTime = elapsed;
        for (const edge of [timing.delay, timing.delay + timing.activeDuration]) {
          margins.push(Math.min(Math.abs(elapsed - edge), Math.abs(until - clocks.get(animation) - edge)));
          if ((elapsed < edge) !== (until - clocks.get(animation) < edge)) margins.push(0);
        }
      }
      return margins;
    },
    node: (backendId) => byBackendId.get(backendId),
    unknown,
  };
}
