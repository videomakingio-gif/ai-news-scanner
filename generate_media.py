import os
from PIL import Image, ImageDraw, ImageFont

def text_to_image(text, output_path, font_size=16, bg_color=(30, 30, 30), text_color=(240, 240, 240)):
    # Try to find a monospace font
    font_paths = [
        "C:\\Windows\\Fonts\\consola.ttf",
        "C:\\Windows\\Fonts\\lucon.ttf",
        "C:\\Windows\\Fonts\\cour.ttf"
    ]
    font = None
    for path in font_paths:
        if os.path.exists(path):
            font = ImageFont.truetype(path, font_size)
            break
    if not font:
        font = ImageFont.load_default()

    lines = text.split('\n')
    # Limit lines to fit in a reasonable image
    lines = lines[-40:] if len(lines) > 40 else lines
    
    # Calculate image size
    line_height = font_size + 4
    width = 1000
    height = len(lines) * line_height + 20
    
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    y = 10
    for line in lines:
        # Simple cleanup for the native command error noise in the log
        if "CategoryInfo" in line or "FullyQualifiedErrorId" in line or "NativeCommandError" in line:
            continue
        d.text((10, y), line, font=font, fill=text_color)
        y += line_height
        
    img.save(output_path)

def create_gif(log_path, gif_output_path):
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Remove the PowerShell noise at the beginning
    lines = content.split('\n')
    clean_lines = []
    for line in lines:
        if "CategoryInfo" in line or "FullyQualifiedErrorId" in line or "NativeCommandError" in line or "In riga:" in line:
            continue
        if line.strip():
            clean_lines.append(line)

    frames = []
    # Create frames showing progress
    # Phase 1: Fetching
    frames.append("\n".join(clean_lines[:15]))
    # Phase 2: Scoring (show a few)
    scoring_start = next((i for i, l in enumerate(clean_lines) if "Phase 3: Scoring" in l), 20)
    frames.append("\n".join(clean_lines[:scoring_start+5]))
    frames.append("\n".join(clean_lines[:scoring_start+15]))
    frames.append("\n".join(clean_lines[:scoring_start+25]))
    # Final results
    frames.append("\n".join(clean_lines[-30:]))

    image_files = []
    for i, frame_text in enumerate(frames):
        path = f"frame_{i}.png"
        text_to_image(frame_text, path)
        image_files.append(path)
    
    # Create screenshot of final output
    text_to_image("\n".join(clean_lines[-25:]), "screenshot_output.png")

    # Use pillow to save GIF if ffmpeg is not used directly
    imgs = [Image.open(f) for f in image_files]
    imgs[0].save(gif_output_path, save_all=True, append_images=imgs[1:], duration=1000, loop=0)
    
    # Cleanup frames
    for f in image_files:
        os.remove(f)

if __name__ == "__main__":
    create_gif("execution_output.log", "execution_scan.gif")
