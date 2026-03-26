"""Notification image generator — renders 984x360 phone mockup preview PNGs.

Creates realistic Android-style notification shade previews using Pillow,
with status bar, app icon, notification card, and CTA button. Each image
is themed with a left accent border matching the notification theme color.
"""

import io
from pathlib import Path

import structlog
from PIL import Image, ImageDraw, ImageFont

logger = structlog.get_logger()

# Image dimensions
WIDTH = 984
HEIGHT = 360

# Font paths (bundled Inter fonts with fallback)
_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_FONT_REGULAR = _FONTS_DIR / "Inter-Regular.ttf"
_FONT_BOLD = _FONTS_DIR / "Inter-Bold.ttf"

# Theme accent colors for the notification card left border
THEME_COLORS: dict[str, str] = {
    "click_bait": "#ef4444",
    "fomo": "#f59e0b",
    "motivational": "#22c55e",
    "relationship": "#ec4899",
    "appreciation": "#f59e0b",
    "wotd": "#3b82f6",
    "challenge": "#ef4444",
    "story_teaser": "#8b5cf6",
    "milestone": "#22c55e",
    "tip": "#06b6d4",
    "streak": "#f97316",
    "quiz": "#a855f7",
    "recap": "#6366f1",
    "social_proof": "#14b8a6",
    "humor": "#eab308",
}


def _load_font(bold: bool = False, size: int = 16) -> ImageFont.FreeTypeFont:
    """Load Inter font with fallback chain."""
    font_path = _FONT_BOLD if bold else _FONT_REGULAR
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        pass
    for fallback in ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf"]:
        try:
            return ImageFont.truetype(fallback, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _draw_status_bar(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont) -> None:
    """Draw the Android-style status bar at the top."""
    bar_h = 36
    draw.rectangle([0, 0, WIDTH, bar_h], fill=(20, 20, 20))
    draw.text((32, 8), "9:41", fill=(180, 180, 180), font=font)

    # Battery icon
    bx = WIDTH - 60
    draw.rectangle([bx, 12, bx + 22, 24], outline=(140, 140, 140), width=1)
    draw.rectangle([bx + 22, 16, bx + 24, 20], fill=(140, 140, 140))
    draw.rectangle([bx + 2, 14, bx + 16, 22], fill=(100, 200, 100))

    # Signal bars
    sx = WIDTH - 100
    for i in range(4):
        bar_height = 6 + i * 3
        draw.rectangle(
            [sx + i * 7, 24 - bar_height, sx + i * 7 + 4, 24],
            fill=(140, 140, 140),
        )


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines


def generate_notification_image(
    title: str,
    body: str,
    cta: str,
    theme: str,
    state: str,
) -> bytes:
    """Render a 984x360 phone mockup notification preview PNG.

    Args:
        title: Notification title text.
        body: Notification body text.
        cta: Call-to-action button text.
        theme: Notification theme (used for accent color).
        state: User state at generation (shown in metadata strip).

    Returns:
        PNG image as bytes.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 10, 10))
    draw = ImageDraw.Draw(img)

    # Background gradient (dark phone wallpaper)
    for y_pos in range(HEIGHT):
        r = int(10 + 6 * (y_pos / HEIGHT))
        g = int(10 + 6 * (y_pos / HEIGHT))
        b = int(10 + 22 * (y_pos / HEIGHT))
        draw.line([(0, y_pos), (WIDTH, y_pos)], fill=(r, g, b))

    # Load fonts
    font_status = _load_font(size=14)
    font_small = _load_font(size=15)
    font_title = _load_font(bold=True, size=22)
    font_body = _load_font(size=16)
    font_cta = _load_font(bold=True, size=14)
    font_meta = _load_font(size=12)
    font_icon = _load_font(bold=True, size=16)

    # Get theme accent color
    accent_hex = THEME_COLORS.get(theme, "#8b5cf6")
    accent_rgb = _hex_to_rgb(accent_hex)

    # 1. Status bar
    _draw_status_bar(draw, font_status)

    # 2. Notification card
    card_x = 24
    card_y = 48
    card_w = WIDTH - 48
    card_h = 265
    card_right = card_x + card_w
    card_bottom = card_y + card_h

    # Card background (rounded rectangle)
    draw.rounded_rectangle(
        [card_x, card_y, card_right, card_bottom],
        radius=16,
        fill=(31, 31, 35),
    )

    # Theme accent left border (4px wide vertical strip)
    draw.rectangle(
        [card_x, card_y + 16, card_x + 4, card_bottom - 16],
        fill=accent_rgb,
    )

    # 3. App header inside card
    icon_x = card_x + 36
    icon_y = card_y + 20
    icon_r = 14

    # App icon: colored circle with "S"
    draw.ellipse(
        [icon_x - icon_r, icon_y - icon_r + 8, icon_x + icon_r, icon_y + icon_r + 8],
        fill=accent_rgb,
    )
    draw.text((icon_x - 5, icon_y - 1), "S", fill=(255, 255, 255), font=font_icon)

    # App name and timestamp
    draw.text((icon_x + 20, icon_y), "SpeakX", fill=(200, 200, 200), font=font_small)
    draw.text((icon_x + 80, icon_y), " \u00b7  now", fill=(120, 120, 120), font=font_small)

    # Chevron indicator
    cx = card_right - 40
    draw.polygon(
        [(cx, icon_y + 5), (cx + 8, icon_y + 5), (cx + 4, icon_y + 11)],
        fill=(100, 100, 100),
    )

    content_y = icon_y + icon_r + 16

    # Divider line
    draw.line(
        [(card_x + 20, content_y), (card_right - 20, content_y)],
        fill=(55, 55, 60),
        width=1,
    )
    content_y += 12

    # 4. Title text
    text_x = card_x + 24
    text_max_w = card_w - 60
    title_lines = _wrap_text(title, font_title, text_max_w)
    for line in title_lines[:2]:
        draw.text((text_x, content_y), line, fill=(245, 245, 245), font=font_title)
        content_y += 28
    content_y += 4

    # 5. Body text
    body_lines = _wrap_text(body, font_body, text_max_w)
    for line in body_lines[:3]:
        draw.text((text_x, content_y), line, fill=(161, 161, 170), font=font_body)
        content_y += 22
    content_y += 8

    # 6. CTA button (pill shape)
    if cta:
        cta_text = cta[:40]
        cta_bbox = font_cta.getbbox(cta_text)
        cta_w = (cta_bbox[2] - cta_bbox[0]) + 32
        cta_h = 32
        cta_x = text_x
        cta_y = content_y

        if cta_y + cta_h < card_bottom - 10:
            draw.rounded_rectangle(
                [cta_x, cta_y, cta_x + cta_w, cta_y + cta_h],
                radius=16,
                fill=accent_rgb,
            )
            draw.text(
                (cta_x + 16, cta_y + 7),
                cta_text,
                fill=(255, 255, 255),
                font=font_cta,
            )

    # 7. Metadata strip below card
    meta_y = card_bottom + 10
    theme_label = theme.replace("_", " ").title()
    state_label = state.replace("_", " ").title()
    meta_text = f"Theme: {theme_label}  \u00b7  State: {state_label}"
    draw.text((card_x + 8, meta_y), meta_text, fill=(80, 80, 90), font=font_meta)

    # Encode to PNG bytes
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def save_notification_image(
    image_bytes: bytes,
    notification_id: str,
    output_dir: Path,
) -> str:
    """Save PNG image to disk and return the relative path.

    Args:
        image_bytes: Raw PNG bytes from generate_notification_image().
        notification_id: UUID string used as filename.
        output_dir: Directory to write the file into.

    Returns:
        Relative path suitable for storing in Notification.image_path,
        e.g. "notifications/abc123.png".
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{notification_id}.png"
    filepath = output_dir / filename
    filepath.write_bytes(image_bytes)
    return f"notifications/{filename}"
