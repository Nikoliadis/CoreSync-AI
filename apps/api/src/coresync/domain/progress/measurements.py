"""Body measurements.

Ten sites on one wide row rather than a tall ``(site, value)`` table. Users measure
several sites in one sitting, always read them together, and the site list is fixed — so
a wide row is one index lookup instead of ten, and adding a site is a migration we will
do once rather than a join we pay for forever (docs/03 §8).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID

from coresync.core.ids import uuid7


class MeasurementSite(StrEnum):
    """The ten sites, as column suffixes.

    Left and right are tracked separately on purpose: asymmetry is a real training
    signal, and averaging it away is how an imbalance goes unnoticed for a year.
    """

    NECK = "neck"
    CHEST = "chest"
    WAIST = "waist"
    HIPS = "hips"
    LEFT_ARM = "left_arm"
    RIGHT_ARM = "right_arm"
    LEFT_THIGH = "left_thigh"
    RIGHT_THIGH = "right_thigh"
    LEFT_CALF = "left_calf"
    RIGHT_CALF = "right_calf"

    @property
    def is_bilateral(self) -> bool:
        return self.value.startswith(("left_", "right_"))

    @property
    def mirror(self) -> MeasurementSite | None:
        """The opposite side, for asymmetry checks."""
        if self.value.startswith("left_"):
            return MeasurementSite("right_" + self.value[5:])
        if self.value.startswith("right_"):
            return MeasurementSite("left_" + self.value[6:])
        return None


# Plausible human ranges in centimetres. Wide on purpose — these exist to catch a
# transposed digit or an inches-for-centimetres mix-up, not to police body shapes.
SITE_RANGE_CM: dict[MeasurementSite, tuple[Decimal, Decimal]] = {
    MeasurementSite.NECK: (Decimal("20"), Decimal("70")),
    MeasurementSite.CHEST: (Decimal("50"), Decimal("200")),
    MeasurementSite.WAIST: (Decimal("40"), Decimal("200")),
    MeasurementSite.HIPS: (Decimal("50"), Decimal("200")),
    MeasurementSite.LEFT_ARM: (Decimal("15"), Decimal("80")),
    MeasurementSite.RIGHT_ARM: (Decimal("15"), Decimal("80")),
    MeasurementSite.LEFT_THIGH: (Decimal("25"), Decimal("110")),
    MeasurementSite.RIGHT_THIGH: (Decimal("25"), Decimal("110")),
    MeasurementSite.LEFT_CALF: (Decimal("15"), Decimal("80")),
    MeasurementSite.RIGHT_CALF: (Decimal("15"), Decimal("80")),
}


@dataclass(slots=True)
class BodyMeasurement:
    """One measurement session. Every site is optional — people measure what they track."""

    id: UUID
    user_id: UUID
    local_date: date
    sites: dict[MeasurementSite, Decimal]
    note: str | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        local_date: date,
        sites: dict[MeasurementSite, Decimal],
        note: str | None = None,
    ) -> BodyMeasurement:
        cleaned = {site: value for site, value in sites.items() if value is not None}
        if not cleaned:
            raise ValueError("a measurement must record at least one site")
        for site, value in cleaned.items():
            low, high = SITE_RANGE_CM[site]
            if not low <= value <= high:
                raise ValueError(
                    f"{site.value} of {value} cm is outside the plausible range "
                    f"{low}-{high} cm — check the units"
                )
        return cls(
            id=uuid7(),
            user_id=user_id,
            local_date=local_date,
            sites=cleaned,
            note=note,
        )

    def value_for(self, site: MeasurementSite) -> Decimal | None:
        return self.sites.get(site)

    @property
    def recorded_sites(self) -> list[MeasurementSite]:
        return [site for site in MeasurementSite if site in self.sites]

    def waist_to_hip_ratio(self) -> Decimal | None:
        """A recognised health marker, and the one derived value worth surfacing."""
        waist = self.sites.get(MeasurementSite.WAIST)
        hips = self.sites.get(MeasurementSite.HIPS)
        if waist is None or hips is None or hips == 0:
            return None
        return (waist / hips).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def asymmetry(self, site: MeasurementSite) -> Decimal | None:
        """Difference between a site and its mirror, in centimetres.

        Positive means this side is larger. Returned rather than flagged: what counts as
        a meaningful imbalance depends on the site and the person, and that judgement
        belongs to the coach in Phase 5, not to a threshold hard-coded here.
        """
        mirror = site.mirror
        if mirror is None:
            return None
        own = self.sites.get(site)
        other = self.sites.get(mirror)
        if own is None or other is None:
            return None
        return own - other
