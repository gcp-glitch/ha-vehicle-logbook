"""Pure logbook calculations (no Home Assistant imports, easy to unit test)."""

from __future__ import annotations

import calendar
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import io
from typing import Any
import uuid

from .const import (
    CONF_DUE_SOON_DAYS,
    CONF_DUE_SOON_KM,
    CONF_OIL_INTERVAL_KM,
    CONF_OIL_INTERVAL_MONTHS,
    CONF_SERVICE_INTERVAL_KM,
    CONF_SERVICE_INTERVAL_MONTHS,
    CONF_TYRE_MAX_AGE_YEARS,
    CONF_TYRE_MAX_KM,
    CONF_TYRE_ROTATION_KM,
    DOCUMENTS,
    ITEM_OIL,
    ITEM_SERVICE,
    ITEM_TYRE_ROTATION,
    ITEM_TYRES,
    PARTS,
    RECORD_LISTS,
    STATUS_DUE_SOON,
    STATUS_OK,
    STATUS_OVERDUE,
    STATUS_UNKNOWN,
)

KM_RATE_WINDOW_DAYS = 90
MAX_SANE_LITRES = 200
KM_RATE_MIN_SPAN_DAYS = 7
ODOMETER_LOG_MAX = 400


def empty_data() -> dict[str, Any]:
    """Return an empty logbook."""
    data: dict[str, Any] = {name: [] for name in RECORD_LISTS}
    data["odometer_log"] = []
    return data


def new_id() -> str:
    """Return a short unique record id."""
    return uuid.uuid4().hex[:12]


def parse_date(value: Any) -> date | None:
    """Parse a date from a date, datetime or ISO-like string."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def add_months(start: date, months: int) -> date:
    """Add calendar months, clamping the day to the month length."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sort_key(record: dict[str, Any]) -> tuple[str, float]:
    return (str(record.get("date") or ""), _num(record.get("odometer")) or 0.0)


def latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most recent record by date then odometer."""
    return max(records, key=_sort_key) if records else None


# --------------------------------------------------------------------------- odometer


def record_odometer(
    data: dict[str, Any], km: float, when: date, source: str
) -> bool:
    """Add an odometer reading (one per day per source). Return True if changed."""
    log: list[dict[str, Any]] = data.setdefault("odometer_log", [])
    iso = when.isoformat()
    for reading in reversed(log):
        if reading["date"] == iso and reading.get("source") == source:
            if reading["km"] == km:
                return False
            reading["km"] = km
            return True
        if reading["date"] < iso:
            break
    log.append({"date": iso, "km": km, "source": source})
    log.sort(key=lambda r: (r["date"], r["km"]))
    del log[:-ODOMETER_LOG_MAX]
    return True


def current_odometer(
    data: dict[str, Any], initial: float | None, linked: float | None
) -> float | None:
    """Highest known odometer from linked sensor, readings and records."""
    values: list[float] = []
    if linked is not None:
        values.append(linked)
    if initial:
        values.append(float(initial))
    values.extend(float(r["km"]) for r in data.get("odometer_log", []))
    for name in RECORD_LISTS:
        values.extend(
            v for r in data.get(name, []) if (v := _num(r.get("odometer"))) is not None
        )
    return max(values) if values else None


def km_per_day(data: dict[str, Any], today: date) -> float | None:
    """Average km per day over the recent window, from all dated odometer points."""
    points: list[tuple[date, float]] = []
    for reading in data.get("odometer_log", []):
        if (d := parse_date(reading["date"])) is not None:
            points.append((d, float(reading["km"])))
    for name in RECORD_LISTS:
        for rec in data.get(name, []):
            d = parse_date(rec.get("date"))
            km = _num(rec.get("odometer"))
            if d is not None and km is not None:
                points.append((d, km))
    cutoff = today - timedelta(days=KM_RATE_WINDOW_DAYS)
    recent = [p for p in points if p[0] >= cutoff]
    if len(recent) < 2:
        recent = sorted(points)[-10:]
    if len(recent) < 2:
        return None
    first = min(recent)
    last = max(recent)
    span = (last[0] - first[0]).days
    if span < KM_RATE_MIN_SPAN_DAYS or last[1] <= first[1]:
        return None
    return (last[1] - first[1]) / span


# --------------------------------------------------------------------------- fuel


@dataclass
class FuelStats:
    """Fuel statistics."""

    avg_consumption: float | None = None  # L/100 km over all full-to-full segments
    last_consumption: float | None = None
    last_price_per_litre: float | None = None
    last_fillup_date: str | None = None
    cost_per_km: float | None = None
    total_litres: float = 0.0
    total_cost: float = 0.0
    distance: float | None = None
    fillup_count: int = 0
    suspect_count: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)


def fuel_stats(fillups: list[dict[str, Any]]) -> FuelStats:
    """Full-tank-to-full-tank consumption and fuel cost per km."""
    stats = FuelStats(fillup_count=len(fillups))
    rows = sorted(
        (f for f in fillups if _num(f.get("odometer")) is not None),
        key=lambda f: (_num(f.get("odometer")), str(f.get("date"))),
    )
    if fillups:
        newest = latest(fillups)
        stats.last_price_per_litre = _num(newest.get("price_per_litre"))
        stats.last_fillup_date = newest.get("date")
    stats.total_litres = round(
        sum(_num(f.get("litres")) or 0 for f in fillups if not f.get("suspect")), 2
    )
    stats.suspect_count = sum(1 for f in fillups if f.get("suspect"))
    stats.total_cost = round(sum(_num(f.get("total_cost")) or 0 for f in fillups), 2)

    seg_litres = 0.0
    seg_distance = 0.0
    prev_full_km: float | None = None
    litres_since_full = 0.0
    for row in rows:
        km = _num(row["odometer"])
        litres = _num(row.get("litres")) or 0.0
        if row.get("suspect"):
            # Unknown fuel volume: the next full tank cannot be measured from here.
            prev_full_km = km if row.get("full_tank", True) else None
            litres_since_full = 0.0
            continue
        if row.get("missed_previous"):
            prev_full_km = None
            litres_since_full = 0.0
        litres_since_full += litres
        if row.get("full_tank", True):
            if prev_full_km is not None and km > prev_full_km:
                distance = km - prev_full_km
                consumption = litres_since_full / distance * 100
                seg_litres += litres_since_full
                seg_distance += distance
                stats.last_consumption = round(consumption, 2)
                stats.history.append(
                    {"date": row.get("date"), "odometer": km, "l_per_100km": round(consumption, 2)}
                )
            prev_full_km = km
            litres_since_full = 0.0
    if seg_distance > 0:
        stats.avg_consumption = round(seg_litres / seg_distance * 100, 2)

    if len(rows) >= 2:
        distance = _num(rows[-1]["odometer"]) - _num(rows[0]["odometer"])
        # The first fill-up's fuel was burnt before tracking started.
        cost = sum(_num(r.get("total_cost")) or 0 for r in rows[1:] if not r.get("suspect"))
        if distance > 0:
            stats.distance = distance
            stats.cost_per_km = round(cost / distance, 3)
    stats.history = stats.history[-20:]
    return stats


# --------------------------------------------------------------------------- costs


def record_cost(name: str, record: dict[str, Any]) -> float:
    """Cost of a record, whatever list it lives in."""
    key = {"fillups": "total_cost", "expenses": "amount"}.get(name, "cost")
    return _num(record.get(key)) or 0.0


def cost_summary(data: dict[str, Any], today: date) -> dict[str, Any]:
    """Spend per category for this month, this year and in total."""
    month_prefix = today.strftime("%Y-%m")
    year_prefix = today.strftime("%Y")
    by_category: dict[str, float] = {}
    month_total = year_total = total = fuel_month = 0.0
    for name in RECORD_LISTS:
        for rec in data.get(name, []):
            cost = record_cost(name, rec)
            if not cost:
                continue
            day = str(rec.get("date") or "")
            total += cost
            if day.startswith(year_prefix):
                year_total += cost
                by_category[name] = round(by_category.get(name, 0.0) + cost, 2)
            if day.startswith(month_prefix):
                month_total += cost
                if name == "fillups":
                    fuel_month += cost
    return {
        "month": round(month_total, 2),
        "year": round(year_total, 2),
        "total": round(total, 2),
        "fuel_month": round(fuel_month, 2),
        "year_by_category": by_category,
    }


def running_cost_per_km(data: dict[str, Any], odometer: float | None) -> float | None:
    """All running costs over the distance tracked (lifetime)."""
    fills = sorted(
        (f for f in data.get("fillups", []) if _num(f.get("odometer")) is not None),
        key=lambda f: _num(f["odometer"]),
    )
    points: list[float] = [float(r["km"]) for r in data.get("odometer_log", [])]
    for name in RECORD_LISTS:
        points.extend(
            v for r in data.get(name, []) if (v := _num(r.get("odometer"))) is not None
        )
    if odometer is not None:
        points.append(odometer)
    if len(points) < 2:
        return None
    distance = max(points) - min(points)
    if distance <= 0:
        return None
    total = 0.0
    for name in RECORD_LISTS:
        for rec in data.get(name, []):
            if name == "fillups" and fills and rec is fills[0]:
                continue
            total += record_cost(name, rec)
    return round(total / distance, 3)


# --------------------------------------------------------------------------- due items


@dataclass
class DueItem:
    """Something that needs doing by a km reading and/or a date."""

    key: str
    category: str  # maintenance | part | document
    last_date: str | None = None
    last_km: float | None = None
    due_km: float | None = None
    due_date: date | None = None
    status: str = STATUS_UNKNOWN
    km_remaining: float | None = None
    days_remaining: int | None = None
    estimated_date: date | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_date(self) -> date | None:
        """Earliest of the calendar due date and the km-based estimate."""
        dates = [d for d in (self.due_date, self.estimated_date) if d is not None]
        return min(dates) if dates else None

    def as_dict(self) -> dict[str, Any]:
        """Serialise for attributes and service responses."""
        return {
            "item": self.key,
            "category": self.category,
            "status": self.status,
            "last_date": self.last_date,
            "last_km": self.last_km,
            "due_km": self.due_km,
            "km_remaining": self.km_remaining,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "days_remaining": self.days_remaining,
            "estimated_date": self.estimated_date.isoformat() if self.estimated_date else None,
            **self.detail,
        }


def _evaluate(
    item: DueItem,
    odometer: float | None,
    today: date,
    rate: float | None,
    soon_km: float,
    soon_days: int,
) -> DueItem:
    if item.due_km is None and item.due_date is None:
        item.status = STATUS_UNKNOWN
        return item
    overdue = soon = False
    if item.due_km is not None and odometer is not None:
        item.km_remaining = round(item.due_km - odometer, 0)
        overdue |= item.km_remaining <= 0
        soon |= item.km_remaining <= soon_km
        if rate and item.km_remaining > 0:
            item.estimated_date = today + timedelta(days=int(item.km_remaining / rate))
        elif item.km_remaining <= 0:
            item.estimated_date = today
    if item.due_date is not None:
        item.days_remaining = (item.due_date - today).days
        overdue |= item.days_remaining <= 0
        soon |= item.days_remaining <= soon_days
    item.status = STATUS_OVERDUE if overdue else STATUS_DUE_SOON if soon else STATUS_OK
    return item


def _interval_item(
    key: str,
    category: str,
    record: dict[str, Any] | None,
    interval_km: float | None,
    interval_months: int | None,
) -> DueItem:
    item = DueItem(key=key, category=category)
    if record is None:
        return item
    item.last_date = record.get("date")
    item.last_km = _num(record.get("odometer"))
    done = parse_date(record.get("date"))
    if interval_km and item.last_km is not None:
        item.due_km = item.last_km + float(interval_km)
    if interval_months and done is not None:
        item.due_date = add_months(done, int(interval_months))
    return item


def due_items(
    data: dict[str, Any],
    options: dict[str, Any],
    odometer: float | None,
    today: date,
) -> list[DueItem]:
    """Build every maintenance, part and document item with its status."""
    rate = km_per_day(data, today)
    soon_km = float(options[CONF_DUE_SOON_KM])
    soon_days = int(options[CONF_DUE_SOON_DAYS])
    items: list[DueItem] = []

    # Service (overrides from the workshop win)
    service = latest(data.get("services", []))
    item = _interval_item(
        ITEM_SERVICE,
        "maintenance",
        service,
        options[CONF_SERVICE_INTERVAL_KM],
        options[CONF_SERVICE_INTERVAL_MONTHS],
    )
    if service:
        if _num(service.get("next_service_km")):
            item.due_km = _num(service["next_service_km"])
        if parse_date(service.get("next_service_date")):
            item.due_date = parse_date(service["next_service_date"])
        item.detail = {
            "service_type": service.get("service_type"),
            "workshop": service.get("workshop"),
            "cost": _num(service.get("cost")),
        }
    items.append(item)

    # Oil: latest oil change or service that included one
    oil_sources = list(data.get("oil_changes", [])) + [
        s for s in data.get("services", []) if s.get("includes_oil_change", True)
    ]
    items.append(
        _interval_item(
            ITEM_OIL,
            "maintenance",
            latest(oil_sources),
            options[CONF_OIL_INTERVAL_KM],
            options[CONF_OIL_INTERVAL_MONTHS],
        )
    )

    # Tyres
    tyres = data.get("tyres", [])
    rotation = latest([t for t in tyres if t.get("action") in ("new_set", "rotation")])
    items.append(
        _interval_item(
            ITEM_TYRE_ROTATION, "maintenance", rotation, options[CONF_TYRE_ROTATION_KM], None
        )
    )
    new_set = latest([t for t in tyres if t.get("action") == "new_set"])
    tyre_item = _interval_item(ITEM_TYRES, "maintenance", new_set, options[CONF_TYRE_MAX_KM], None)
    if new_set:
        born = parse_date(new_set.get("dot_date")) or parse_date(new_set.get("date"))
        if born:
            tyre_item.due_date = add_months(born, int(options[CONF_TYRE_MAX_AGE_YEARS]) * 12)
        checks = [t for t in tyres if _num(t.get("tread_mm")) is not None]
        last_check = latest(checks)
        tyre_item.detail = {
            "brand": new_set.get("brand"),
            "size": new_set.get("size"),
            "km_on_set": round(odometer - tyre_item.last_km, 0)
            if odometer is not None and tyre_item.last_km is not None
            else None,
            "tread_mm": _num(last_check.get("tread_mm")) if last_check else None,
        }
        # Legal minimum in SA is 1 mm; flag replacement at 1.6 mm.
        if last_check and (_num(last_check.get("tread_mm")) or 99) <= 1.6:
            tyre_item.due_date = parse_date(last_check.get("date")) or today
    items.append(tyre_item)

    # Parts
    for part, (default_km, default_months) in PARTS.items():
        record = latest([p for p in data.get("parts", []) if p.get("part") == part])
        interval_km = default_km
        interval_months = default_months
        if record is not None:
            if _num(record.get("interval_km")) is not None:
                interval_km = _num(record["interval_km"]) or None
            if _num(record.get("interval_months")) is not None:
                interval_months = int(_num(record["interval_months"])) or None
        part_item = _interval_item(part, "part", record, interval_km, interval_months)
        if record is not None:
            part_item.detail = {"cost": _num(record.get("cost")), "notes": record.get("notes")}
        items.append(part_item)

    # Documents: latest expiry per document type
    for document in DOCUMENTS:
        record = latest([d for d in data.get("documents", []) if d.get("document") == document])
        doc_item = DueItem(key=document, category="document")
        if record is not None:
            doc_item.last_date = record.get("date")
            doc_item.due_date = parse_date(record.get("expiry_date"))
            doc_item.detail = {
                "reference": record.get("reference"),
                "cost": _num(record.get("cost")),
            }
        items.append(doc_item)

    return [_evaluate(i, odometer, today, rate, soon_km, soon_days) for i in items]


def next_due(items: list[DueItem]) -> DueItem | None:
    """The known item that falls due first."""
    known = [i for i in items if i.status != STATUS_UNKNOWN and i.effective_date is not None]
    if not known:
        known = [i for i in items if i.status != STATUS_UNKNOWN]
        return min(known, key=lambda i: i.km_remaining or 0) if known else None
    return min(known, key=lambda i: i.effective_date)


# --------------------------------------------------------------------------- summary


def summarize(
    data: dict[str, Any],
    options: dict[str, Any],
    initial_odometer: float | None,
    linked_odometer: float | None,
    today: date,
) -> dict[str, Any]:
    """Everything the entities show, computed in one pass."""
    odometer = current_odometer(data, initial_odometer, linked_odometer)
    fuel = fuel_stats(data.get("fillups", []))
    items = due_items(data, options, odometer, today)
    return {
        "odometer": odometer,
        "km_per_day": (round(r, 1) if (r := km_per_day(data, today)) else None),
        "fuel": fuel,
        "costs": cost_summary(data, today),
        "running_cost_per_km": running_cost_per_km(data, odometer),
        "items": {i.key: i for i in items},
        "next_due": next_due(items),
        "attention": [
            i for i in items if i.status in (STATUS_DUE_SOON, STATUS_OVERDUE)
        ],
        "counts": {name: len(data.get(name, [])) for name in RECORD_LISTS},
    }


# --------------------------------------------------------------------------- Fuelio import


def _sections(text: str) -> dict[str, list[dict[str, str]]]:
    """Split a Fuelio CSV export into its '## Section' tables."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.lstrip("\ufeff").splitlines():
        stripped = line.strip().strip('"').strip()
        if stripped.startswith("##"):
            current = stripped.lstrip("#").strip().lower()
            sections[current] = []
            continue
        if current is not None and line.strip():
            sections[current].append(line)
    tables: dict[str, list[dict[str, str]]] = {}
    for name, lines in sections.items():
        reader = csv.DictReader(io.StringIO("\n".join(lines)))
        tables[name] = [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader
        ]
    return tables


def _col(row: dict[str, str], *names: str) -> str:
    """Value of the first column whose header starts with one of the names."""
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    for name in names:
        for key, value in lowered.items():
            if key.startswith(name.lower()):
                return value
    return ""


_COST_CATEGORY_MAP = {
    "service": "services",
    "maintenance": "services",
    "tyre": "tyres",
    "tire": "tyres",
    "insurance": "insurance",
    "registration": "licence",
    "licen": "licence",
    "toll": "tolls",
    "parking": "parking",
    "wash": "wash",
    "fine": "fine",
    "repair": "repair",
    "financ": "finance",
    "leas": "finance",
}


def parse_fuelio_csv(text: str) -> dict[str, list[dict[str, Any]]]:
    """Convert a Fuelio CSV export (metric) into logbook records."""
    tables = _sections(text)
    fillups: list[dict[str, Any]] = []
    for row in tables.get("log", []):
        day = parse_date(_col(row, "Data", "Date"))
        odo = _num(_col(row, "Odo"))
        litres = _num(_col(row, "Fuel (", "Fuel"))
        if day is None or odo is None or not litres:
            continue
        total = _num(_col(row, "Price"))
        per_litre = _num(_col(row, "VolumePrice"))
        if per_litre is None and total:
            per_litre = round(total / litres, 3)
        if total is None and per_litre:
            total = round(per_litre * litres, 2)
        # Typos (e.g. 925 L instead of 92.5 L) or a zero price would wreck the stats:
        # keep the record but exclude it from consumption/cost maths.
        suspect = litres > MAX_SANE_LITRES or not total
        fillups.append(
            {
                "suspect": suspect,
                "date": day.isoformat(),
                "odometer": odo,
                "litres": litres,
                "total_cost": total,
                "price_per_litre": per_litre,
                "full_tank": _col(row, "Full") not in ("0", "false", "False"),
                "missed_previous": _col(row, "Missed") in ("1", "true", "True"),
                "station": _col(row, "City"),
                "notes": _col(row, "Notes"),
                "source": "fuelio",
                "external_id": _col(row, "UniqueId") or None,
            }
        )

    categories = {
        _col(row, "CostTypeID", "IdCategory"): _col(row, "Name")
        for row in tables.get("costcategories", [])
    }
    services: list[dict[str, Any]] = []
    tyres: list[dict[str, Any]] = []
    expenses: list[dict[str, Any]] = []
    for row in tables.get("costs", []):
        if _col(row, "isTemplate") == "1" or _col(row, "isIncome") == "1":
            continue
        day = parse_date(_col(row, "Date"))
        amount = _num(_col(row, "Cost"))
        if day is None or amount is None:
            continue
        category_name = categories.get(_col(row, "CostTypeID"), "")
        title = _col(row, "CostTitle")
        notes = " - ".join(v for v in (title, _col(row, "Notes")) if v)
        odo = _num(_col(row, "Odo")) or None
        external = _col(row, "UniqueId") or None
        target = "other"
        lowered = f"{category_name} {title}".lower()
        for needle, mapped in _COST_CATEGORY_MAP.items():
            if needle in lowered:
                target = mapped
                break
        base = {"date": day.isoformat(), "odometer": odo, "notes": notes, "source": "fuelio",
                "external_id": external}
        if target == "services":
            services.append({**base, "cost": amount, "service_type": "other",
                             "includes_oil_change": "oil" in lowered or "service" in lowered})
        elif target == "tyres":
            tyres.append({**base, "cost": amount, "action": "new_set" if "new" in lowered else "repair"})
        else:
            expenses.append({**base, "amount": amount, "category": target})
    return {"fillups": fillups, "services": services, "tyres": tyres, "expenses": expenses}


def merge_import(
    data: dict[str, Any], imported: dict[str, list[dict[str, Any]]]
) -> dict[str, int]:
    """Add imported records, skipping ones already present. Return counts added."""
    added: dict[str, int] = {}
    for name, records in imported.items():
        existing = data.setdefault(name, [])
        seen_ext = {r.get("external_id") for r in existing if r.get("external_id")}
        seen_key = {(r.get("date"), _num(r.get("odometer")), record_cost(name, r)) for r in existing}
        count = 0
        for rec in records:
            key = (rec.get("date"), _num(rec.get("odometer")), record_cost(name, rec))
            if (rec.get("external_id") and rec["external_id"] in seen_ext) or key in seen_key:
                continue
            existing.append({"id": new_id(), **rec})
            seen_key.add(key)
            if rec.get("external_id"):
                seen_ext.add(rec["external_id"])
            count += 1
        added[name] = count
    return added
