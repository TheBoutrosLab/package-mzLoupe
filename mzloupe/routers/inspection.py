"""Scientific queries scoped to one fully prepared project revision."""

from typing import Any

from fastapi import APIRouter, FastAPI, Query

from mzloupe.models import XicRequest, MapTargetRequest
from mzloupe.psm_models import PsmFilters, PsmQuery
from mzloupe.services.project_runtime import ProjectRuntime
from mzloupe.services.signal import SignalService, FragmentAnnotator


class InspectionRoutes:
    """Own scientific queries scoped to one prepared project revision."""

    def __init__(self, runtime: ProjectRuntime) -> None:
        """Keep the application runtime explicit and give this route group its own router."""
        self.runtime = runtime
        self.router = APIRouter(prefix="/api")

    def register(self, app: FastAPI) -> None:
        """Connect public handler methods to their existing HTTP endpoints."""
        self.router.add_api_route(
            "/projects/{token}",
            self.project,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/projects/{token}/psms",
            self.psms,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/projects/{token}/sources/{source}/map",
            self.map_data,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/projects/{token}/sources/{source}/spectra/{ordinal}",
            self.spectrum,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/projects/{token}/map-target",
            self.map_target,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/projects/{token}/xic",
            self.xic,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/projects/{token}/psms/{psm_id}/annotations",
            self.annotations,
            methods=["GET"],
        )
        app.include_router(self.router)

    def project(self, token: str, layer: str | None = None) -> dict[str, Any]:
        """Return the project name and per-fraction identification summaries."""
        with self.runtime.metadata_lock:
            project, catalog, _ = self.runtime.snapshot(token)
            return {
                "name": project.name,
                "acquisitions": catalog.acquisitions(layer),
                "protein_groupings": catalog.groupings.summaries() if catalog.groupings else [],
            }

    def psms(
        self,
        token: str,
        *,
        sample: str,
        source: str | None = None,
        page: int = Query(0, ge=0),
        page_size: int = Query(50, ge=10, le=200),
        filters: str = "{}",
        grouping: str = "",
        sort_by: str = "",
        sort_direction: str = "asc",
    ) -> dict[str, Any]:
        """Filter and sort complete PSM results before paginating the table response."""
        query = PsmQuery.model_validate(
            {
                "sample": sample,
                "source": source,
                "filters": PsmFilters.model_validate_json(filters),
                "grouping": grouping,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "page": page,
                "page_size": page_size,
            }
        )
        with self.runtime.search_lock:
            return self.runtime.search_service(token).page(query)

    def map_data(self, token: str, source: str) -> dict[str, Any]:
        """Load the prepared MS1 map for one fraction."""
        with self.runtime.metadata_lock:
            _, catalog, workspace = self.runtime.snapshot(token)
            return SignalService(catalog, workspace).map(source)

    def spectrum(self, token: str, source: str, ordinal: int) -> dict[str, Any]:
        """Read a single spectrum while serializing native signal access."""
        with self.runtime.signal_lock:
            return self.runtime.signal_service(token).spectrum(source, ordinal)

    def map_target(self, token: str, request: MapTargetRequest) -> dict[str, Any]:
        """Resolve a selected map cell to a measured precursor target."""
        with self.runtime.signal_lock:
            return self.runtime.signal_service(token).map_target(request)

    def xic(self, token: str, request: XicRequest) -> dict[str, Any]:
        """Extract the requested MS1 trace from disk-backed spectra."""
        with self.runtime.signal_lock:
            return self.runtime.signal_service(token).xic(request)

    def annotations(
        self,
        token: str,
        psm_id: int,
        ppm: float = Query(20, gt=0, le=1000),
    ) -> list[dict[str, int | str | float]]:
        """Annotate a resolved PSM's measured spectrum with theoretical fragments."""
        with self.runtime.metadata_lock:
            _, catalog, _ = self.runtime.snapshot(token)
            rows = catalog.rows("SELECT * FROM psms WHERE id=?", (psm_id,))
            if not rows or not rows[0]["resolved"]:
                raise ValueError("PSM has no resolved spectrum")
            psm = rows[0]
            scan = catalog.rows(
                "SELECT ordinal FROM scans WHERE source=? AND native=?",
                (psm["source"], psm["native"]),
            )[0]
        with self.runtime.signal_lock:
            peaks = self.runtime.signal_service(token).spectrum(psm["source"], scan["ordinal"])
        return FragmentAnnotator().annotate(peaks, psm["sequence"], ppm)
