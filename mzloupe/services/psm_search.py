"""Filter and order complete PSM results before selecting a display page."""

import json
from typing import Any

from mzloupe.psm_models import PsmQuery, TextFilter
from mzloupe.services.psm_proteins import PsmProteinIndex, ProteinSearchScope
from mzloupe.storage.catalog import ProjectCatalog


class PsmConditions:
    """Build parameterized column predicates separately from ordering and pagination."""

    def __init__(self, query: PsmQuery) -> None:
        """Start with the selected sample and optional acquisition scope."""
        self.clauses = ["p.sample=?"]
        self.parameters: list[Any] = [query.sample]
        if query.source:
            self.clauses.append("p.source=?")
            self.parameters.append(query.source)

    @staticmethod
    def literal_pattern(value: str) -> str:
        """Escape LIKE metacharacters so pasted identifiers are searched literally."""
        return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    def text(self, column: str, condition: TextFilter) -> None:
        """Add an exact or contains predicate for an application-owned SQL column."""
        if not condition.value:
            return
        if condition.mode == "exact":
            self.clauses.append(column + " = ? COLLATE NOCASE")
            self.parameters.append(condition.value)
        else:
            self.clauses.append(column + " LIKE ? ESCAPE '\\'")
            self.parameters.append(self.literal_pattern(condition.value))

    def choices(self, column: str, values: list[str]) -> None:
        """Add OR choices within a column; empty selections leave it unrestricted."""
        if values:
            self.clauses.append(column + " IN (" + ",".join("?" for _ in values) + ")")
            self.parameters.extend(values)

    def bounds(self, column: str, lower: float | None, upper: float | None) -> None:
        """Apply inclusive numeric bounds while excluding NULL values naturally."""
        for operator, value in ((">=", lower), ("<=", upper)):
            if value is not None:
                self.clauses.append(column + operator + "?")
                self.parameters.append(value)

    def columns(self, query: PsmQuery) -> None:
        """Combine independent column filters with the table scope."""
        filters = query.filters
        if filters.fractions:
            ids = [value for value in filters.fractions if value != "__unresolved__"]
            branches = ["p.source IS NULL"] if "__unresolved__" in filters.fractions else []
            if ids:
                branches.append("p.source IN (" + ",".join("?" for _ in ids) + ")")
                self.parameters.extend(ids)
            self.clauses.append("(" + " OR ".join(branches) + ")")
        self.choices("p.layer", filters.layers)
        self.text("p.sequence", filters.sequence)
        self.text("p.native", filters.native)
        self.bounds(
            "s.rt",
            filters.rt_min * 60 if filters.rt_min is not None else None,
            filters.rt_max * 60 if filters.rt_max is not None else None,
        )
        self.bounds("p.precursor_mz", filters.precursor_mz_min, filters.precursor_mz_max)
        self.bounds("p.score", filters.score_min, filters.score_max)
        if filters.score_type:
            self.clauses.append("p.score_type=?")
            self.parameters.append(filters.score_type)
        if filters.link:
            self.clauses.append("p.resolved=?")
            self.parameters.append(int(filters.link == "resolved"))

    def sql(self) -> str:
        """Return the complete WHERE clause with values kept in parameters."""
        return " WHERE " + " AND ".join(self.clauses)


class PsmSearch:
    """Own reusable protein indexes and scoped table queries for one project session."""

    metadata_joins = (
        " LEFT JOIN acquisitions a ON p.source=a.id"
        " LEFT JOIN scans s ON p.source=s.source AND p.native=s.native"
    )
    joined_tables = " FROM psms p" + metadata_joins
    sort_columns = {
        "fraction": "a.fraction COLLATE NOCASE",
        "sequence": "p.sequence COLLATE NOCASE",
        "native": "s.ordinal",
        "rt": "s.rt",
        "precursor_mz": "p.precursor_mz",
        "layer": "p.layer COLLATE NOCASE",
        "score": "p.score",
        "resolved": "p.resolved",
    }

    def __init__(self, catalog: ProjectCatalog) -> None:
        """Defer protein indexing until a protein filter or sort actually needs it."""
        self.catalog = catalog
        self.protein_indexes: dict[str, PsmProteinIndex] = {}
        self.facet_cache: dict[tuple, dict[str, Any]] = {}

    def protein_ids(self, query: PsmQuery) -> list[int]:
        """Reuse an index for the chosen view without loading mzML or idXML again."""
        scope = ProteinSearchScope(
            sample=query.sample,
            source=query.source,
            layers=tuple(sorted(set(query.filters.layers))),
        )
        index = self.protein_indexes.get(query.grouping)
        if index is None or index.scope != scope:
            if query.grouping:
                summaries = self.catalog.groupings.summaries() if self.catalog.groupings else []
                if query.grouping not in {item["name"] for item in summaries}:
                    raise ValueError("Unknown protein grouping view")
            # Keep one scope per view so browsing other samples does not retain
            # the entire project's protein metadata in memory.
            self.protein_indexes[query.grouping] = PsmProteinIndex(
                catalog=self.catalog,
                grouping=query.grouping,
                scope=scope,
            )
        direction = query.sort_direction if query.sort_by == "proteins" else None
        return self.protein_indexes[query.grouping].matching_ids(query.filters.proteins, direction)

    def ordering(self, query: PsmQuery) -> str:
        """Use a whitelist of SQL columns, with missing values last and stable ID ties."""
        if query.sort_by == "proteins":
            return " ORDER BY CAST(protein_order.key AS INTEGER),p.id"
        if not query.sort_by:
            return " ORDER BY (p.source IS NULL),a.fraction,s.rt,p.id"
        column = self.sort_columns[query.sort_by]
        direction = "DESC" if query.sort_direction == "desc" else "ASC"
        return f" ORDER BY ({column} IS NULL),{column} {direction},p.id"

    def facets(self, query: PsmQuery) -> dict[str, Any]:
        """Offer choices across the table scope, rather than only the visible page."""
        key = (query.sample, query.source)
        if key not in self.facet_cache:
            scope = PsmConditions(query)
            rows = self.catalog.rows(
                "SELECT DISTINCT p.source,a.fraction,p.layer,p.score_type"
                + self.joined_tables
                + scope.sql(),
                scope.parameters,
            )
            fractions = {
                row["source"] or "__unresolved__": row["fraction"] or "Unresolved" for row in rows
            }
            self.facet_cache[key] = {
                "fractions": [
                    {"value": value, "label": label}
                    for value, label in sorted(
                        fractions.items(), key=lambda item: item[1].casefold()
                    )
                ],
                "layers": sorted({row["layer"] for row in rows}),
                "score_types": sorted({row["score_type"] for row in rows}),
            }
        return self.facet_cache[key]

    def page(self, query: PsmQuery) -> dict[str, Any]:
        """Apply every condition and order across all matches, then return one page."""
        conditions = PsmConditions(query)
        conditions.columns(query)
        tables = self.joined_tables
        parameters: list[Any] = []
        if query.filters.proteins.value or query.sort_by == "proteins":
            identifiers = json.dumps(self.protein_ids(query))
            if query.sort_by == "proteins":
                # CROSS JOIN fixes the loop order: walk the ordered IDs once,
                # then look each PSM up by primary key. An ordinary JOIN can
                # make SQLite rescan every ID for each scoped PSM (quadratic).
                tables = " FROM json_each(?) protein_order CROSS JOIN psms p" + self.metadata_joins
                conditions.clauses.insert(0, "p.id=protein_order.value")
                parameters.append(identifiers)
            else:
                conditions.clauses.append("p.id IN (SELECT value FROM json_each(?))")
                conditions.parameters.append(identifiers)
        parameters.extend(conditions.parameters)
        where = tables + conditions.sql()
        counts = self.catalog.rows(
            "SELECT count(*) AS total,count(DISTINCT p.peptide) AS peptides" + where,
            parameters,
        )[0]
        page = min(query.page, max(0, (counts["total"] - 1) // query.page_size))
        rows = self.catalog.psm_rows(
            "SELECT p.*,a.fraction,s.ordinal,s.rt"
            + where
            + self.ordering(query)
            + " LIMIT ? OFFSET ?",
            [*parameters, query.page_size, page * query.page_size],
        )
        return {
            **counts,
            "rows": rows,
            "page": page,
            "page_size": query.page_size,
            "facets": self.facets(query),
        }
