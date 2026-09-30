"""Pydantic schemas for historical databases.

A "database" groups many standalone power/voltage series ("historicals")
that all share the exact same timeline. Unlike MeasurementsData
(schemas/measurements_data.py), none of this is tied to a specific grid or
node -- each series just has a series_id (unique within its database) and a
grid_level tag (MV/LV) saying which level it's meant for.
"""

from typing import List, Optional

from pydantic import BaseModel, model_validator

from gridarena.schemas.types import GridLevel, Phase


class HistoricalValue(BaseModel):

    datetime: str
    phase: Optional[Phase] = None
    power_active: Optional[float] = None
    power_reactive: Optional[float] = None
    voltage_magnitude: Optional[float] = None
    voltage_angle: Optional[float] = None

    @model_validator(mode="after")
    def _require_power_or_voltage(self):
        if self.power_active is None and self.voltage_magnitude is None:
            raise ValueError("Each value must include power_active and/or voltage_magnitude.")
        return self


class HistoricalSeriesUpload(BaseModel):

    series_id: str
    grid_level: GridLevel
    name: Optional[str] = None
    description: Optional[str] = None
    values: List[HistoricalValue]


class HistoricalDatabaseUpload(BaseModel):

    database_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    timestamps: List[str]
    historicals: List[HistoricalSeriesUpload]

    @model_validator(mode="after")
    def _validate_shared_timeline(self):
        if not self.timestamps:
            raise ValueError("A database must declare at least one timestamp.")
        if not self.historicals:
            raise ValueError("A database must contain at least one historical (series).")

        seen_series_ids = set()
        timestamp_set = set(self.timestamps)
        for historical in self.historicals:
            if historical.series_id in seen_series_ids:
                raise ValueError(f"Duplicate series_id '{historical.series_id}' within this database.")
            seen_series_ids.add(historical.series_id)

            for value in historical.values:
                if value.datetime not in timestamp_set:
                    raise ValueError(
                        f"Series '{historical.series_id}' has a value at datetime "
                        f"'{value.datetime}', which is not in this database's declared timestamps."
                    )
        return self
