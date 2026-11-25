# Changelog

## [0.1.0]

Initial release.

### Added

- Installable Python package with a FastAPI service and bundled React/TypeScript
  dashboard for inspecting mass spectrometry and proteomics data in a browser.
- Persistent project library with stable project IDs, draft saving, reopening,
  editing, duplication, JSON import/export, archive/restore, and separate cache
  clearing and project deletion.
- Incremental project preparation that reuses unchanged acquisition data, refreshes
  affected identification scopes, and preserves the previous usable revision when
  updates fail. Artifact reuse supports copying when hard links are unavailable and
  re-indexes acquisitions with missing catalog headers. Durable project definitions
  remain separate from disposable caches.
- Configurable cache roots with project UUID directories, local cache availability,
  and boundary checks for cache writes and cleanup.
- Interactive project setup with sample/fraction assignments for mzML files and
  sample-level identification layers for idXML files. Includes filesystem
  browsing, batch file selection, and input validation.
- Project JSON import and saving on the machine running mzLoupe, with absolute
  source paths, explicit overwrite confirmation, and atomic file publication.
- Native pyOpenMS mzML and idXML readers with fraction-aware PSM association using
  source metadata and native scan references. Unresolved assignments remain
  searchable with an explanation.
- Sample overview with per-fraction MS2 counts and identification rates.
- MS1 acquisition heatmaps with log-scaled intensity, automatic percentile
  contrast, full-range and custom contrast controls, optional MS2 event markers,
  and selection of precise measured MS1 peaks.
- Measured MS2 spectrum inspection with candidate assignments and singly charged
  b/y fragment annotations at a configurable mass tolerance.
- Precursor chromatograms from peptide identifications, MS1 map selections, or
  manual m/z targets. Includes configurable ppm tolerance, calculated peptide
  masses when needed, linked retention-time zoom, and empty-signal reporting.
- Optional chromatogram PSM marks spanning all identification layers and ranks
  within the extraction window, with grouped scan evidence, assignment details
  on hover, and spectrum selection on click.
- Sample-scoped PSM tables covering the active fraction or all sample fractions,
  with per-column text, multi-select, numeric-range, score-type, and link-status
  filters. Includes server-side sorting and filtering across the complete result
  set, pagination, and selectable page sizes.
- Precursor m/z values in the PSM table, with full-precision sorting and range
  filtering, displayed source information, and explicit missing values.
- Compact protein accession displays with representative labels, member counts,
  full memberships, copy actions, and searches across hidden protein members.
- Optional protein grouping idXML inputs with ProteinGroups or
  IndistinguishableProteins selection, sample/layer scopes, multiple named views,
  original-order representatives, and explicit ambiguous or missing assignments.
- Disk-backed spectrum access, a SQLite metadata/PSM catalog, prepared MS1 maps,
  and indexed working copies for unindexed or gzip-compressed mzML inputs.
- Background preparation progress, versioned reusable project caches, indexed
  source resolution, and bounded session caches for readers, spectra, and XICs.
- Typed explorer transitions for linked fraction, spectrum, peptide, and map
  selections, with cancellable requests and stale-response protection.
- Source-scoped URLs that restore the selected acquisition, scan, and PSM.
- `mzloupe serve` and `mzloupe demo` commands with argument help and synthetic
  two-fraction data generation for development and testing.
- mzLoupe branding, Tabler icons, and links to the GitHub repository and issue
  reporting form.
- Vite live development, Python and frontend regression tests, browser workflow
  checks, dedicated frontend CI with failure screenshots, and Python static-analysis
  configuration.
- Automated release preparation with synchronized Python and frontend package
  versions and a CI check for version consistency.
- BSD-3-Clause licensing with the Sanford Burnham Prebys Medical Discovery
  Institute ("Boutros Lab") copyright notice and build-generated third-party
  notices included in the dashboard and Python distributions.
