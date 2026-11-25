# User guide

[Back to mzLoupe](../README.md) · [Installation](../README.md#install-from-github)

- [Project library](#project-library)
- [Project setup](#project-setup-in-the-dashboard)
- [Project JSON and input files](#your-data)
- [Protein grouping](#protein-grouping)
- [Plots and linked selections](#interactions)
- [PSM filtering and sorting](#psm-table-filters-and-sorting)
- [Precursor m/z](#precursor-mz)
- [Preparation, memory, and caching](#memory-and-preparation)

## Project library

Start `mzloupe serve` to open **Projects**, the saved project library for the account
running mzLoupe. Search by name, reopen an existing project, or choose **New project**
or **Import JSON**. Projects remain available after restarting mzLoupe or clearing
prepared caches. A command-line `--project FILE` opens that project directly.

Each project has a permanent UUID. Renaming it, adding fractions, changing
identification layers, or saving edits keeps the same identity. **Duplicate** creates
an independent project with a new ID. The row menu also provides **Edit**, **Export
JSON**, **Archive**, **Clear cache**, and **Delete project**. Archived projects remain
available through **Include archived**. Clearing a cache preserves the project;
deleting a project removes its saved definition and its cache under the current root.
Original input files and caches under other roots are kept. Choose **Close project**
from the active project's menu before clearing its cache or deleting it; restarting mzLoupe is not necessary.

The library stores metadata in `~/.local/share/mzloupe/projects.sqlite`, outside the
cache directory. Use `--registry /path/to/projects.sqlite` to select another registry.
Library rows check cache availability under the current cache root; opening a project
also rechecks its input files. **Edit** loads only the saved configuration, without
preparing mzML.

## Project setup in the dashboard

Choose **New project**, or **Edit** from an existing project's menu, to open **Project setup**. The project selector switches between saved projects; **Projects** returns to the library.

- **Acquisitions** assigns each mzML path to a sample and fraction.
- **Identifications** assigns each sample-level idXML path to a sample and named layer.
- **Protein grouping** loads an inference idXML and selects **Protein groups** or
  **Indistinguishable proteins**. Both populated collections require an explicit
  choice with their counts shown; a single populated collection is selected
  automatically. Empty sample/layer selections apply to all samples/layers.

Use **Add mzML files** or **Add idXML files** to browse the filesystem of the machine running mzLoupe. Select multiple files and give them a common sample. You can also add empty rows and paste paths directly into cells. Sample names have autocomplete. **Show sample** filters both tables.

Errors appear beside the relevant fields. **Save project** or **Save changes** stores
the configuration without preparing data. Empty projects can be saved as drafts, and
missing source files can be corrected later. **Save and explore** saves the project,
prepares only the affected inputs, and opens **Explore**. A preview reports added,
changed, and reused acquisitions. **Project details** shows creation/modification
dates and the project's cache directory.

Switching between **Projects**, **Project setup**, and **Explore** preserves staged
edits. Switching to another project or creating a new one asks before discarding
unsaved changes. During an update, the previous prepared revision remains available
and is labeled clearly; failed preparation does not replace its data. Project-scoped
browser URLs restore the saved project and selected spectrum.

**Import JSON** populates the tables for review. Importing into an existing editor
updates that project's configuration. **Export JSON** opens a directory and filename
chooser on the machine running mzLoupe. Use **Browse directory** to navigate;
`~` refers to that account's home directory. Existing files require **Replace file**.
Exports preserve the project UUID, acquisition IDs, and sample/layer associations,
using absolute source paths. Exporting does not prepare data. There is no browser
download action.

## Your data

Project JSON remains available for programmatic import and export. Paths resolve relative to its location. Acquisition IDs use letters, digits, underscores, or hyphens. An optional top-level `id` is the project UUID; exports include it so moved or regenerated manifests retain their identity. Command-line manifests without an ID are registered once by their import path. For dashboard imports without an ID, use an existing project's editor to update it, or import from the library to create a new project.

```json
{
  "name": "Study A",
  "samples": [
    {
      "name": "Sample 1",
      "identifications": [
        {"name": "Validated", "path": "sample_1_filter.idXML"}
      ]
    }
  ],
  "acquisitions": [
    {
      "id": "sample1_f01",
      "sample": "Sample 1",
      "fraction": "F01",
      "mzml": "fraction_01.mzML"
    },
    {
      "id": "sample1_f02",
      "sample": "Sample 1",
      "fraction": "F02",
      "mzml": "fraction_02.mzML"
    }
  ]
}
```

Run `mzloupe serve --project /absolute/path/project.json`, or enter that path in the dashboard. Associate the merged idXML with the sample once. Its PSMs are assigned to the sample's fractions using `base_name`, `file_origin`, or the identification run's `spectra_data` and zero-based `id_merge_index`. An exact native spectrum reference that occurs in only one eligible acquisition can resolve a record without a fraction hint. Conflicting hints, invalid merge indices, and references that occur in several fractions remain visible as unresolved PSMs with an explanation.

Each acquisition can optionally declare `aliases` for source filenames retained in the idXML after files were moved or renamed. For example, `"aliases": ["original_run.raw"]`. Supply the actual search/validation mzML, including reindexed or reconstructed mzML when those representations produced the PSMs. Fraction ordering in the project does not assign merge indices. The idXML's run-specific `spectra_data` list defines that association.

Identification layers belong to samples and span their associated fractions. mzLoupe also works with mzML alone.

## Protein grouping

Optional inference inputs are stored separately from PSM identification layers:

```json
"protein_groupings": [
  {
    "name": "ProteinProphet groups",
    "path": "cohort-ProteinProphet.idXML",
    "collection": "protein_groups",
    "samples": ["Sample 1"],
    "layers": ["Validated"]
  }
]
```

The collection values are `protein_groups` and `indistinguishable_proteins`.
Each grouping name must be unique. You can load both collections as separate
named views of the same file. Paths resolve relative to the project JSON.
Only idXML inference inputs are supported; Fido JSON is not supported.

The PSM table's **Protein grouping view** selector switches between applicable
inference views and original peptide mappings without loading spectra again.
A uniquely assigned group displays its first accession in original file order
as its representative, with the other-member count. Several possible groups
show their representative accessions separated by semicolons, such as
**A (+1); C (+1)**, with each count referring to additional members in that group.
Long labels truncate within the column; hover reveals the complete combined label,
and clicking opens the individual group memberships. Ambiguous references without
an identifiable group show **Unresolved group**; missing assignments show **Not assigned**.
The popover separates original search mappings, inference peptide mappings,
and full group members. Those lists are not interchangeable.

Inference peptide evidence takes precedence over search evidence. Spectrum-level
assignments are matched within the resolved acquisition, so repeated native scan
IDs across fractions cannot assign a peptide to the wrong group. Sequence-only
inference evidence uses the unmodified peptide sequence and preserves multiple
possible groups. A file containing only groups uses explicitly labelled accession
overlap. Missing inference assignments do not silently fall back to search links.
ProteinProphet's default zero subgroup probabilities are shown as **Not supplied**,
with the stored zero preserved internally; loading does not apply score filtering.

Grouping files are loaded once per activation into a session metadata index.
Changing their paths, scopes, or selected collection reuses the existing scan
catalog and heatmaps; the raw-data fingerprint excludes grouping inputs.
Original PSM IDs and peptide mappings in SQLite remain unchanged.

## Interactions

- Choose a sample and identification layer, then click a fraction card or use the fraction selector.
- The PSM table defaults to **Active fraction**. Choose **All sample fractions** to search the sample, including unresolved records. Selecting a resolved row from another fraction switches the acquisition to that PSM’s source. You can also enable **Show MS2 events** and click an orange diamond.
- Click an assignment in the inspector to change fragment annotations. Fragment tolerance is in ppm. The initial annotator uses singly charged b/y ions.
- Selecting a PSM automatically extracts an MS1 XIC at its peptide precursor m/z from idXML. If idXML omits m/z, mzLoupe calculates it from the modified sequence and charge. Selecting an unassigned MS2 event uses its isolation center, labeled explicitly. You can edit the target and tolerance and select **Extract XIC**. Manual extraction uses the visible retention-time interval. Map and chromatogram time zooms are linked. The caption retains the extraction's target and tolerance.
- **Show PSMs (all layers)** adds a bottom row of marks to the XIC. Each mark represents an MS2 scan with candidates matching the extraction's fraction, retention-time interval, and peptide precursor m/z tolerance. Hover to see all matching sequences, layers, charges, ranks, and scores; click to inspect the spectrum. The selected candidate is orange. Evidence includes all identification layers and ranks independently of the PSM table's search and pagination, so different peptides sharing the m/z remain visible. These marks indicate identification evidence, not additional MS1 intensity measurements.
- Click a populated MS1 map cell to select its strongest measured MS1 peak and automatically extract an XIC at that precise m/z. The selected peak is marked with an orange cross. An empty cell gives an explicit message. The bin center is not a precise precursor target.
- The map is a fixed-resolution overview with log-scaled, summed MS1 intensity per time × m/z bin. The palette runs from dark blue for low intensity through cyan to yellow for high intensity, without a color bar. The map and XIC share fixed plot margins to align their retention-time axes. XIC and spectrum plots omit grid lines. MS2 isolation-center markers are optional and start hidden to preserve map readability in dense DIA acquisitions. Zoom changes the displayed overview. Fine-resolution map tiles, mobility views, and feature layers are future work.
- **Contrast** defaults to the 5th–99.5th percentiles of nonzero log-intensity bins across the acquisition. **Full range** uses zero through the actual maximum, without rounding the maximum upward. **Custom limits** accepts lower and upper values in the hover label's `log10(1 + I)` units and keeps them fixed across fractions for comparison. Values outside the limits use the palette endpoints; raw data, hover values, and XICs are unchanged. Zoom retains the same color limits. Empty or constant maps use a stable full-range fallback.

## PSM table filters and sorting

The PSM table uses Mantine DataTable. Click a column header to sort ascending or
descending, and its funnel button to open that column's filter. Active funnels
are highlighted. **Clear filters** clears column conditions while retaining the
table scope and sort order. Use the Sequence and Scan column filters for peptide
or native scan ID searches.

- **Fraction** and **Layer** allow multiple selections. Selected values within a
  column are combined with OR; different columns are combined with AND.
- **Sequence**, **Scan**, and **Proteins** support literal contains or exact
  matching. SQL wildcard characters such as `%` and `_` are treated literally.
- **Precursor m/z**, **RT (min)**, and **Score** accept inclusive minimum/maximum bounds, including
  zero and open-ended ranges. The Score filter also offers score-type selection;
  score values retain their source scale and higher/lower-is-better semantics.
- **Link** selects resolved or unresolved spectrum references. Unresolved PSMs
  are available in **All sample fractions**, since they have no assigned fraction.

The global identification layer initializes the table's Layer filter. Add layers
or clear that column to compare layers within the table; changing table filters
leaves the active inspection layer and plots unchanged. Grouping views apply to
their configured samples and layers; other rows retain original peptide mappings.
Protein filtering searches every member in the selected view, including members
hidden by a representative label. Exact searches also recognize displayed UniProt
accession IDs. Protein sorting follows the displayed representative or ambiguity
label. Scan sorting follows acquisition scan order; missing scan metadata sorts last.

All filters and sorting apply across the complete scoped result set before
pagination. Filter choices are drawn from that scope, not just the current page.
Use **Rows per page** to choose 25, 50, 100, or 200 rows. Filter and sort edits
restart at page one and do not select a PSM or reload its spectrum/XIC. The selected
candidate keeps its identity even if a filter moves it off the visible page.

Normal queries run against SQLite. Protein filtering/sorting builds a reusable
session index of candidate IDs, labels, and accession strings in batches, limited
to the selected sample, acquisition scope, and layers; no raw
spectra or native idXML objects are retained by that index. Table queries do not
invalidate project preparation or read mzML peak arrays.

## Precursor m/z

The PSM table includes **Precursor m/z**, formatted to five decimal places with
full precision and origin on hover. It uses the peptide precursor reported in
idXML, or the existing sequence/charge calculation when that value is absent.
Missing values show an em dash. Sorting and inclusive range filtering use the
full stored value, with missing values sorted last.

## Memory and preparation

Peak arrays are read one spectrum at a time. pyOpenMS retains scan metadata for the
active reader. Initial preparation reads MS1 signal for map bounds and intensities,
and runs in a background worker while the UI reports progress. Signal operations
are serialized to bound simultaneous readers.

Each project has a stable directory under `~/.cache/mzloupe/projects/<project-id>/`.
Use `--cache /path/to/cache` to select the root for every project in that server.
Cache paths are derived from this root and the project UUID, rather than stored in
the registry. Changing the root uses an existing valid cache there or prepares a new
one; caches under the previous root are neither moved nor deleted. Readiness is
checked from the selected root's cache manifests, so a shared registry cannot make
an absent cache appear ready. File paths, sizes, modification times, and processing
format determine which inputs need preparation, without full content checksums.
Adding a fraction prepares only that acquisition and re-resolves the affected sample's identifications. Changing an idXML reimports only the affected
layer; renaming a project or changing grouping does not reread mzML.

Updates stage complete metadata snapshots inside the same project directory before
publishing them. Unchanged maps and indexed working copies share disk storage.
Superseded snapshots are collected after the server finishes its readers when the
project is closed or the server shuts down.
A project cache has one server owner at a time; another server can browse its saved
configuration but cannot prepare the same cache concurrently. Clearing caches leaves
the durable registry and original input files intact. Cache writes and cleanup reject
paths or symlinks that redirect outside the expected project directory.

Identification files are loaded with pyOpenMS `IdXMLFile` into native protein and peptide identification objects. One complete idXML is held in memory during its import. The reader uses OpenMS run identifiers and source metadata to associate PSMs with acquisitions, then the importer writes the selected fields to SQLite.

First-time preparation reads spectrum headers for scan indexing and decodes only
MS1 peak arrays for acquisition-map bounds and intensities. MS2 peak arrays stay
on disk until requested for inspection. PSM source resolution uses the catalog's
source/native-ID index rather than scanning all scans for each candidate. All
fractions are still prepared before the project opens; large or compressed mzML
files and shared storage can make this initial preparation expensive.

Interactive spectrum and XIC requests open mzML in index-only mode and use the
scan headers already in SQLite, avoiding another XML metadata pass per click.
Each prepared project session reuses one active acquisition reader, the latest
displayed spectrum, and the latest exact XIC request. Annotation requests reuse
the displayed spectrum. Spectrum and trace caches have size limits and are
replaced when the prepared workspace changes. MS1 peak arrays read during XIC
extraction are released after each scan; the complete raw experiment is never
retained in memory. A new target or RT interval still needs its relevant MS1 scans.

For unindexed or gzip-compressed mzML, preparation streams an indexed working copy into the cache. The original stays intact. Budget disk space for that working copy. Wide XIC requests can still take time because the relevant spectra must be decoded.
