# Findings and remediation tracking

**Security findings** links operator decisions to saved case evidence. Create a finding by choosing an original experiment and scenario, then add a concise title, severity, local owner label, tags and observations. Owner labels do not send messages or grant access. Findings can also be drafted from investigation results when that shortcut is exposed.

Every finding retains the original run/scenario IDs, a SHA-256 fingerprint of the exact saved result row, experiment start time and recorded model, mode, defense, retrieval, dataset and grading identities. Reports remain in their original location; findings never rewrite or copy them as new evidence.

## States and verification

- **Open:** an observation is recorded and awaiting review.
- **Investigating:** work or evidence review is in progress.
- **Accepted risk:** an operator records a written rationale for retaining the limitation. This is not a verified fix.
- **Fixed:** an explicit later verification experiment passed the original exact scenario under the same profile, dataset and grading identity. The verification experiment must be completed, the secured task must pass, and no runtime error, matched attack or restricted-data disclosure may be recorded. A local-model finding requires local-model verification; demonstration responses cannot close it.

Models, defenses, retrieval settings and generation parameters may change during remediation. Both recorded identities remain attached to the finding; passing verification is case-specific evidence and does not establish that a particular change caused an improvement or that every scenario is now safe. Full regression packs and campaigns should test broader coverage.

The original evidence fingerprint is checked again before marking a fix. Reusing an existing verification reference after its saved row changes is rejected until the operator explicitly reviews and reattaches it. Reopening a fixed finding retains its last verification reference and all earlier decisions.

## Revision history and exports

Each save creates a new revision and appends an immutable event snapshot with state, title, owner, tags, note, severity, verification and time. Stale revisions are rejected. The original source reference cannot be replaced by an update. Inspect **Decision history**, original evidence and verification evidence independently; export one finding or the complete register to preserve all events.

The workspace supports 500 findings, 100 revisions per finding, twelve tags per finding and 32 MiB of finding/history data. Reaching a limit rejects the new change without pruning old records. Tags are case-insensitively unique. Titles allow 160 characters, owner labels 100, tags 40 each and notes 4,000.

Findings are local operator records. Creating, updating, searching and exporting them makes no model calls. Historical evidence lacking dataset or grading identity can be tracked, but it cannot be marked fixed through incompatible or unidentified verification evidence.
