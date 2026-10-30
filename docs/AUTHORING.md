# Scenario studio and local document ingestion

Scenario studio lets an operator define a complex evaluation using their own task, source records, typed reference assertions and required citations. A scenario can be a legitimate control or include an adversarial attachment with an explicit typed-field or synthetic-canary objective. Select several saved scenarios to configure a batch; inference starts through the experiment dialog.

## Define a defensible reference

Write the task as an analytical question. Put evidence and calculation operands in source records. Add independently checked reference fields as numbers, booleans or strings. Numeric tolerance is absolute; string grading uses trimmed, case-insensitive comparison. The model receives field types and documents, while the grader retains expected values and assertion descriptions. Expected values are not copied into the task or response schema.

The first source is primary; all remaining sources enter the supporting retrieval corpus. Required citation IDs must identify legitimate records. Each source has author role, access level and channel trust. Reader clearance controls which access levels can enter context. An adversarial attachment is unapproved by default. Explicit provenance approval tests authenticated false content; it does not establish that the content is true.

Saved definitions have stable custom case IDs, numbered revisions and SHA-256 dataset digests. Earlier snapshots remain inspectable and exportable. Restoring an earlier definition creates a new revision. Saving against a stale revision fails instead of overwriting a newer edit. Experiment and suite snapshots retain the canonical definitions supplied when they were configured.

## Import and review local documents

Choose a local TXT, Markdown, CSV, DOCX or text-based PDF no larger than 4 MiB. Extraction returns a staging preview; explicitly add the reviewed text to the draft. The original upload SHA-256 identifies the uploaded bytes. If the preview is edited, an accompanying provenance warning distinguishes those bytes from the edited source text.

TXT, Markdown and CSV require UTF-8. CSV formulas remain literal text. DOCX extraction reads main-document paragraphs, tabs and breaks with the standard library; headers, footers, annotations, drawings and image content are omitted. Embedded content and macros are never executed. DOCX archive entries and expanded sizes are checked before reading XML; unsafe paths, encrypted entries, links and XML entities are rejected.

PDF requires the optional `documents` dependency (`pypdf`). Parsing runs in a subprocess with a 20-second deadline and a 256 MiB process memory ceiling. Encrypted PDFs and files exceeding 100 pages are rejected. PDF reading can lose layout, and image-only pages require a separate OCR workflow. This importer does not perform OCR or fetch URLs.

## Limits

- 1–40 legitimate source records; 250,000 characters per record; 1,000,000 total document characters including the adversarial attachment.
- 1–30 typed fields; 1–40 unique required citation IDs; up to eight task-derived retrieval queries.
- 20,000 task characters; finite numeric references and tolerances; source IDs must be unique.
- 100 authored scenarios; 50 revisions per scenario; 32 MiB of total authored definition and revision data. Limits reject saves without pruning history.
- Extracted text is limited to 250,000 characters. DOCX is limited to 256 unique entries, 16 MiB expanded content and 4 MiB of main-document XML.

Large documents can exceed a model's retrieval or context budget even when they satisfy authoring limits. Configure retrieval depth and context size, then inspect citation coverage and limitations in the resulting evidence. Imported provenance identifies original content; it is not a cryptographic signature of truth or a document authenticity guarantee.
