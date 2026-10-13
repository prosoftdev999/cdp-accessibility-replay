# CDP Accessibility Replay

A frontend accessibility reconstruction project focused on replaying historical browser state and recovering the accessibility tree exposed through the Chrome DevTools Protocol.

Modern accessibility behavior is not determined by HTML markup alone. The accessibility tree is derived from DOM structure, ARIA semantics, visibility, focus, element lifetime, computed naming, and browser state.

CDP Accessibility Replay reconstructs that changing state over time.

## Overview

Chrome exposes accessibility information through the Chrome DevTools Protocol Accessibility domain.

An accessibility node may contain information such as:

- accessibility role
- accessible name
- description
- value
- ignored state
- parent/child relationships
- backend DOM identity
- focus state
- accessibility properties

The full accessibility tree can be retrieved through CDP, while partial-tree operations can inspect specific DOM-backed regions. :chatgpt-content-reference{index="2"}

This project treats accessibility as historical runtime state rather than a static snapshot.

## Repository Structure

```text
cdp-accessibility-replay/
├── environment/
├── solution/
├── tests/
├── instruction.md
└── task.toml
```

### `instruction.md`

Defines the reconstruction problem, input evidence, browser semantics, and required output.

### `environment/`

Contains the reproducible runtime and solver-visible browser evidence.

### `solution/`

Contains the reference reconstruction implementation.

### `tests/`

Contains the independent verifier.

### `task.toml`

Defines task metadata and execution configuration.

## Accessibility Tree Reconstruction

The browser accessibility tree is related to the DOM, but it is not simply a copy of the DOM tree.

Conceptually:

```text
DOM
 +
ARIA
 +
computed semantics
 +
visibility
 +
focus
 +
browser state
        ↓
accessibility tree
```

Some DOM nodes may be ignored.

Other elements may expose semantic roles or names derived from:

- native HTML semantics
- `aria-label`
- `aria-labelledby`
- element contents
- associated labels
- state and properties

A correct replay must reconstruct the accessibility-facing result rather than relying only on raw markup.

## Chrome DevTools Protocol

The CDP Accessibility domain includes operations for retrieving accessibility nodes and trees.

Common operations include:

```text
Accessibility.enable
Accessibility.getFullAXTree
Accessibility.getPartialAXTree
Accessibility.getChildAXNodes
Accessibility.queryAXTree
```

Enabling the domain allows AX node IDs to remain consistent between calls while accessibility is enabled. :chatgpt-content-reference{index="3"}

This makes node lifetime and historical identity important during replay.

## AX Nodes and DOM Identity

Accessibility nodes may be associated with backend DOM nodes.

Conceptually:

```text
DOM node
   ↓
browser accessibility computation
   ↓
AX node
```

However, that relationship is not always one-to-one.

A DOM node can be:

- ignored
- replaced
- hidden
- reparented
- removed
- recreated

and the resulting accessibility representation may change.

Therefore:

```text
same visible text
```

does not necessarily imply:

```text
same historical AX node
```

## Accessible Names

Accessible names can come from several sources.

For example:

```html
<button aria-label="Save changes">
    💾
</button>
```

may expose an accessibility name such as:

```text
Save changes
```

rather than the button's visible text.

Similarly, an element can obtain a name from another element through:

```text
aria-labelledby
```

The reconstruction must preserve the naming relationships that existed at the requested historical state.

## Roles

Accessibility roles can come from either native semantics or explicit ARIA.

Examples include:

```text
button
heading
checkbox
textbox
link
list
listitem
dialog
navigation
```

CDP exposes the browser-computed accessibility role rather than requiring a consumer to infer the role purely from the tag name. :chatgpt-content-reference{index="4"}

## Ignored Nodes

Not every DOM element appears as a meaningful accessibility node.

Elements may be ignored because they:

- contribute no accessibility semantics
- are hidden
- participate only in presentation
- are collapsed into another semantic node

A replay engine therefore cannot assume:

```text
number of DOM nodes == number of AX nodes
```

## DOM Mutations

Dynamic applications frequently alter the accessibility tree through mutations such as:

```text
insert element
remove element
change text
change aria-label
change aria-labelledby
toggle hidden state
change role
move focus
replace component
reparent node
```

Each mutation can change the exposed accessibility state.

## Historical Replay

The core task is stateful.

A simplified reconstruction looks like:

```text
initial DOM / AX state
        ↓
mutation
        ↓
accessibility recomputation
        ↓
focus / property update
        ↓
next mutation
        ↓
new AX state
        ↓
historical query
```

Looking only at the final DOM can therefore produce the wrong answer for earlier checkpoints.

## Node Lifetime

Node identity must be interpreted historically.

Consider:

```text
time 1:
backend DOM node 412 → "Submit"

time 2:
node removed

time 3:
new component → "Submit"
```

Although the visible interface may appear unchanged, the historical object identity can be different.

Correct replay must distinguish:

```text
logical UI meaning
```

from:

```text
concrete DOM / AX instance
```

## Focus State

Accessibility consumers depend heavily on focus.

The reconstructed tree may need to track:

- focused DOM node
- focused accessibility node
- element replacement while focused
- focus movement
- removal of the focused node

A stale focus assignment can make an otherwise correct AX tree historically inaccurate.

## Full vs Partial Trees

A full-tree query provides a document-wide accessibility snapshot.

A partial query may expose only a subtree or related nodes.

The reconstruction must therefore preserve enough global state to interpret local observations correctly.

A node appearing in a partial capture does not imply that the capture contains the complete accessibility environment.

## Event Replay

Browser evidence may arrive as events rather than complete snapshots.

Conceptually:

```text
initial state
     +
event stream
     ↓
replay
     ↓
historical AX state
```

Events may change:

- DOM structure
- semantic attributes
- accessible names
- focus
- ignored state
- relationships
- node lifetime

The order of those events matters.

## Accessibility Semantics

This project emphasizes accessibility meaning rather than exact DOM shape.

Two different DOM structures can expose equivalent accessibility semantics.

For example:

```html
<button>Save</button>
```

and another standards-compliant implementation may produce equivalent:

```text
role: button
name: Save
```

The reconstruction should therefore distinguish professionally meaningful accessibility behavior from irrelevant markup differences.

## Common Failure Modes

### Replaying only DOM structure

ARIA and computed accessibility semantics can change the AX tree independently of basic structure.

### Treating AX IDs as permanent global IDs

Accessibility identity is tied to browser/runtime lifetime.

### Using the final accessibility tree for earlier queries

Historical state must be replayed.

### Assuming every DOM node is exposed

Ignored nodes break that assumption.

### Computing names from visible text only

ARIA labels and referenced labeling relationships can override or augment textual content.

### Ignoring focus

Focus is part of the observable accessibility state.

### Matching nodes only by text

Several nodes can share the same name while representing different identities and roles.

## Reconstruction Pipeline

A high-level implementation can be viewed as:

```text
browser evidence
      ↓
recover DOM lifetimes
      ↓
replay DOM mutations
      ↓
apply ARIA / semantic changes
      ↓
resolve AX identity
      ↓
compute role / name / state
      ↓
replay focus
      ↓
reconstruct accessibility tree
      ↓
emit required artifact
```

## Technical Areas

This project exercises:

- Chrome DevTools Protocol
- browser accessibility
- ARIA
- accessible-name computation
- accessibility trees
- DOM reconstruction
- node lifetime tracking
- frontend state replay
- browser event processing
- focus management
- semantic HTML
- historical state reconstruction
- JavaScript
- Python

## Validation

A correct implementation should preserve relationships between:

```text
DOM identity
ARIA semantics
AX identity
role
accessible name
ignored state
focus
historical time
```

rather than treating each accessibility snapshot independently.

For the exact input locations, replay rules, output schema, and ordering requirements, see:

```text
instruction.md
```

## Goal

The goal of CDP Accessibility Replay is to reconstruct what assistive technology would have observed from the browser at specific historical moments.

The central principle is:

> Accessibility is computed runtime state, not merely static HTML.

## License

No license is currently specified.
