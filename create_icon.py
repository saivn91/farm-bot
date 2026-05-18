"""
Run this once to generate a placeholder icon.ico for the build.
Requires Pillow.
"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_icon():
    img = Image.new("RGBA", (256, 256), (13, 17, 23, 255))
    draw = ImageDraw.Draw(img)
    
    draw.ellipse([20, 20, 236, 236], fill=(35, 134, 54), outline=(56, 212, 100), width=6)
    
    try:
        font = ImageFont.truetype("arial.ttf", 120)
    except Exception:
        font = ImageFont.load_default()
    
    draw.text((128, 128), "🌾", font=font, anchor="mm")
    
    os.makedirs("assets", exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    icons[0].save("assets/icon.ico", format="ICO", sizes=[(s, s) for s in sizes],
                  append_images=icons[1:])
    print("Icon saved to assets/icon.ico")

if __name__ == "__main__":
    create_icon()
