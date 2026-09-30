"""Defines the Cable data model for representing cable properties in the grid database."""

from pydantic import BaseModel


class Cable(BaseModel):

    cable_id: str
    r_imp_real: float
    r_imp_imag: float
    s_imp_real: float
    s_imp_imag: float
    t_imp_real: float
    t_imp_imag: float
    r_nom_curr: float
    s_nom_curr: float
    t_nom_curr: float
