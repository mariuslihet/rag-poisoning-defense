# Evidence bundles and regression packs

Open **Evidence packs** to preserve selected investigations and create exact regression suites. These actions read saved evidence and make no model calls.

## Export evidence

Choose up to ten saved experiments and optionally include findings whose source, current verification, or historical verification links to those experiments. **Export selected evidence bundle** downloads a ZIP containing:

- Original report JSON, including recorded requests/responses and generation/retrieval settings when available.
- Complete frozen authored definitions, including independent typed references and multi-turn data when present. Authored cohorts preserve their full original identity even when the experiment selected a subset.
- Compatible built-in scenario definitions pinned to their declared dataset and grading versions. Historical incompatible definitions are explicitly marked unavailable; current fixtures are not silently substituted.
- Linked findings and verification references when requested.
- An escaped, self-contained HTML index and metadata file.
- A manifest listing every payload path, byte length and SHA-256 fingerprint.

Bundle generation does not add host report-file locations. It preserves original report contents: local paths already present in recorded errors, operator-authored text, prompts, reference answers and synthetic canaries remain part of that evidence. Review the selected material before sharing it outside the laboratory.

Archives are bounded to 16 MiB, with at most 32 MiB expanded payload and 128 entries. Large selections fail with a request to choose fewer experiments. Export never rewrites original reports or findings. The offline index does not run inference, install software or make network requests.

## Verify a bundle

Choose a Spades ZIP and use **Verify selected archive**. Verification reads the archive in memory without extracting files or opening its HTML. It rejects traversal/absolute paths, duplicate paths, unsupported compression, encrypted entries, symbolic/special-file entries, excessive expansion, inconsistent file lists, duplicate manifest JSON keys, and mismatched payload sizes or fingerprints.

A successful result means payload fingerprints match the supplied manifest. It does **not** authenticate the publisher, establish that an attacker has not replaced both content and manifest, certify HTML safety, or validate model claims. Keep an independently trusted archive fingerprint or manifest when provenance matters. The returned archive SHA-256 identifies the complete bytes verified.

## Build a regression suite

Choose one saved source experiment, then select exact recorded scenarios. The controls can select recorded failures, all recorded cases, or an individual subset. Enter a unique suite name and purpose, then save the frozen regression suite.

The laboratory validates the source dataset/grading identity and retrieves independent scenario references. Authored sources and typed assertions are copied from the original frozen definition. Built-in fixtures stay pinned to their compatible dataset and grading versions. Recorded typed references/required sources must still match; foundation reference facts must agree with their compatible fixtures. Observed model responses are never promoted into expected answers.

Each suite records its source experiment in the purpose text. The source reports remain unchanged. Existing suite controls provide export, exact-selection execution, revision history and campaign use. Missing/stale identities and unavailable case IDs are rejected rather than reconstructed. Duplicate suite names use the existing suite validation rules.

Regression packs identify checks to repeat; creating one is not evidence that a failure has been fixed. Run the suite under reviewed settings and link the resulting evidence through the findings workflow.
