#!/usr/bin/env python3
"""Render the deterministic, sanitized README demo GIF."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "demo.gif"
FONT_PATH = "/System/Library/Fonts/SFNSMono.ttf"
WIDTH, HEIGHT = 1200, 675

STAGES = [
    (
        "1 / 4  Trigger the controlled demo incident",
        [
            "$ curl -i http://203.0.113.10:8000/crash",
            "HTTP/1.1 500 Internal Server Error",
            '{"detail":"intentional crash"}',
            "",
            "CloudWatch  <-  ERROR DemoFailure path=/crash status=500",
        ],
    ),
    (
        "2 / 4  Start a bounded, read-only investigation",
        [
            "$ python triage-agent/agent.py",
            "    --cluster example-cluster --service checkout-demo",
            "    --log-group /ecs/checkout-demo --lookback-minutes 180",
            "",
            "Target locked: example-cluster / checkout-demo / us-east-1",
        ],
    ),
    (
        "3 / 4  Collect and correlate evidence",
        [
            "[ok] ecs:DescribeClusters    cluster ACTIVE",
            "[ok] ecs:DescribeServices    desired/running/pending 1/1/0",
            "[ok] ecs:ListTasks + DescribeTasks",
            "[ok] logs:FilterLogEvents    6 image-pull errors",
            "[ok] local pattern analysis  image_pull_failure (high)",
            "",
            "No Create*, Update*, Stop*, Delete*, PassRole, or shell tool.",
        ],
    ),
    (
        "4 / 4  Review the evidence-backed RCA",
        [
            "RCA written -> incidents/incident-20260827T142000Z.md",
            "",
            "CONFIRMED ROOT CAUSE",
            "Container manifest did not include linux/amd64.",
            "",
            "UNVERIFIED",
            "Why the incompatible image was selected.",
            "",
            "Operator review required. No remediation was executed.",
        ],
    ),
]


def render(stage: str, lines: list[str], cursor: bool) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0b1220")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(FONT_PATH, 28)
    body_font = ImageFont.truetype(FONT_PATH, 21)
    small_font = ImageFont.truetype(FONT_PATH, 16)

    draw.rounded_rectangle(
        (42, 35, WIDTH - 42, HEIGHT - 35),
        20,
        fill="#111d32",
        outline="#31415e",
        width=2,
    )
    draw.ellipse((72, 64, 88, 80), fill="#ff6b6b")
    draw.ellipse((98, 64, 114, 80), fill="#ffd166")
    draw.ellipse((124, 64, 140, 80), fill="#72e0a8")
    draw.text((72, 111), stage, font=title_font, fill="#f7fafc")
    draw.line((72, 158, WIDTH - 72, 158), fill="#31415e", width=2)

    y = 191
    for line in lines:
        color = "#d8e1ee"
        if line.startswith("[ok]"):
            color = "#72e0a8"
        elif line in {"CONFIRMED ROOT CAUSE", "UNVERIFIED"}:
            color = "#ffcf70"
        elif line.startswith("No ") or line.startswith("Operator "):
            color = "#9fb0c8"
        draw.text((78, y), line, font=body_font, fill=color)
        y += 40

    if cursor:
        draw.rectangle((78, min(y + 3, 590), 91, min(y + 27, 614)), fill="#72e0a8")
    draw.text(
        (72, HEIGHT - 72),
        "SANITIZED DEMO  |  fictional identifiers  |  read-only by construction",
        font=small_font,
        fill="#71829b",
    )
    return image


def main() -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    for stage, lines in STAGES:
        frames.extend([render(stage, lines, True), render(stage, lines, False)])
        durations.extend([1800, 450])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
