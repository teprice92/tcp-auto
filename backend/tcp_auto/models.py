"""Core data models shared by every pipeline stage.

Coordinates:
- Sheet coordinates are PDF points on a page (origin top-left).
- World coordinates are WGS84 lat/lon.
- Layout math happens in a local planar frame in feet (see ``geo.LocalFrame``).
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Ingestion / extraction
# ---------------------------------------------------------------------------


class TextSpan(BaseModel):
    page: int
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points
    size: float = 0.0


class PageModel(BaseModel):
    page: int
    width: float
    height: float
    spans: list[TextSpan]
    scale_ft_per_inch: Optional[float] = None  # e.g. 40.0 for 1" = 40'
    scale_text: Optional[str] = None
    excluded_regions: list[tuple[float, float, float, float]] = Field(default_factory=list)


class Action(str, Enum):
    construct = "construct"
    remove = "remove"


class WorkItem(BaseModel):
    id: str = Field(default_factory=new_id)
    action: Action
    device_type: Optional[str] = None  # pole, transformer, ...
    label_text: str
    page: int
    x: float  # sheet position (points)
    y: float
    confidence: float = 1.0
    source: Literal["keyword", "user", "llm"] = "keyword"
    included: bool = True  # user can switch items off


class TitleBlockInfo(BaseModel):
    job_number: Optional[str] = None
    address: Optional[str] = None
    streets: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    pages: list[PageModel]
    items: list[WorkItem]
    title_block: TitleBlockInfo = Field(default_factory=TitleBlockInfo)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Site / road
# ---------------------------------------------------------------------------


class LatLon(BaseModel):
    lat: float
    lon: float


class RoadClass(str, Enum):
    local = "local"
    collector = "collector"
    arterial = "arterial"
    highway = "highway"


class Intersection(BaseModel):
    """An intersection along the centerline, referenced by station (ft from centerline start)."""

    station_ft: float
    cross_street: str = ""
    signalized: bool = False


class Valued(BaseModel):
    """A value plus where it came from (shown as a badge in the UI)."""

    value: Any = None
    source: Literal["drawing", "osm", "rule_default", "user", "none"] = "none"


class MedianPoint(BaseModel):
    """Median width at a station (divided roads). Width is between the inner edges of the two carriageways."""

    station_ft: float
    width_ft: float


Side = Literal["right", "left"]


class TurnLane(BaseModel):
    """An exclusive right-turn lane: an extra lane outside the curb lane for a stretch before an intersection."""
    side: Side = "right"  # side of the road, relative to the centerline's forward direction
    start_station_ft: float  # stations covered (either order); the lane ends at the intersection
    end_station_ft: float
    cross_street: str = ""
    width_ft: Optional[float] = None  # default: the road's lane width


class Driveway(BaseModel):
    """A driveway / business entrance meeting the road."""
    station_ft: float
    side: Side = "right"
    name: str = ""  # e.g. "Chevron", "Mesa High bus loop"
    width_ft: float = 30.0


class RoadContext(BaseModel):
    name: str = ""
    centerline: list[LatLon]  # ordered; "forward" = direction of increasing station
    speed_mph: int = 35
    speed_confirmed: bool = False
    lanes_forward: int = 1
    lanes_backward: int = 1
    lane_width_ft: float = 12.0
    one_way: bool = False
    divided: bool = False
    center_turn_lane: bool = False  # two-way left-turn lane between the directions (one lane wide)
    road_class: RoadClass = RoadClass.collector
    has_bike_lane: bool = False
    has_sidewalk: bool = True
    intersections: list[Intersection] = Field(default_factory=list)
    median: list[MedianPoint] = Field(default_factory=list)  # empty = no median
    turn_lanes: list[TurnLane] = Field(default_factory=list)  # right-turn lanes
    driveways: list[Driveway] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Project details (form) and timeline
# ---------------------------------------------------------------------------


class Phase(BaseModel):
    name: str
    start_date: date
    end_date: date
    start_time: time = time(8, 30)
    end_time: time = time(15, 30)
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon=0


class Contacts(BaseModel):
    preparer: str = ""
    preparer_phone: str = ""
    field_supervisor: str = ""
    field_supervisor_phone: str = ""
    emergency_contact: str = ""
    emergency_phone: str = ""
    traffic_control_company: str = ""


WorkPosition = Literal["shoulder", "lane"]


class NearbySchool(BaseModel):
    name: str = "School"
    distance_ft: int
    lat: Optional[float] = None
    lon: Optional[float] = None


class ProjectDetails(BaseModel):
    project_name: str = ""
    job_number: str = ""
    permit_number: str = ""
    utility_name: str = "Electric Utility"
    description: str = ""
    address: str = ""
    city: str = ""  # e.g. "Tempe"; empty = unknown / unincorporated
    county: str = ""
    road_owner: Literal["city", "county", "ADOT", "tribal", "unknown"] = "city"
    work_position: WorkPosition = "lane"
    side: Side = "right"  # relative to the forward direction of the centerline
    trucks: int = 2
    flaggers_requested: Optional[bool] = None  # None = let the generator decide
    police_requested: bool = False
    reduced_speed_requested: bool = False
    school_zone: bool = False
    nearby_school: Optional[NearbySchool] = None  # nearest school from the map lookup
    school_checked: bool = False  # a map lookup for schools ran (so "none found" is meaningful)
    near_residential: bool = True
    pedestrian_detour: bool = False
    phases: list[Phase] = Field(default_factory=list)
    contacts: Contacts = Field(default_factory=Contacts)
    notes: str = ""


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


class DeviceType(str, Enum):
    sign = "sign"
    cone = "cone"
    drum = "drum"
    barricade3 = "barricade3"
    arrow_board = "arrow_board"
    cms = "cms"
    flagger = "flagger"
    police = "police"
    truck = "truck"
    light_tower = "light_tower"


class Device(BaseModel):
    id: str = Field(default_factory=new_id)
    type: DeviceType
    code: Optional[str] = None  # MUTCD/ADOT sign code
    label: str = ""
    lat: float
    lon: float
    station_ft: Optional[float] = None
    offset_ft: Optional[float] = None
    rotation_deg: float = 0.0
    direction: Literal["forward", "backward", "both"] = "forward"
    group: str = ""  # advance_warning | taper | tangent | work | termination | ...
    lights: Optional[str] = None  # "Type A", "Type C"
    origin: Literal["generated", "manual"] = "generated"
    rule_ref: Optional[str] = None


class Zone(BaseModel):
    kind: Literal["work_area", "buffer", "taper", "reduced_speed", "roadway", "center_lane", "turn_lane", "driveway"]
    polygon: list[LatLon]
    start_station_ft: float
    end_station_ft: float
    label: str = ""


class Requirement(BaseModel):
    kind: Literal["police", "device", "personnel", "permit", "notice", "checklist", "access"]  # access: turn lanes / driveways
    text: str
    required: bool = True  # False = advisory ("may be required")
    verified: bool = True
    citation: str = ""


class ComplianceIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    message: str
    device_ids: list[str] = Field(default_factory=list)
    rule_ref: Optional[str] = None


class LayoutDimensions(BaseModel):
    speed_mph: int
    work_area_ft: float
    buffer_ft: float
    taper_ft: float
    taper_type: str
    downstream_taper_ft: float
    sign_spacing_ft: dict[str, float]
    taper_spacing_ft: float
    tangent_spacing_ft: float
    template: str
    work_start_station_ft: float
    work_end_station_ft: float


class TcpPlan(BaseModel):
    version: int = 1
    template: str
    devices: list[Device]
    zones: list[Zone]
    dimensions: LayoutDimensions
    requirements: list[Requirement] = Field(default_factory=list)
    issues: list[ComplianceIssue] = Field(default_factory=list)
    night: bool = False


# ---------------------------------------------------------------------------
# Project (persisted)
# ---------------------------------------------------------------------------


class Project(BaseModel):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: ProjectDetails = Field(default_factory=ProjectDetails)
    field_sources: dict[str, str] = Field(default_factory=dict)
    drawing_filename: Optional[str] = None
    extraction: Optional[ExtractionResult] = None
    road: Optional[RoadContext] = None
    work_center: Optional[LatLon] = None
    work_extent_ft: float = 0.0  # spread of the work items along the road
    plan: Optional[TcpPlan] = None
    history: list[dict[str, Any]] = Field(default_factory=list)
