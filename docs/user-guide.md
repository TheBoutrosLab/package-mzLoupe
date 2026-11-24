# User guide

[Back to mzLoupe](../README.md) · [Installation](../README.md#install-from-github)

- [Project setup](#project-setup-in-the-dashboard)
- [Project JSON and input files](#your-data)
- [Protein grouping](#protein-grouping)
- [Plots and linked selections](#interactions)
- [PSM filtering and sorting](#psm-table-filters-and-sorting)
- [Precursor m/z](#precursor-mz)
- [Preparation, memory, and caching](#memory-and-preparation)

## Project setup in the dashboard

Start `mzloupe serve` to build a project interactively. Choose **Project setup** to edit acquisition, identification, and optional protein grouping tables.

- **Acquisitions** assigns each mzML path to a sample and fraction.
- **Identifications** assigns each sample-level idXML path to a sample and named layer.
- **Protein grouping** loads an inference idXML and selects **Protein groups** or
  **Indistinguishable proteins**. Both populated collections require an explicit
  choice with their counts shown; a single populated collection is selected
  automatically. Empty sample/layer selections apply to all samples/layers.

Use **Add mzML files** or **Add idXML files** to browse the filesystem of the machine running mzLoupe. Select multiple files and give them a common sample. You can also add empty rows and paste paths directly into cells. Sample names have autocomplete. **Show sample** filters both tables.

Errors appear beside the relevant fields. **Open project** or **Apply changes** becomes available after row assignments and source paths pass validation. Applying starts preparation. Switching between **Project setup** and **Explore** preserves the current inspection while edits are staged.

**Import JSON** populates the tables for review. **Save JSON** opens an in-app server
directory and filename chooser and saves the current draft on the machine running
mzLoupe. Use **Browse directory** to navigate that machine's filesystem;
`~` refers to the server user's home directory. Existing files require an explicit
**Replace file** action. The dialog reports the resolved server path after saving.
Saving preserves acquisition IDs and sample/layer associations, writes absolute
source paths so the manifest works from its new location, and does not activate
the draft or reprepare data. There is no browser-download action. Both import and
save use the same project model as the CLI. Compiled dashboard assets are included
in the installed wheel.

## Your data

Create a project JSON. Paths resolve relative to its location. IDs use letters, digits, underscores, or hyphens.

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

Peak arrays are read one spectrum at a time. pyOpenMS retains scan metadata for the active reader. Preparation performs two sequential passes to determine map bounds and populate the catalog and fixed-size map. It runs in a background worker while the UI reports progress. Signal operations are serialized to bound simultaneous readers. Completed preparation is reused when the project mapping and all source paths, sizes, and modification times match. This fingerprint detects routine source changes, and does not perform a full content checksum. Use `--cache /path/to/cache` to choose its location. Remove old project directories there while the server is stopped to reclaim disk space.

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
