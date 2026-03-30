"""
=============================================================================
  SIMULATO — Full Pipeline End-to-End Test
=============================================================================

Tests the complete pipeline on 30 real exam images from datasets/test-images/:

  1. Image receive (file load)
  2. Preprocessing (CLAHE + header mask)
  3. Parallel: AI query (Gemini) + layout/option detection
  4. Option mapping accuracy (A/B/C/D/E with click targets)
  5. Next/Prev button detection + position mapping
  6. Last-question detection (is_last_question flag)
  7. Token usage tracking (input/output/total per image)
  8. Per-image and aggregate timing

Metrics tracked:
  - Option detection: count, labels, click target coordinates
  - Button detection: next_button, prev_button positions + is_last_question
  - AI response: answer letter, token usage, latency
  - Parallel execution: local vs AI timing, total wall-clock
  - Errors: any failures at each stage
"""

import concurrent.futures
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from controller.capture_pipeline.image_preprocessor import ImagePreprocessor
from controller.capture_pipeline.ocr_layout_analyzer import OCRLayoutAnalyzer
from controller.capture_pipeline.exam_layout import ExamLayoutDetector


# ── Result containers ────────────────────────────────────────────────────

@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class OptionResult:
    count: int = 0
    labels: list[str] = field(default_factory=list)
    targets: dict[str, tuple[float, float]] = field(default_factory=dict)  # letter -> (nx, ny)


@dataclass
class ButtonResult:
    has_next: bool = False
    has_prev: bool = False
    next_pos: Optional[tuple[int, int, int, int]] = None  # x,y,w,h
    prev_pos: Optional[tuple[int, int, int, int]] = None
    is_last_question: bool = False


@dataclass
class ImageResult:
    filename: str = ""
    category: str = ""  # no-scroll, scroll, question-scroll, answer-and-question-scroll
    # Timing (ms)
    t_load: float = 0
    t_preprocess: float = 0
    t_layout_options: float = 0  # layout detect + option detect (single pass)
    t_ai: float = 0
    t_total_wall: float = 0     # wall-clock from start to finish
    # Parallelism
    local_processing_ms: float = 0
    parallel_saved_ms: float = 0  # how much time saved by parallelism
    # Results
    options: OptionResult = field(default_factory=OptionResult)
    buttons: ButtonResult = field(default_factory=ButtonResult)
    ai_answer: str = ""
    tokens: TokenUsage = field(default_factory=TokenUsage)
    # Errors
    errors: list[str] = field(default_factory=list)


# ── AI query with token capture ──────────────────────────────────────────

def query_ai_with_tokens(image_path: Path) -> tuple[str, TokenUsage, float]:
    """Call Gemini API and return (answer, tokens, latency_ms).
    
    This wraps the real API call so we can capture token usage from
    the response metadata.
    """
    from google import genai
    from google.genai import types
    from controller.config import GEMINI_MODEL, GCP_PROJECT_ID, GCP_LOCATION

    # Build client
    client_kwargs = {"vertexai": True}
    if GCP_PROJECT_ID:
        client_kwargs["project"] = GCP_PROJECT_ID
    if GCP_LOCATION:
        client_kwargs["location"] = GCP_LOCATION
    client = genai.Client(**client_kwargs)

    # Read image
    image_bytes = image_path.read_bytes()

    # Try answer panel crop
    panel_crop = None
    try:
        from controller.capture_pipeline.exam_layout import ExamLayoutDetector
        import cv2
        detector = ExamLayoutDetector()
        layout = detector.detect(image_path)
        if layout and layout.is_valid() and layout.answer_panel:
            img = cv2.imread(str(image_path))
            if img is not None:
                ap = layout.answer_panel
                pad_left = min(50, ap.x)
                x1, y1 = max(0, ap.x - pad_left), max(0, ap.y)
                x2, y2 = min(img.shape[1], ap.x + ap.w), min(img.shape[0], ap.y + ap.h)
                cropped = img[y1:y2, x1:x2]
                if cropped.size > 0:
                    ok, buf = cv2.imencode(".jpg", cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    if ok:
                        panel_crop = buf.tobytes()
    except Exception:
        pass

    from controller.ai_pipeline.prompt_builder import (
        SYSTEM_PROMPT, SYSTEM_PROMPT_WITH_PANEL,
        USER_PROMPT, USER_PROMPT_WITH_PANEL,
    )
    from controller.ai_pipeline.response_parser import parse_ai_response

    if panel_crop:
        system_prompt = SYSTEM_PROMPT_WITH_PANEL
        user_prompt = USER_PROMPT_WITH_PANEL
    else:
        system_prompt = SYSTEM_PROMPT
        user_prompt = USER_PROMPT

    contents = [
        user_prompt,
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
    ]
    if panel_crop:
        contents.append(types.Part.from_bytes(data=panel_crop, mime_type="image/jpeg"))

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {"answer": {"type": "STRING"}},
            "required": ["answer"],
        },
    )

    t0 = time.perf_counter()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=config,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    # Extract tokens
    tokens = TokenUsage()
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        tokens.input_tokens = getattr(um, "prompt_token_count", 0) or 0
        tokens.output_tokens = getattr(um, "candidates_token_count", 0) or 0
        tokens.total_tokens = getattr(um, "total_token_count", 0) or 0

    # Parse answer
    answer = ""
    if response.text:
        parsed = parse_ai_response(response.text)
        answer = parsed.answer

    return answer, tokens, latency_ms


# ── Collect all 30 images ────────────────────────────────────────────────

def collect_images(base: Path) -> list[tuple[Path, str]]:
    """Collect all images with category labels."""
    images = []
    for subdir in sorted(base.iterdir()):
        if not subdir.is_dir():
            continue
        category = subdir.name
        for img in sorted(subdir.glob("*.jpg")):
            images.append((img, category))
    return images


# ── Process one image ────────────────────────────────────────────────────

def process_image(img_path: Path, category: str, temp_dir: Path) -> ImageResult:
    """Run the full pipeline on one image and return results."""
    result = ImageResult(filename=img_path.name, category=category)
    wall_start = time.perf_counter()

    # -- Step 1: Load --
    t0 = time.perf_counter()
    import cv2
    img = cv2.imread(str(img_path))
    if img is None:
        result.errors.append("LOAD_FAILED")
        return result
    result.t_load = (time.perf_counter() - t0) * 1000

    # -- Step 2: Preprocess --
    t0 = time.perf_counter()
    preprocessor = ImagePreprocessor()
    out_path = temp_dir / f"{img_path.stem}_preprocessed.jpg"
    preprocessed = preprocessor.preprocess(img_path, output_path=out_path)
    result.t_preprocess = (time.perf_counter() - t0) * 1000

    # -- Step 3: PARALLEL launch AI + local processing --
    ai_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    ai_future = ai_executor.submit(query_ai_with_tokens, preprocessed)

    # -- Step 4: Layout + Option detection (local, single pass) --
    t0 = time.perf_counter()
    analyzer = OCRLayoutAnalyzer()
    ocr_result = analyzer.analyze(preprocessed)
    result.t_layout_options = (time.perf_counter() - t0) * 1000

    # -- Extract option results --
    if ocr_result:
        opt_map = ocr_result.get_option_map()
        if opt_map:
            result.options.count = opt_map.count
            sorted_opts = sorted(opt_map.options, key=lambda o: o.circle_y)
            result.options.labels = [o.label for o in sorted_opts]
            # Resolve click targets for each detected option
            for label in result.options.labels:
                target = ocr_result.locate_option_target(label)
                if target:
                    result.options.targets[label] = target

        # -- Extract button results --
        if ocr_result.layout:
            layout = ocr_result.layout
            if layout.next_button:
                nb = layout.next_button
                result.buttons.has_next = True
                result.buttons.next_pos = (nb.x, nb.y, nb.w, nb.h)
            if layout.prev_button:
                pb = layout.prev_button
                result.buttons.has_prev = True
                result.buttons.prev_pos = (pb.x, pb.y, pb.w, pb.h)
            result.buttons.is_last_question = layout.is_last_question

    local_end = time.perf_counter()
    result.local_processing_ms = result.t_load + result.t_preprocess + result.t_layout_options

    # -- Step 5: Wait for AI result --
    try:
        answer, tokens, ai_latency = ai_future.result(timeout=30)
        result.ai_answer = answer
        result.tokens = tokens
        result.t_ai = ai_latency
    except Exception as e:
        result.errors.append(f"AI_ERROR: {e}")
        result.t_ai = 0

    ai_executor.shutdown(wait=False)

    wall_end = time.perf_counter()
    result.t_total_wall = (wall_end - wall_start) * 1000

    # Parallelism savings: if AI and local run in parallel,
    # total wall = max(local, AI) + load + preprocess (serial prefix)
    serial_total = result.local_processing_ms + result.t_ai
    result.parallel_saved_ms = max(0, serial_total - result.t_total_wall)

    return result


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    base = Path("datasets/test-images")
    temp_dir = Path("runs/_pipeline_test_temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    images = collect_images(base)
    print(f"\n{'='*80}")
    print(f"  SIMULATO — Full Pipeline End-to-End Test")
    print(f"  Images: {len(images)}")
    print(f"{'='*80}\n")

    results: list[ImageResult] = []

    for idx, (img_path, category) in enumerate(images, 1):
        print(f"  [{idx:2d}/{len(images)}] {category}/{img_path.name}...", end=" ", flush=True)
        try:
            r = process_image(img_path, category, temp_dir)
            results.append(r)

            status = "OK" if not r.errors else f"ERRORS: {r.errors}"
            opts = ",".join(r.options.labels) if r.options.labels else "NONE"
            targets_ok = len(r.options.targets)
            next_str = "YES" if r.buttons.has_next else "NO"
            last_str = " [LAST-Q]" if r.buttons.is_last_question else ""
            print(
                f"{r.options.count} opts({opts}) "
                f"targets={targets_ok} "
                f"next={next_str}{last_str} "
                f"ai={r.ai_answer or '?'} "
                f"wall={r.t_total_wall:.0f}ms "
                f"tokens={r.tokens.total_tokens} "
                f"[{status}]"
            )
        except Exception as e:
            print(f"EXCEPTION: {e}")
            results.append(ImageResult(filename=img_path.name, category=category, errors=[str(e)]))

    # ── Aggregate stats ──────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  AGGREGATE RESULTS ({len(results)} images)")
    print(f"{'='*80}\n")

    total = len(results)
    errored = [r for r in results if r.errors]
    ok = [r for r in results if not r.errors]

    # Option detection
    opt3plus = [r for r in ok if r.options.count >= 3]
    opt4plus = [r for r in ok if r.options.count >= 4]
    no_opts = [r for r in ok if r.options.count == 0]

    # Target resolution (all detected options have click targets)
    full_targets = [r for r in ok if len(r.options.targets) == r.options.count and r.options.count > 0]

    # Button detection
    has_next = [r for r in ok if r.buttons.has_next]
    last_q = [r for r in ok if r.buttons.is_last_question]

    # AI
    ai_answered = [r for r in ok if r.ai_answer]
    total_input_tokens = sum(r.tokens.input_tokens for r in ok)
    total_output_tokens = sum(r.tokens.output_tokens for r in ok)
    total_all_tokens = sum(r.tokens.total_tokens for r in ok)

    # Timing
    avg_wall = sum(r.t_total_wall for r in ok) / max(1, len(ok))
    avg_local = sum(r.local_processing_ms for r in ok) / max(1, len(ok))
    avg_ai = sum(r.t_ai for r in ok if r.t_ai > 0) / max(1, len([r for r in ok if r.t_ai > 0]))
    avg_parallel_saved = sum(r.parallel_saved_ms for r in ok) / max(1, len(ok))

    print(f"  ACCURACY")
    print(f"  {'-'*40}")
    print(f"  Total images:              {total}")
    print(f"  Successful:                {len(ok)}/{total} ({len(ok)/max(1,total)*100:.0f}%)")
    print(f"  Errors:                    {len(errored)}")
    print(f"")
    print(f"  Option Detection:")
    print(f"    3+ options:              {len(opt3plus)}/{len(ok)} ({len(opt3plus)/max(1,len(ok))*100:.0f}%)")
    print(f"    4+ options:              {len(opt4plus)}/{len(ok)} ({len(opt4plus)/max(1,len(ok))*100:.0f}%)")
    print(f"    0 options:               {len(no_opts)}")
    print(f"")
    print(f"  Click Target Resolution:")
    print(f"    Full targets resolved:   {len(full_targets)}/{len(ok)} ({len(full_targets)/max(1,len(ok))*100:.0f}%)")
    print(f"")
    print(f"  Button Detection:")
    print(f"    NEXT button found:       {len(has_next)}/{len(ok)}")
    print(f"    Last-question detected:  {len(last_q)}")
    print(f"")
    print(f"  AI Responses:")
    print(f"    Answered:                {len(ai_answered)}/{len(ok)} ({len(ai_answered)/max(1,len(ok))*100:.0f}%)")
    print(f"")

    print(f"  TIMING (averages)")
    print(f"  {'-'*40}")
    print(f"  Load:                      {sum(r.t_load for r in ok)/max(1,len(ok)):.0f} ms")
    print(f"  Preprocess:                {sum(r.t_preprocess for r in ok)/max(1,len(ok)):.0f} ms")
    print(f"  Layout + Option detect:    {sum(r.t_layout_options for r in ok)/max(1,len(ok)):.0f} ms")
    print(f"  Local total:               {avg_local:.0f} ms")
    print(f"  AI latency:                {avg_ai:.0f} ms")
    print(f"  Wall-clock total:          {avg_wall:.0f} ms")
    print(f"  Parallel savings:          {avg_parallel_saved:.0f} ms/image")
    print(f"")

    print(f"  TOKEN USAGE")
    print(f"  {'-'*40}")
    print(f"  Total input tokens:        {total_input_tokens:,}")
    print(f"  Total output tokens:       {total_output_tokens:,}")
    print(f"  Total tokens:              {total_all_tokens:,}")
    print(f"  Avg tokens/image:          {total_all_tokens/max(1,len(ok)):,.0f}")
    print(f"")

    # Per-category breakdown
    categories = sorted(set(r.category for r in results))
    print(f"  PER-CATEGORY BREAKDOWN")
    print(f"  {'-'*40}")
    for cat in categories:
        cat_results = [r for r in ok if r.category == cat]
        if not cat_results:
            continue
        cat_opts = sum(1 for r in cat_results if r.options.count >= 3)
        cat_targets = sum(1 for r in cat_results if len(r.options.targets) == r.options.count and r.options.count > 0)
        cat_ai = sum(1 for r in cat_results if r.ai_answer)
        cat_wall = sum(r.t_total_wall for r in cat_results) / len(cat_results)
        print(f"  {cat}:")
        print(f"    Images: {len(cat_results)}  "
              f"Opts>=3: {cat_opts}/{len(cat_results)}  "
              f"Targets: {cat_targets}/{len(cat_results)}  "
              f"AI: {cat_ai}/{len(cat_results)}  "
              f"Avg wall: {cat_wall:.0f}ms")

    # Detailed per-image table for errors
    if errored:
        print(f"\n  ERRORS ({len(errored)} images)")
        print(f"  {'─'*40}")
        for r in errored:
            print(f"  {r.category}/{r.filename}: {r.errors}")

    # Save full results to JSON
    results_path = temp_dir / "pipeline_test_results.json"
    with open(results_path, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2, default=str)
    print(f"\n  Full results saved to: {results_path}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
