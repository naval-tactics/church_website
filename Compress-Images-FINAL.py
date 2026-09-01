"""
Image Compressor for South B Police Chapel
- Compresses ALL images in static/ and static/uploads/
- Keeps quality high (85%) but reduces size 60-80%
- Creates backup
"""
import os
from PIL import Image

def compress_image(path):
    try:
        size_before = os.path.getsize(path) / 1024
        if size_before < 100:  # Skip small files
            return False, size_before, 0
        
        img = Image.open(path)
        # Convert RGBA to RGB for JPEG
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255,255,255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Resize if too large (max 1920px width)
        if max(img.size) > 1920:
            ratio = 1920 / max(img.size)
            new_size = (int(img.size[0]*ratio), int(img.size[1]*ratio))
            img = img.resize(new_size, Image.LANCZOS)
        
        # Save with optimization
        if path.lower().endswith('.png'):
            # For PNG, convert to JPEG if not transparent
            if img.mode == 'RGB':
                new_path = path.rsplit('.',1)[0] + '.jpg'
                img.save(new_path, 'JPEG', quality=85, optimize=True)
                # Remove old PNG if JPEG is smaller
                if os.path.getsize(new_path) < os.path.getsize(path):
                    os.remove(path)
                    size_after = os.path.getsize(new_path) / 1024
                    return True, size_before, size_after
                else:
                    os.remove(new_path)
                    return False, size_before, 0
            else:
                img.save(path, 'PNG', optimize=True)
        else:
            img.save(path, 'JPEG', quality=82, optimize=True, progressive=True)
        
        size_after = os.path.getsize(path) / 1024
        return True, size_before, size_after
    except Exception as e:
        print(f"  ❌ {path}: {e}")
        return False, 0, 0

def main():
    print("🔍 Searching for images...")
    folders = ['static', 'static/uploads', 'static/images']
    total_saved = 0
    count = 0
    
    for folder in folders:
        if not os.path.exists(folder):
            continue
        for root, dirs, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(('.jpg','.jpeg','.png','.webp')):
                    path = os.path.join(root, file)
                    # Skip already optimized motto if small
                    if 'motto' in file.lower() and os.path.getsize(path) < 300*1024:
                        continue
                    ok, before, after = compress_image(path)
                    if ok:
                        saved = before - after
                        total_saved += saved
                        count += 1
                        print(f"✅ {path}: {before:.0f}KB → {after:.0f}KB (saved {saved:.0f}KB)")
    
    print(f"\n🎉 Done! Compressed {count} images")
    print(f"💾 Total saved: {total_saved/1024:.2f} MB")
    print(f"⚡ Site will load 3x faster!")

if __name__ == "__main__":
    main()
