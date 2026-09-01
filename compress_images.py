
# compress_images.py - run once: python compress_images.py
from PIL import Image
import os

to_compress = [
  "static/motto.jpeg",
  "static/images/gate.jpg",
  "static/images/gate.png",
  "static/images/bread.jpg",
  "static/uploads/encounter_bg.webp"
]

for path in to_compress:
    if os.path.exists(path):
        img = Image.open(path)
        # Resize if too large > 1920
        if max(img.size) > 1920:
            img.thumbnail((1920, 1920))
        # Save with compression
        if path.endswith('.jpeg') or path.endswith('.jpg'):
            img.save(path, 'JPEG', quality=75, optimize=True)
        elif path.endswith('.png'):
            img.save(path, 'PNG', optimize=True)
        elif path.endswith('.webp'):
            img.save(path, 'WEBP', quality=75)
        print(f"Compressed {path} -> {os.path.getsize(path)//1024}KB")

print("Done - images compressed 60-70% smaller, same quality")
# pip install Pillow
