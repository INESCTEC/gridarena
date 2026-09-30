"""Sparse Y-bus assembler for the PF-datagen output record group.

No tap ratio or shunt terms -- the MV schema doesn't model either, so this is
the simple case: for each in-service branch with admittance y = 1/Z,
Yii += y, Yjj += y, Yij -= y, Yji -= y.
"""

from typing import Dict, List, Tuple

from gridarena.pf_datagen.grid_loader import MVBranch


def build_ybus_entries(
    sub_branches: List[MVBranch], branch_admittances: Dict[str, complex],
) -> List[Tuple[str, str, float, float]]:
    """Returns sparse (i_node_id, j_node_id, G, B) rows for one topology
    variant's energised sub-network."""
    y_matrix: Dict[Tuple[str, str], complex] = {}

    def _add(i, j, val):
        y_matrix[(i, j)] = y_matrix.get((i, j), 0j) + val

    for b in sub_branches:
        y = branch_admittances.get(b.connection_id)
        if y is None:
            continue
        i, j = b.from_node_id, b.to_node_id
        _add(i, i, y)
        _add(j, j, y)
        _add(i, j, -y)
        _add(j, i, -y)

    return [(i, j, y.real, y.imag) for (i, j), y in y_matrix.items() if y != 0]
