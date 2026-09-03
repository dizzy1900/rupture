"""Lattice construction and binning."""

from __future__ import annotations

import numpy as np
import pytest

from rupture.adapters.forecasting.grid import (
    build_lattice,
    magnitude_bin_indices,
    shape_coords_lat_lon,
)
from rupture.domain import Region, TectonicSetting


def test_rectangle_lattice_covers_every_cell(region: Region) -> None:
    lattice = build_lattice(region)
    assert lattice.n_cells == 80 * 55
    assert lattice.origins[0] == (-122.0, 32.0)
    idx = lattice.cell_indices([-121.95, -114.05, -122.5], [32.05, 37.45, 33.0])
    assert idx[0] == 0
    assert idx[1] == lattice.n_cells - 1
    assert idx[2] == -1, "outside the lattice"


def test_triangle_keeps_only_cells_whose_centre_is_inside() -> None:
    tri = Region(
        id="tri",
        name="triangle",
        polygon=((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
        depth_max_km=30.0,
        tectonic_setting=TectonicSetting.OTHER,
        target_min_magnitude=4.0,
    )
    lattice = build_lattice(tri)
    assert 0 < lattice.n_cells < 100
    for lon, lat in lattice.origins:
        assert lon + 0.05 + lat + 0.05 < 1.0 + 1e-9
    assert shape_coords_lat_lon(tri)[0] == [0.0, 0.0]
    assert shape_coords_lat_lon(tri)[1] == [0.0, 1.0], "[lat, lon] order for the etas package"


def test_magnitude_bins_are_left_closed_with_open_top(region: Region) -> None:
    edges = region.magnitude_bin_edges()
    j = magnitude_bin_indices([3.9, 3.95, 4.0, 4.049, 4.05, 9.5], edges, 0.1)
    assert j.tolist() == [-1, 0, 0, 0, 1, len(edges) - 1]
    assert np.all(magnitude_bin_indices([4.0], edges, 0.1) >= 0)


def test_degenerate_region_is_refused() -> None:
    sliver = Region(
        id="sliver",
        name="too thin for any cell centre",
        polygon=((0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01)),
        depth_max_km=30.0,
        tectonic_setting=TectonicSetting.OTHER,
        target_min_magnitude=4.0,
    )
    with pytest.raises(ValueError, match="no cell"):
        build_lattice(sliver)
