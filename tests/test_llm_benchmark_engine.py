from fzastro_ai.benchmarks import grade_benchmark_response


IMAGE_SCALE_PROMPT = (
    "A telescope has 800 mm focal length and a camera with 3.76 micron pixels. "
    "Estimate the image scale in arcseconds per pixel using 206.265 * pixel_size / focal_length. "
    "Show the formula and result."
)


JSON_PROMPT = (
    "Create a JSON object with keys model, benchmark, metrics, and verdict. metrics must contain "
    "tokens_per_second and quality_score as numbers. Return only JSON."
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
            '{"model":"test","benchmark":"json","metrics":'
            '{"tokens_per_second":30.5,"quality_score":91},"verdict":"pass"}'
        ),
        max_tokens=256,
        model="test-model",
        base_url="http://localhost:11434/v1",
        repeat_total=2,
        heuristic_score=90,
    )

    assert result["instruction_score"] == 100.0
    assert result["accuracy_score"] == 100.0
    assert all(check["passed"] for check in result["grader_results"])
