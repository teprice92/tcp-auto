import sys
from datetime import date, time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "samples"))

from tcp_auto.models import Intersection, LatLon, Phase, ProjectDetails, Project, RoadClass, RoadContext  # noqa: E402


@pytest.fixture
def sample_pdf(tmp_path):
    from make_sample_drawing import make

    p = tmp_path / "drawing.pdf"
    make(str(p))
    return p


def road(**kw) -> RoadContext:
    base = dict(
        name="E University Dr",
        centerline=[LatLon(lat=33.4215, lon=-111.9200), LatLon(lat=33.4215, lon=-111.9050)],  # ~4,560 ft eastbound
        speed_mph=40, speed_confirmed=True, lanes_forward=2, lanes_backward=2, road_class=RoadClass.arterial,
    )
    base.update(kw)
    return RoadContext(**base)


def project(city="Tempe", road_kw=None, **details) -> Project:
    d = dict(
        city=city, work_position="lane",
        phases=[Phase(name="Work", start_date=date(2026, 12, 1), end_date=date(2026, 12, 2), start_time=time(9, 0), end_time=time(15, 0))],
    )
    d.update(details)
    return Project(details=ProjectDetails(**d), road=road(**(road_kw or {})), work_center=LatLon(lat=33.4215, lon=-111.9125))


@pytest.fixture
def make_project():
    return project


@pytest.fixture
def signal_at():
    def f(station, name="S Rural Rd"):
        return [Intersection(station_ft=station, cross_street=name, signalized=True)]
    return f
