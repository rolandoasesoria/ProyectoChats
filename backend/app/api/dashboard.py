"""Panel de actividad."""
from enum import IntEnum

from fastapi import APIRouter

from .. import metrics
from .deps import CurrentUser

router = APIRouter()


class DashboardPeriod(IntEnum):
    WEEK = 7
    MONTH = 30
    QUARTER = 90
    YEAR = 365


@router.get("/api/dashboard")
def dashboard(user: CurrentUser, days: DashboardPeriod = DashboardPeriod.MONTH):
    """Métricas del equipo. El desglose por persona solo lo ven los administradores."""
    return metrics.dashboard(int(days), include_people=user["role"] == "admin")
