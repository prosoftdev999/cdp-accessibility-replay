We recorded one automated test session against the claims console and kept only its DevTools-protocol traffic, in `/app/data/transcript.jsonl`. `/app/data/README.md` has the recording details. The session can't be run again, and the accessibility review now needs to know what the browser was exposing to assistive technology at certain points in it.

Those points, and the nodes to look at for each, are in `/app/data/audit_points.json`. For each node I need what `Accessibility.getPartialAXTree` (with `fetchRelatives: false`) would have returned for it at that point, in the Chromium build the README names. Put the answers in `/app/output/ax_audit.json`, by audit point id and then backend node id:

```json
{
  "points": {
    "c01": {
      "57": {"ignored": true},
      "61": {"ignored": false, "role": "button", "name": "Close selected", "description": "", "states": {"disabled": true, "invalid": "false"}}
    }
  }
}
```

`ignored` is the AX node's `ignored` flag. If it is true, nothing else about the node is read. If not, `role`, `name` and `description` are the `value` of the AX node's fields with those names, or an empty string when the browser gave none. `states` holds the ones among `checked`, `pressed`, `selected`, `expanded`, `disabled`, `invalid`, `required`, `level`, `hasPopup` and `modal` that are in the AX node's `properties`, with the browser's values. Leave out any the node doesn't have.

All listed nodes must be there and all facts must match. Roles have to match exactly. Names and descriptions are compared with whitespace runs collapsed and the ends trimmed. State values are compared as text and case is ignored, so `true` and `"true"` count as the same. Key order doesn't matter and extra keys are ignored. The values in the example are made up.

You have 9000 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
