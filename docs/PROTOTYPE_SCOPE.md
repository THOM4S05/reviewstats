# Prototype scope

The previous checkout contained a paid-pilot planning document. Its commercial targets and rollout milestones were proposals, not evidence of actual customers, deployment, measured accuracy or live integrations. This portfolio copy replaces that presentation with the current verified prototype scope.

The demonstrated inputs are mock POS orders and simulated reviews. Persistent QR/NFC URLs, delayed reconciliation, attribution evidence and owner analytics are implemented. The existing Google Business Profile provider adapter remains in the code as an experimental extension; its parser has a fixture-based test, but live access, OAuth refresh, approval and real response behaviour have not been verified here.

See [matching](MATCHING.md) for the implemented heuristic, [database relationships](DATABASE.md) for the data model, and the [changelog](CHANGELOG.md) for dated updates. There is no claim of paid pilots, production traffic or measured accuracy.
