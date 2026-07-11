"""Convert local profile picture to ASCII art for SVG banner."""
from PIL import Image, ImageEnhance, ImageFilter
import sys

# Character ramp from light (space) to dark
# Using chars that render well in Consolas monospace and are XML-safe
CHARS_DARK = " .':;|/\\(){}1ixczXYUJCLQ0OZmwqpdbkhao*#MW%@$"
CHARS_LIGHT = "$@%WM#*oahkbdpqwmZO0QLCJUYXzcxi1{}()/\\|;:'. "

def image_to_ascii(img_path, width=42, height=22, for_dark_bg=True):
    """Convert image to ASCII art lines."""
    img = Image.open(img_path)
    
    # Crop to just the owl (left 60% of image, since right side is black)
    w, h = img.size
    img = img.crop((0, 0, int(w * 0.55), h))
    
    # Convert to grayscale
    img = img.convert('L')
    
    # Increase contrast
    img = ImageEnhance.Contrast(img).enhance(1.5)
    img = ImageEnhance.Brightness(img).enhance(1.1)
    
    # Resize for ASCII (chars are ~2x taller than wide)
    img = img.resize((width, height))
    
    chars = CHARS_DARK if for_dark_bg else CHARS_LIGHT
    
    pixels = list(img.getdata())
    lines = []
    for row in range(height):
        line = ''
        for col in range(width):
            pixel = pixels[row * width + col]
            idx = int(pixel / 255 * (len(chars) - 1))
            line += chars[idx]
        lines.append(line)
    
    return lines

def escape_xml(text):
    """Escape special chars for XML/SVG."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

if __name__ == '__main__':
    img_path = 'pfp.png'
    
    print("=" * 60)
    print("DARK BACKGROUND (for dark_mode.svg)")
    print("=" * 60)
    dark = image_to_ascii(img_path, width=42, height=22, for_dark_bg=True)
    for i, line in enumerate(dark, 1):
        print(f'{i:>2}  |{line}|')
    
    print()
    print("=" * 60)
    print("LIGHT BACKGROUND (for light_mode.svg)")  
    print("=" * 60)
    light = image_to_ascii(img_path, width=42, height=22, for_dark_bg=False)
    for i, line in enumerate(light, 1):
        print(f'{i:>2}  |{line}|')
    
    # Python list output for embedding
    print("\n\n# XML-escaped for SVG embedding:")
    print("DARK_ASCII = [")
    for line in dark:
        print(f'    {repr(escape_xml(line))},')
    print("]")
    
    print("\nLIGHT_ASCII = [")
    for line in light:
        print(f'    {repr(escape_xml(line))},')
    print("]")
