-- One mzML acquisition per sample/fraction pair in the project configuration.
CREATE TABLE acquisitions (
    id TEXT PRIMARY KEY,
    sample TEXT,
    fraction TEXT,
    path TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('DIA', 'DDA', 'Unknown'))
);

-- Spectrum metadata; peak arrays remain in mzML.
CREATE TABLE scans (
    source TEXT,
    ordinal INTEGER,
    native TEXT,
    rt REAL,       -- Retention time in seconds.
    level INTEGER,
    mz REAL,       -- MS2 isolation center, when available.
    charge INTEGER,
    isolation_lower_mz REAL, -- Absolute precursor isolation bounds; NULL when unknown.
    isolation_upper_mz REAL,
    PRIMARY KEY (source, ordinal),
    UNIQUE (source, native)
);

CREATE INDEX scan_rt ON scans (source, level, rt);

-- One peptide candidate per row. Unresolved candidates have a NULL source.
CREATE TABLE psms (
    id INTEGER PRIMARY KEY,
    sample TEXT,
    source TEXT,
    layer TEXT,
    native TEXT,
    sequence TEXT, -- Sequence including modifications.
    peptide TEXT,  -- Unmodified sequence for distinct-peptide counts.
    charge INTEGER,
    score REAL,
    score_type TEXT,
    higher_better INTEGER,
    rank INTEGER,
    resolved INTEGER,
    link_reason TEXT,
    source_path TEXT,
    precursor_mz REAL,
    precursor_mz_origin TEXT, -- idXML, calculated, or NULL when unavailable.
    protein_accessions TEXT NOT NULL DEFAULT '[]' -- JSON array of original accessions.
);

CREATE INDEX psm_scan ON psms (source, native);
CREATE INDEX psm_peptide ON psms (peptide);

-- Identification layers registered for each acquisition.
CREATE TABLE layers (
    source TEXT,
    name TEXT,
    PRIMARY KEY (source, name)
);
