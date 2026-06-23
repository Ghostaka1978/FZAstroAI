from __future__ import annotations

from fzastro_ai.astro_tools import engine
from fzastro_ai.astro_tools.fzastro import imagefetch


def test_fast_lookup_html_surfaces_enriched_result_details(monkeypatch):
    monkeypatch.setattr(
        engine,
        "_lookup_galactic_coords",
        lambda _ra, _dec: (121.1743, -21.5733),
    )
    info = {
        "display_name": "M 31",
        "object_type": "Galaxy",
        "ra_deg": 10.6847083,
        "dec_deg": 41.26875,
        "pmra_masyr": 0.0,
        "pmdec_masyr": 0.0,
        "redshift": -0.001001,
        "radial_velocity_kms": -300.0,
        "distance_pc": 765000.0,
        "distance_method": "NED-D (median)",
        "distance_reference": "2020ApJ",
        "mag_B": 4.36,
        "mag_V": 3.44,
        "mag_G": 3.90,
        "morphology": "SA(s)b",
        "oid": "12345",
    }

    html = engine._format_fast_lookup_html(
        "M31", info, ["M 31", "NGC 224"], "CDS Sesame"
    )

    assert "Coordinates" in html
    assert "RA HMS" in html
    assert "Dec DMS" in html
    assert "Galactic l" in html
    assert "Motion / velocity" in html
    assert "Physical details" in html
    assert "Morphology" in html
    assert "SA(s)b" in html
    assert "Distance modulus" in html
    assert "Photometry" in html
    assert "Color B-V" in html
    assert "Abs V" in html
    assert "Catalog IDs" in html
    assert "SIMBAD OID" in html
    assert "Alias count" in html


def test_lookup_coordinate_formatters_are_observer_friendly():
    assert engine._lookup_ra_hms(10.6847083) == "00h 42m 44.33s"
    assert engine._lookup_dec_dms(41.26875) == "+41° 16' 07.50\""
    assert engine._lookup_dec_dms(-5.5) == "-05° 30' 00.00\""


def test_lookup_alias_line_renders_every_alias_by_default():
    aliases = [f"CAT {idx}" for idx in range(1, 18)]

    html = engine._lookup_alias_line(aliases)

    assert "CAT 1" in html
    assert "CAT 17" in html
    assert "+" not in html
    assert "more" not in html


def test_fast_lookup_html_shows_all_aliases_not_preview(monkeypatch):
    monkeypatch.setattr(
        engine, "_lookup_galactic_coords", lambda _ra, _dec: (None, None)
    )
    aliases = [f"ALIAS {idx}" for idx in range(1, 18)]
    info = {
        "display_name": "Example Object",
        "object_type": "Galaxy",
        "ra_deg": 1.0,
        "dec_deg": 2.0,
        "oid": "999",
    }

    html = engine._format_fast_lookup_html("Example", info, aliases, "SIMBAD TAP")

    assert "Alias count" in html
    assert "17" in html
    assert "ALIAS 1" in html
    assert "ALIAS 17" in html
    assert "+5 more" not in html


def test_simbad_alias_fetch_uses_no_preview_limit(monkeypatch):
    seen = {}

    def fake_tap(adql: str, timeout: int):
        seen["adql"] = adql
        return [{"id": "M 31"}, {"ID": "NGC 224"}, {"id": "NAME Andromeda Galaxy"}]

    monkeypatch.setattr(engine, "_simbad_tap_csv", fake_tap)

    aliases = engine._fetch_simbad_aliases_for_oid("123", timeout=6)

    assert aliases == ["M 31", "NGC 224", "NAME Andromeda Galaxy"]
    assert "FROM ident" in seen["adql"]
    assert "TOP" not in seen["adql"].upper()
    assert "ORDER BY id" in seen["adql"]


def test_fast_lookup_html_surfaces_all_simbad_basic_and_measurement_fields(monkeypatch):
    monkeypatch.setattr(
        engine, "_lookup_galactic_coords", lambda _ra, _dec: (None, None)
    )
    info = {
        "display_name": "Example Galaxy",
        "object_type": "Galaxy",
        "ra_deg": 10.0,
        "dec_deg": 20.0,
        "distance_pc": 1234.0,
        "distance_method": "NED-D (median)",
        "distance_reference": "ladder-ref",
        "simbad_basic_fields": {
            "main_id": "Example Galaxy",
            "otype": "G",
            "rvz_redshift": "0.0123",
            "custom_extra_field": "raw basic value",
        },
        "simbad_measurements": {
            "mesDistance": {
                "label": "Distance measurements",
                "row_limit": 200,
                "rows": [
                    {
                        "dist": "1.23",
                        "unit": "Mpc",
                        "method": "TRGB",
                        "bibcode": "2024A&A...000A...1X",
                    }
                ],
            },
            "mesVar": {
                "label": "Variability measurements",
                "row_limit": 200,
                "rows": [{"period": "12.3", "varType": "Cepheid"}],
            },
        },
    }

    html = engine._format_fast_lookup_html(
        "Example", info, ["Example Galaxy"], "SIMBAD TAP"
    )

    assert "SIMBAD basic row · all fields" in html
    assert "Custom extra field" in html
    assert "raw basic value" in html
    assert "SIMBAD measurement tables · all fetched rows" in html
    assert "Distance measurements" in html
    assert "mesDistance" in html
    assert "TRGB" in html
    assert "2024A&amp;A...000A...1X" in html
    assert "Variability measurements" in html
    assert "Cepheid" in html
    assert "Distance values shown here do not replace" in html


def test_simbad_research_enrichment_does_not_touch_distance_ladder_fields(monkeypatch):
    calls = []

    def fake_tap(adql: str, timeout: int):
        calls.append(adql)
        if "FROM basic" in adql:
            return [
                {
                    "main_id": "Example Galaxy",
                    "otype": "G",
                    "rvz_redshift": "0.01",
                    "rvz_radvel": "3000",
                }
            ]
        if "FROM ident" in adql:
            return [{"id": "Example Galaxy"}, {"id": "NGC 9999"}]
        if "FROM mesDistance" in adql:
            return [
                {
                    "dist": "999",
                    "unit": "Mpc",
                    "method": "Should stay display-only",
                    "bibcode": "2099Fake",
                }
            ]
        return []

    monkeypatch.setattr(engine, "_simbad_tap_csv", fake_tap)
    monkeypatch.setattr(
        engine,
        "_simbad_research_tables",
        lambda: [("mesDistance", "Distance measurements")],
    )

    info = {
        "oid": "123",
        "display_name": "Original",
        "object_type": "Galaxy",
        "ra_deg": 1.0,
        "dec_deg": 2.0,
        "distance_pc": 765000.0,
        "distance_method": "NED-D (median)",
        "distance_reference": "ladder-ref",
    }

    enriched, aliases = engine._enrich_fast_object_details_via_tap(info, [], timeout=4)

    assert enriched["distance_pc"] == 765000.0
    assert enriched["distance_method"] == "NED-D (median)"
    assert enriched["distance_reference"] == "ladder-ref"
    assert (
        enriched["simbad_measurements"]["mesDistance"]["rows"][0]["method"]
        == "Should stay display-only"
    )
    assert enriched["_simbad_research_enriched"] is True
    assert aliases == ["Example Galaxy", "NGC 9999"]
    assert any("FROM mesDistance" in call for call in calls)


def test_fast_lookup_metadata_carries_simbad_raw_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine, "_load_fast_lookup_cache", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        engine, "_store_fast_lookup_cache", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        engine,
        "_simbad_fast_lookup_via_sesame",
        lambda *_args, **_kwargs: (
            {
                "oid": "123",
                "display_name": "Example",
                "object_type": "Galaxy",
                "ra_deg": 1.0,
                "dec_deg": 2.0,
                "distance_pc": 10.0,
                "distance_method": "existing ladder",
            },
            ["Example"],
        ),
    )
    monkeypatch.setattr(
        engine,
        "_enrich_fast_object_details_via_tap",
        lambda info, aliases, **_kwargs: (
            {
                **info,
                "simbad_basic_fields": {"custom_field": "abc"},
                "simbad_measurements": {
                    "mesVar": {
                        "label": "Variability measurements",
                        "row_limit": 200,
                        "rows": [{"period": "1.2"}],
                    }
                },
                "_simbad_details_enriched": True,
                "_simbad_aliases_complete": True,
                "_simbad_research_enriched": True,
            },
            aliases,
        ),
    )

    text, metadata = engine._fast_lookup_object_text("Example", timeout=4)

    assert "SIMBAD basic row" in text
    assert metadata["simbad_basic_fields"] == {"custom_field": "abc"}
    assert metadata["simbad_measurements"]["mesVar"]["rows"][0]["period"] == "1.2"
    assert metadata["distance_method"] == "existing ladder"


def test_lookup_panels_are_marked_for_dialog_tabs(monkeypatch):
    monkeypatch.setattr(
        engine, "_lookup_galactic_coords", lambda _ra, _dec: (None, None)
    )
    info = {
        "display_name": "Example Object",
        "object_type": "Galaxy",
        "ra_deg": 1.0,
        "dec_deg": 2.0,
        "oid": "999",
        "simbad_basic_fields": {"main_id": "Example Object"},
    }

    html = engine._format_fast_lookup_html("Example", info, ["ALIAS 1"], "SIMBAD TAP")

    assert 'class="lookup-panel"' in html
    assert 'data-lookup-title="Coordinates"' in html
    assert 'data-lookup-title="Aliases"' in html
    assert 'data-lookup-title="SIMBAD basic row · all fields"' in html


def test_solar_system_reference_image_falls_back_without_real_source(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(engine, "APP_DIR", tmp_path)
    monkeypatch.setattr(
        engine,
        "_fetch_solar_system_real_reference_image",
        lambda *_args, **_kwargs: None,
    )

    result = engine._generate_solar_system_reference_image(
        "Mars", width=640, height=480
    )

    assert result.success is True
    assert result.files
    assert result.metadata["reference_image_kind"] == "planet"
    assert result.metadata["reference_image_source"] == "generated fallback"
    assert result.files[0].endswith("solar_ref_mars_640x480.png")
    assert __import__("pathlib").Path(result.files[0]).exists()


def test_solar_system_reference_image_prefers_real_bundled_source(
    tmp_path, monkeypatch
):
    ref_dir = tmp_path / "resources" / "astro_reference_images"
    ref_dir.mkdir(parents=True)
    real_image = ref_dir / "mars.jpg"
    real_image.write_bytes(b"\xff\xd8\xfffake-jpeg")
    monkeypatch.setattr(engine, "SOLAR_SYSTEM_REFERENCE_DIR", ref_dir)

    result = engine._fetch_solar_system_real_reference_image("Mars", "planet")

    assert result is not None
    assert result.success is True
    assert result.files == [str(real_image)]
    assert result.metadata["reference_image_source"] == "bundled real image"


def test_solar_system_reference_kind_includes_moons():
    assert engine._solar_system_reference_kind("Europa") == "moon"
    assert engine._solar_system_reference_kind("Moon") == "moon"
    assert engine._solar_system_reference_kind("Jupiter") == "planet"
    assert engine._solar_system_reference_kind("ISS") == ""


def test_fast_lookup_html_has_links_panel_and_keeps_raw_data_in_all_data(monkeypatch):
    monkeypatch.setattr(
        engine, "_lookup_galactic_coords", lambda _ra, _dec: (None, None)
    )
    info = {
        "display_name": "M 31",
        "object_type": "Galaxy",
        "ra_deg": 10.6847083,
        "dec_deg": 41.26875,
        "oid": "12345",
        "simbad_basic_fields": {"main_id": "M 31"},
        "simbad_measurements": {
            "mesDistance": {
                "label": "Distance measurements",
                "row_limit": 200,
                "rows": [{"dist": "765", "unit": "kpc"}],
            }
        },
    }

    html = engine._format_fast_lookup_html(
        "M31", info, ["M 31", "NGC 224"], "SIMBAD TAP"
    )

    assert 'data-lookup-title="Links"' in html
    assert "SIMBAD object page" in html
    assert "NASA/IPAC NED by name" in html
    assert "Aladin Lite sky atlas" in html
    assert "SIMBAD measurement tables · all fetched rows" in html


def test_lookup_survey_presets_include_narrowband_halpha():
    presets = engine.lookup_survey_presets()
    labels = "\n".join(str(item.get("label") or "") for item in presets)
    surveys = "\n".join(str(item.get("survey") or "") for item in presets)

    assert "Pan-STARRS" in labels
    assert "H-alpha" in labels
    assert "FinkbeinerHalpha" in surveys
    assert "SHASSA" in surveys


def test_halpha_survey_presets_are_explicit_about_coverage():
    presets = [
        item
        for item in imagefetch.lookup_survey_presets()
        if "H-alpha" in str(item.get("label") or "")
    ]

    assert [item["survey"] for item in presets[-3:]] == [
        imagefetch.FINKBEINER_HALPHA_SURVEY,
        imagefetch.VTSS_HALPHA_SURVEY,
        imagefetch.SHASSA_HALPHA_SURVEY,
    ]
    assert "full" in presets[-3]["label"].casefold()
    assert "north" in presets[-2]["label"].casefold()
    assert "south" in presets[-1]["label"].casefold()
    assert "WHAM" in presets[-3]["coverage"]
    assert "-15" in presets[-2]["coverage"]
    assert "+15" in presets[-1]["coverage"]


def test_halpha_survey_chain_respects_declination_coverage():
    southern_chain = imagefetch._survey_chain(imagefetch.VTSS_HALPHA_SURVEY, dec=-16.5)
    northern_chain = imagefetch._survey_chain(imagefetch.SHASSA_HALPHA_SURVEY, dec=41.0)

    assert imagefetch.VTSS_HALPHA_SURVEY not in southern_chain
    assert imagefetch.SHASSA_HALPHA_SURVEY in southern_chain
    assert imagefetch.SHASSA_HALPHA_SURVEY not in northern_chain
    assert imagefetch.VTSS_HALPHA_SURVEY in northern_chain
    assert imagefetch.FINKBEINER_HALPHA_SURVEY in southern_chain
    assert imagefetch.FINKBEINER_HALPHA_SURVEY in northern_chain


def test_hips_request_uses_icrs_coordinates_for_halpha(monkeypatch):
    captured = {}

    class DummyResponse:
        status_code = 200
        content = b"fake-jpeg"
        headers = {"content-type": "image/jpeg"}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = dict(params)
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr(imagefetch.requests, "get", fake_get)

    blob = imagefetch._hips_request(
        imagefetch.FINKBEINER_HALPHA_SURVEY,
        ra=275.196,
        dec=-16.172,
        fov_deg=1.0,
        w=256,
        h=256,
        rotation_angle=0.0,
        timeout=5,
    )

    assert blob == b"fake-jpeg"
    assert captured["params"]["hips"] == imagefetch.FINKBEINER_HALPHA_SURVEY
    assert captured["params"]["coordsys"] == "icrs"
    assert captured["params"]["format"] == "jpg"


def test_lookup_object_passes_selected_survey_to_sky_image(monkeypatch):
    calls = {}

    monkeypatch.setattr(
        engine,
        "_fast_lookup_object_text",
        lambda *_args, **_kwargs: (
            '<section class="lookup-panel" data-lookup-title="Coordinates"><div>Coordinates</div></section>',
            {
                "fast_lookup": True,
                "ra_deg": 10.0,
                "dec_deg": 20.0,
                "object_type": "Galaxy",
            },
        ),
    )

    def fake_fetch_sky_image(ra, dec, **kwargs):
        calls.update(kwargs)
        return engine.AstroToolResult(
            title="Sky image",
            text="ok",
            files=["/tmp/fake.jpg"],
            success=True,
            metadata={"survey": kwargs.get("survey")},
        )

    monkeypatch.setattr(engine, "fetch_sky_image", fake_fetch_sky_image)

    result = engine.lookup_object(
        "M31", survey="https://alasky.cds.unistra.fr/FinkbeinerHalpha/"
    )

    assert result.success is True
    assert calls["survey"] == "https://alasky.cds.unistra.fr/FinkbeinerHalpha/"
    assert (
        result.metadata["survey_requested"]
        == "https://alasky.cds.unistra.fr/FinkbeinerHalpha/"
    )
    assert (
        result.metadata["survey"] == "https://alasky.cds.unistra.fr/FinkbeinerHalpha/"
    )
