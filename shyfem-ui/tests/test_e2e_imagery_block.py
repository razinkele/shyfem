"""The E2E browser fails third-party map imagery at once (see conftest)."""

import pytest

from tests.conftest import _is_third_party_imagery


@pytest.mark.parametrize(
    "url",
    [
        "https://ows.emodnet-bathymetry.eu/wms?SERVICE=WMS&REQUEST=GetMap&LAYERS=emodnet:mean",
        "https://tiles.basemaps.cartocdn.com/vectortiles/carto.streets/v1/7/71/40.mvt",
    ],
)
def test_map_imagery_is_blocked(url):
    assert _is_third_party_imagery(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/",
        "https://cdn.jsdelivr.net/npm/deck.gl@9/dist.min.js",
        "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        "https://fonts.googleapis.com/css2?family=Inter",
    ],
)
def test_the_app_and_its_libraries_are_not(url):
    assert not _is_third_party_imagery(url)
