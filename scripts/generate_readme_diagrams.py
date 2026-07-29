#!/usr/bin/env python3
"""Generate README architecture diagrams (PNG) for the current stack.

Run:
    python3 scripts/generate_readme_diagrams.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"

# Palette (aligned with original diagram style)
BG = (255, 255, 255)
DARK_BLUE = (26, 54, 93)
DARK_BLUE_FILL = (44, 82, 130)
GREEN = (56, 161, 105)
GREEN_FILL = (240, 255, 244)
PURPLE = (107, 70, 193)
PURPLE_FILL = (250, 245, 255)
ORANGE = (221, 107, 32)
ORANGE_FILL = (255, 250, 240)
NEO4J = (0, 116, 217)
NEO4J_FILL = (235, 245, 255)
PG_FILL = (236, 244, 248)
PG_BORDER = (51, 103, 145)
GRAY = (113, 128, 150)
LIGHT_BLUE = (235, 248, 255)
LIGHT_ORANGE = (255, 247, 237)
RED = (229, 62, 62)
TEXT = (26, 32, 44)
MUTED = (74, 85, 104)
WHITE = (255, 255, 255)
ARROW = (113, 128, 150)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    lines: list[str],
    font,
    fill=TEXT,
    line_gap: int = 6,
) -> None:
    x0, y0, x1, y1 = box
    widths = []
    heights = []
    for line in lines:
        w, h = _text_size(draw, line, font)
        widths.append(w)
        heights.append(h)
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y0 + (y1 - y0 - total_h) // 2
    for i, line in enumerate(lines):
        w = widths[i]
        x = x0 + (x1 - x0 - w) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += heights[i] + line_gap


def _left_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    lines: list[str],
    font,
    fill=TEXT,
    line_gap: int = 5,
    pad_x: int = 16,
) -> None:
    x0, y0, x1, y1 = box
    heights = [_text_size(draw, line, font)[1] for line in lines]
    total_h = sum(heights) + line_gap * (len(lines) - 1)
    y = y0 + (y1 - y0 - total_h) // 2
    for i, line in enumerate(lines):
        draw.text((x0 + pad_x, y), line, font=font, fill=fill)
        y += heights[i] + line_gap


def _rounded_box(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill,
    outline,
    width: int = 2,
    radius: int = 10,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _arrow_down(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int) -> None:
    draw.line([(x, y0), (x, y1 - 8)], fill=ARROW, width=2)
    draw.polygon([(x, y1), (x - 6, y1 - 10), (x + 6, y1 - 10)], fill=ARROW)


def _arrow_right(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int, label: str | None = None) -> None:
    draw.line([(x0, y), (x1 - 8, y)], fill=ARROW, width=2)
    draw.polygon([(x1, y), (x1 - 10, y - 6), (x1 - 10, y + 6)], fill=ARROW)
    if label:
        font = _font(13)
        w, h = _text_size(draw, label, font)
        draw.text(((x0 + x1 - w) // 2, y - h - 8), label, font=font, fill=MUTED)


def architecture_overview() -> None:
    w, h = 920, 1180
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    title_font = _font(22, bold=True)
    box_font = _font(15, bold=True)
    sub_font = _font(13)
    small_font = _font(12)
    tag_font = _font(11, bold=True)

    draw.text((w // 2 - 180, 24), "OpenShift Cluster", font=title_font, fill=TEXT)

    cx = w // 2
    y = 70
    box_w = 760

    def box(y_pos: int, height: int, lines: list[str], fill, outline, subtitle: str | None = None) -> int:
        x0 = (w - box_w) // 2
        x1 = x0 + box_w
        y1 = y_pos + height
        _rounded_box(draw, (x0, y_pos, x1, y1), fill=fill, outline=outline)
        if subtitle:
            _center_text(draw, (x0, y_pos + 8, x1, y_pos + 34), [lines[0]], box_font, fill=WHITE if fill == DARK_BLUE_FILL else TEXT)
            _center_text(draw, (x0, y_pos + 34, x1, y1), lines[1:], sub_font, fill=WHITE if fill == DARK_BLUE_FILL else MUTED)
        else:
            _center_text(draw, (x0, y_pos, x1, y1), lines, box_font if len(lines) == 1 else sub_font, fill=WHITE if fill == DARK_BLUE_FILL else TEXT)
        return y1

    # FastAPI
    y1 = box(y, 56, ["FastAPI  ·  POST /query  ·  GET /admin/"], DARK_BLUE_FILL, DARK_BLUE)
    _arrow_down(draw, cx, y1 + 4, y1 + 28)
    y = y1 + 28

    # ReAct agent
    y1 = box(
        y,
        72,
        [
            "ReAct Agent Pipeline  (src/reasoning/pipeline.py)",
            "LLM orchestrator — chooses tools and order (max 6 rounds)",
            "tool_call_trace in every QueryResponse",
        ],
        DARK_BLUE_FILL,
        DARK_BLUE,
        subtitle="yes",
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 28)
    y = y1 + 28

    # Tools row
    tool_h = 110
    x0 = (w - box_w) // 2
    gap = 12
    tool_w = (box_w - 3 * gap) // 4
    tools = [
        ("get_affected_subgraph", "Neo4j Cypher", "NO LLM", GREEN, GREEN_FILL),
        ("solve_impact", "PostGIS + Solver", "NO LLM", GREEN, GREEN_FILL),
        ("search_scenario_context", "pgvector search", "via LLM client", PURPLE, PURPLE_FILL),
        ("run_ingestion_pull", "on-demand adapter", "refresh live data", GREEN, GREEN_FILL),
    ]
    for i, (title, sub, tag, outline, fill) in enumerate(tools):
        tx0 = x0 + i * (tool_w + gap)
        tx1 = tx0 + tool_w
        _rounded_box(draw, (tx0, y, tx1, y + tool_h), fill=fill, outline=outline)
        _center_text(draw, (tx0, y + 8, tx1, y + 36), [title], _font(12, bold=True), fill=TEXT)
        _center_text(draw, (tx0, y + 38, tx1, y + 78), [sub], small_font, fill=MUTED)
        tw, th = _text_size(draw, tag, tag_font)
        tag_x = tx0 + (tool_w - tw - 12) // 2
        draw.rounded_rectangle((tag_x, y + 82, tag_x + tw + 12, y + 82 + th + 8), radius=6, fill=outline)
        draw.text((tag_x + 6, y + 85), tag, font=tag_font, fill=WHITE)

    y1 = y + tool_h
    _arrow_down(draw, cx, y1 + 4, y1 + 28)
    y = y1 + 28

    # LLM client
    y1 = box(
        y,
        88,
        [
            "LLM Client  (src/llm/)",
            "OpenAI-compatible inference  ·  embeddings  ·  pgvector RAG",
            "Providers: OpenAI | vLLM | Llama Stack /v1 | fake (tests)",
        ],
        PURPLE_FILL,
        PURPLE,
        subtitle="yes",
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 28)
    y = y1 + 28

    # Direct query note
    y1 = box(
        y,
        56,
        ["Graph (Neo4j) + Live/Geo (PostGIS) queried DIRECTLY — not via LLM client"],
        GREEN_FILL,
        GREEN,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 28)
    y = y1 + 28

    # vLLM optional
    y1 = box(
        y,
        64,
        ["vLLM  (GPU, optional)  —  OpenAI-compatible /v1  ·  tool-calling model"],
        ORANGE_FILL,
        ORANGE,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 28)
    y = y1 + 28

    # Two stores side by side
    store_h = 150
    store_w = (box_w - gap) // 2
    neo4j_box = (x0, y, x0 + store_w, y + store_h)
    pg_box = (x0 + store_w + gap, y, x0 + box_w, y + store_h)

    _rounded_box(draw, neo4j_box, fill=NEO4J_FILL, outline=NEO4J, width=3)
    _center_text(
        draw,
        neo4j_box,
        [
            "Neo4j",
            "property graph · Cypher",
            "Entity nodes · dependency edges",
            "SimulationEvent overlays",
        ],
        box_font,
    )

    _rounded_box(draw, pg_box, fill=PG_FILL, outline=PG_BORDER, width=3)
    _center_text(
        draw,
        pg_box,
        [
            "PostgreSQL",
            "pgvector — embeddings / RAG",
            "PostGIS — live snapshot / geo",
        ],
        box_font,
    )

    out = OUT / "architecture-overview.png"
    img.save(out, "PNG")
    print(f"wrote {out}")


def query_flow() -> None:
    w, h = 860, 1180
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    title_font = _font(20, bold=True)
    box_font = _font(15, bold=True)
    sub_font = _font(13)
    tag_font = _font(11, bold=True)

    draw.text((40, 24), 'Query flow: "How would event X impact the current situation?"', font=title_font, fill=TEXT)

    cx = w // 2
    x0, x1 = 80, w - 80
    y = 80
    box_w = x1 - x0

    def step(
        y_pos: int,
        height: int,
        title: str,
        body: list[str],
        outline,
        fill,
        tag: str | None = None,
        tag_color=None,
    ) -> int:
        y1 = y_pos + height
        _rounded_box(draw, (x0, y_pos, x1, y1), fill=fill, outline=outline, width=2)
        draw.text((x0 + 16, y_pos + 12), title, font=box_font, fill=TEXT)
        by = y_pos + 40
        for line in body:
            draw.text((x0 + 16, by), line, font=sub_font, fill=MUTED)
            by += 22
        if tag:
            tw, th = _text_size(draw, tag, tag_font)
            draw.rounded_rectangle((x1 - tw - 28, y_pos + 12, x1 - 12, y_pos + 12 + th + 8), radius=6, fill=tag_color or outline)
            draw.text((x1 - tw - 22, y_pos + 15), tag, font=tag_font, fill=WHITE)
        return y1

    y1 = step(
        y,
        72,
        "1 · User submits POST /query",
        ["{ question, scenario_id }", "SimulationEvent already in Neo4j as an overlay"],
        DARK_BLUE,
        DARK_BLUE_FILL,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 26)
    y = y1 + 26

    y1 = step(
        y,
        110,
        "Round 1 — LLM calls get_affected_subgraph(scenario_id)",
        [
            "Neo4j Cypher traversal (direct, no LLM in this step)",
            "Walk DEPENDS_ON / FEEDS edges from AFFECTED_BY entities",
            "Returns affected entity IDs, edges, and attributes",
        ],
        GREEN,
        GREEN_FILL,
        tag="deterministic",
        tag_color=GREEN,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 26)
    y = y1 + 26

    y1 = step(
        y,
        110,
        "Round 2 — LLM calls solve_impact(scenario_id)",
        [
            "Pluggable Solver reads PostGIS live state (no LLM in this step)",
            "Computes impact score, chain length, response options",
            'Example: "reroute recovers 70% throughput"',
        ],
        GREEN,
        GREEN_FILL,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 26)
    y = y1 + 26

    y1 = step(
        y,
        96,
        "Round 3 (optional) — LLM calls search_scenario_context(...)",
        [
            "pgvector semantic search via LLM client",
            "Pulls event narratives, playbooks, and precedent",
        ],
        PURPLE,
        PURPLE_FILL,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 26)
    y = y1 + 26

    y1 = step(
        y,
        96,
        "LLM synthesis — grounded answer",
        [
            "Composes tool outputs into a cited explanation",
            "LLM explains; it does not invent impact numbers",
        ],
        PURPLE,
        PURPLE_FILL,
        tag="generative",
        tag_color=PURPLE,
    )
    _arrow_down(draw, cx, y1 + 4, y1 + 26)
    y = y1 + 26

    y1 = step(
        y,
        96,
        "Response",
        [
            "QueryResponse { answer, affected_entities, solver, tool_call_trace }",
            "Auditable: prose + deterministic evidence from each tool call",
        ],
        DARK_BLUE,
        DARK_BLUE_FILL,
    )

    # Side note
    draw.rounded_rectangle((x0, y1 + 24, x1, y1 + 84), radius=8, fill=(247, 250, 252), outline=GRAY)
    draw.text(
        (x0 + 16, y1 + 36),
        "Agent may reorder or skip tools — e.g. run_ingestion_pull first if live positions matter.",
        font=sub_font,
        fill=MUTED,
    )

    out = OUT / "query-flow.png"
    img.save(out, "PNG")
    print(f"wrote {out}")


def simulation_overlay() -> None:
    w, h = 920, 520
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    title_font = _font(20, bold=True)
    box_font = _font(14, bold=True)
    sub_font = _font(12)
    small_font = _font(11)

    draw.text(
        (w // 2 - 320, 20),
        "Simulation as a reversible overlay — ground truth is never mutated",
        font=title_font,
        fill=TEXT,
    )

    left = (40, 70, 430, 470)
    right = (490, 70, 880, 470)

    _rounded_box(draw, left, fill=(239, 246, 255), outline=DARK_BLUE, width=2)
    _rounded_box(draw, right, fill=(255, 245, 245), outline=RED, width=2, radius=10)
    # dashed effect for overlay - draw inner dashed border manually
    rx0, ry0, rx1, ry1 = right
    for x in range(rx0, rx1, 16):
        draw.line([(x, ry0), (min(x + 8, rx1), ry0)], fill=RED, width=2)
        draw.line([(x, ry1), (min(x + 8, rx1), ry1)], fill=RED, width=2)
    for y in range(ry0, ry1, 16):
        draw.line([(rx0, y), (rx0, min(y + 8, ry1))], fill=RED, width=2)
        draw.line([(rx1, y), (rx1, min(y + 8, ry1))], fill=RED, width=2)

    draw.text((left[0] + 16, left[1] + 12), "GROUND TRUTH (read-only at query time)", font=box_font, fill=DARK_BLUE)
    draw.text((right[0] + 16, right[1] + 12), "OVERLAY (injected, removable in one op)", font=box_font, fill=RED)

    # Simple graph nodes left
    nodes = {"A": (120, 170), "B": (220, 230), "C": (320, 170), "D": (280, 310)}
    node_r = 22
    for label, (nx, ny) in nodes.items():
        draw.ellipse((nx - node_r, ny - node_r, nx + node_r, ny + node_r), fill=WHITE, outline=DARK_BLUE, width=2)
        tw, th = _text_size(draw, label, sub_font)
        draw.text((nx - tw // 2, ny - th // 2), label, font=sub_font, fill=TEXT)

    def edge(a: str, b: str) -> None:
        ax, ay = nodes[a]
        bx, by = nodes[b]
        draw.line([(ax, ay), (bx, by)], fill=DARK_BLUE, width=2)
        # arrowhead toward b
        draw.polygon([(bx, by), (bx - 8, by - 6), (bx - 8, by + 6)], fill=DARK_BLUE)

    edge("A", "B")
    edge("C", "B")
    edge("B", "D")

    draw.text((left[0] + 16, left[3] - 72), "Neo4j dependency graph", font=sub_font, fill=MUTED)
    draw.text((left[0] + 16, left[3] - 50), "FEEDS / DEPENDS_ON edges", font=sub_font, fill=MUTED)
    draw.text((left[0] + 16, left[3] - 28), "+ PostGIS live snapshot (positions, states)", font=sub_font, fill=MUTED)

    # Overlay right
    draw.rounded_rectangle((right[0] + 40, 120, right[0] + 320, 160), radius=8, fill=(254, 215, 215), outline=RED, width=2)
    draw.text((right[0] + 56, 132), "SimulationEvent  scenario_id = S1", font=sub_font, fill=RED)

    for label, ox in [("B'", 160), ("D'", 300)]:
        draw.ellipse((ox - 20, 250, ox + 20, 290), outline=RED, width=2)
        tw, th = _text_size(draw, label, sub_font)
        draw.text((ox - tw // 2, 260), label, font=sub_font, fill=RED)
        draw.line([(right[0] + 180, 160), (ox, 250)], fill=RED, width=2)
        mid_x = (right[0] + 180 + ox) // 2
        draw.text((mid_x - 40, 195), "AFFECTED_BY", font=small_font, fill=RED)

    draw.text(
        (right[0] + 16, right[3] - 72),
        "Event node + AFFECTED_BY edges in Neo4j",
        font=sub_font,
        fill=MUTED,
    )
    draw.text(
        (right[0] + 16, right[3] - 50),
        "Event narrative embedded in pgvector, tagged scenario_id = S1",
        font=sub_font,
        fill=MUTED,
    )
    draw.text(
        (right[0] + 16, right[3] - 28),
        "Multiple scenarios (S1, S2, S3…) coexist — each is an independent what-if",
        font=sub_font,
        fill=MUTED,
    )

    # Arrow between boxes
    _arrow_right(draw, left[2] + 8, right[0] - 8, 270, "references\nnever edits")

    out = OUT / "simulation-overlay.png"
    img.save(out, "PNG")
    print(f"wrote {out}")


def domain_seams() -> None:
    w, h = 920, 620
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    title_font = _font(20, bold=True)
    header_font = _font(15, bold=True)
    item_font = _font(13)
    small_font = _font(12)

    draw.text((w // 2 - 250, 20), "What changes per domain vs. what stays fixed", font=title_font, fill=TEXT)

    left = (40, 70, 420, 580)
    right = (500, 70, 880, 580)

    _rounded_box(draw, left, fill=LIGHT_BLUE, outline=DARK_BLUE, width=2)
    _rounded_box(draw, right, fill=LIGHT_ORANGE, outline=ORANGE, width=2)

    draw.text((left[0] + 16, left[1] + 12), "FIXED CORE (identical across domains)", font=header_font, fill=DARK_BLUE)
    draw.text((right[0] + 16, right[1] + 12), "SWAP SEAMS (per domain)", font=header_font, fill=ORANGE)

    fixed_items = [
        "OpenShift platform + deployment model",
        "LLM client (OpenAI-compatible inference + pgvector RAG)",
        "vLLM inference (optional, GPU)",
        "Neo4j (graph) + Postgres (pgvector + PostGIS)",
        "ReAct agent pipeline + tool_call_trace",
        "Simulation overlay mechanism",
        "Canonical entity schema (generic)",
    ]

    y = left[1] + 52
    for item in fixed_items:
        _rounded_box(draw, (left[0] + 16, y, left[2] - 16, y + 44), fill=WHITE, outline=(190, 215, 235), width=1)
        draw.text((left[0] + 28, y + 13), item, font=item_font, fill=TEXT)
        y += 52

    draw.text((left[0] + 16, left[3] - 28), "No domain entity names in core packages", font=small_font, fill=MUTED)

    seams = [
        (
            "1 · Ingestion adapters",
            "supply chain: flight / AIS / freight APIs",
            "manufacturing: OPC-UA / MQTT / SCADA / historian",
        ),
        (
            "2 · Graph schema",
            "supply chain: Port / Route / Region",
            "manufacturing: ISA-95 — Site / Area / Work Cell / Equipment",
        ),
        (
            "3 · Solver logic (Stage 2)",
            "supply chain: route pathfinding",
            "manufacturing: production rescheduling / line balancing",
        ),
        (
            "4 · Domain context in RAG",
            "supply chain: logistics precedent",
            "manufacturing: SOPs, maintenance manuals, plant playbooks",
        ),
    ]

    y = right[1] + 52
    for title, line1, line2 in seams:
        _rounded_box(draw, (right[0] + 16, y, right[2] - 16, y + 78), fill=WHITE, outline=(250, 210, 170), width=1)
        draw.text((right[0] + 28, y + 10), title, font=item_font, fill=TEXT)
        draw.text((right[0] + 28, y + 32), line1, font=small_font, fill=MUTED)
        draw.text((right[0] + 28, y + 50), line2, font=small_font, fill=MUTED)
        y += 88

    _arrow_right(draw, left[2] + 8, right[0] - 8, 320, "plug into")

    out = OUT / "domain-seams.png"
    img.save(out, "PNG")
    print(f"wrote {out}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    architecture_overview()
    query_flow()
    simulation_overlay()
    domain_seams()


if __name__ == "__main__":
    main()
