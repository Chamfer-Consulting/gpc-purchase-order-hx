"""The API contract for analytics pages. One generic PageResponse shape — scope +
KPIs + charts + named tables — so the SPA renders any page from a spec and the
service layer has a precise target. Ported page-by-page from dashboard/views/*.py.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

NumFormat = Literal["int", "currency", "currency2", "percent", "text"]


class Kpi(BaseModel):
    label: str
    value: float | int | str
    format: NumFormat = "int"
    delta: str | None = None
    delta_direction: Literal["up", "down", "flat"] | None = None
    delta_label: str | None = None  # caption under the delta, e.g. "vs. prior 30 days"
    spark: list[float] | None = None
    help: str | None = None
    north_star: bool = False  # the page's headline metric (accent underline). None
    #                           set => the SPA accents the first KPI, as before.


class ChartSeries(BaseModel):
    name: str
    data: list[float | None]


class BreakdownRow(BaseModel):
    name: str
    value: float | None = None  # generic magnitude (revenue, count, units, …)
    requested: float | None = None  # requested-vs-shipped charts only
    shipped: float | None = None


class BreakdownPoint(BaseModel):
    x: str | float
    rows: list[BreakdownRow] = Field(default_factory=list)


class ChartBreakdown(BaseModel):
    """A per-x-point constituent breakdown surfaced in the chart tooltip
    (e.g. the top products / customers behind each month or each bar)."""
    by: str  # "product" | "customer" | "size" | …
    label: str  # tooltip sub-heading, e.g. "Top products"
    value_format: NumFormat = "currency"  # how to render row `value`
    points: list[BreakdownPoint] = Field(default_factory=list)


class Chart(BaseModel):
    id: str
    title: str | None = None
    kind: Literal["line", "area", "bar", "stacked_bar", "hbar"] = "line"
    x: list[str | float] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    y_format: NumFormat = "int"
    breakdowns: list[ChartBreakdown] | None = None
    width: Literal["half", "full"] | None = None  # None => the SPA auto-picks by shape


class TableColumn(BaseModel):
    key: str
    label: str
    kind: Literal["text", "int", "currency", "currency2", "percent", "date"] = "text"


class Table(BaseModel):
    title: str | None = None
    columns: list[TableColumn]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    export_name: str | None = None


class Scope(BaseModel):
    count: int = 0
    noun: str = "orders"
    start: str | None = None
    end: str | None = None
    note: str | None = None


class AttentionItem(BaseModel):
    severity: Literal["critical", "serious", "warning", "info"]
    title: str
    count: int = 1
    href: str | None = None  # SPA route, e.g. "/data-quality"


class PageResponse(BaseModel):
    stub: bool = False
    scope: Scope = Field(default_factory=Scope)
    attention: list[AttentionItem] = Field(default_factory=list)
    kpis: list[Kpi] = Field(default_factory=list)
    charts: list[Chart] = Field(default_factory=list)
    tables: dict[str, Table] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
