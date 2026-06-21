from fzastro_ai.benchmarks import grade_benchmark_response

IMAGE_SCALE_PROMPT = (
    "A telescope has 800 mm focal length and a camera with 3.76 micron pixels. "
    "Estimate the image scale in arcseconds per pixel using 206.265 * pixel_size / focal_length. "
    "Show the formula and result."
)


JSON_PROMPT = (
    "Create JSON with constraints: top-level keys 'constraint_check', 'valid_observations', "
    "'invalid_observations'. Each observation must have 'catalog_id', 'ra_hms', 'dec_dms', "
    "'mag', 'surface_brightness', 'best_filter'. Minimum 3 valid, 2 invalid with 'reason' "
    "field. Return only JSON."
)


def test_benchmark_engine_grades_numeric_accuracy_and_trust():
    result = grade_benchmark_response(
        preset_name="Math Reasoning",
        prompt=IMAGE_SCALE_PROMPT,
        response="image scale = 206.265 * 3.76 / 800 = 0.970 arcsec/pixel",
        max_tokens=256,
        model="qwen3.6:35b",
        base_url="http://localhost:11434/v1",
        repeat_total=3,
        heuristic_score=80,
        heuristic_notes=["legacy heuristic check"],
    )

    assert result["benchmark_engine_version"] == "2.0"
    assert result["accuracy_score"] == 100.0
    assert result["quality_score"] >= 95.0
    assert result["trust_score"] >= 85.0
    assert result["grader_results"][0]["passed"] is True
    assert result["prompt_hash"]
    assert result["response_hash"]


def test_benchmark_engine_grades_json_instruction_following():
    result = grade_benchmark_response(
        preset_name="Instruction Following",
        prompt=JSON_PROMPT,
        response=(
            '{"constraint_check":"pass",'
            '"valid_observations":['
            '{"catalog_id":"NGC7001","ra_hms":"20:54:05","dec_dms":"+63:09:01",'
            '"mag":5.0,"surface_brightness":28.0,"best_filter":"OIII"},'
            '{"catalog_id":"NGC6563","ra_hms":"17:53:18","dec_dms":"+13:42:18",'
            '"mag":7.0,"surface_brightness":30.0,"best_filter":"Halpha"},'
            '{"catalog_id":"NGC1976","ra_hms":"05:34:55","dec_dms":"+22:12:07",'
            '"mag":4.0,"surface_brightness":4.0,"best_filter":"RGB"}'
            "],"
            '"invalid_observations":['
            '{"catalog_id":"NGC0001","ra_hms":"00:00:00","dec_dms":"00:00:00",'
            '"mag":10.0,"surface_brightness":50.0,"best_filter":"L","reason":"below horizon"},'
            '{"catalog_id":"NGC0002","ra_hms":"12:00:00","dec_dms":"00:00:00",'
            '"mag":12.0,"surface_brightness":55.0,"best_filter":"V","reason":"too close to sun"}'
            "]}"
        ),
        max_tokens=512,
        model="test-model",
        base_url="http://localhost:11434/v1",
        repeat_total=2,
        heuristic_score=90,
    )

    assert result["instruction_score"] == 100.0
    assert result["accuracy_score"] == 100.0
    assert all(check["passed"] for check in result["grader_results"])
