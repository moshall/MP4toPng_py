# PicoPico MP4 to PNG 高级处理引擎 v5.0 (最终交付版)
# 功能: 从视频提取帧，并可选地进行缩放、效果加工和画布合成。
# 新增: 支持两种不同的边缘效果处理顺序。

import os
import subprocess
import shutil
import platform
import json
import time
from math import floor

# --- 依赖检查 ---
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
except ImportError:
    print("错误: 核心界面库 rich 未安装。")
    print("请在您的终端中运行以下命令来安装它:")
    print("pip install rich")
    exit()

try:
    from PIL import Image, ImageDraw, ImageChops, ImageFilter
except ImportError:
    print("错误: 核心图像处理库 Pillow 未安装。")
    print("请在您的终端中运行以下命令来安装它:")
    print("pip install Pillow")
    exit()


# --- 全局辅助函数 ---

def clear_screen():
    """清空终端屏幕"""
    os.system('cls' if os.name == 'nt' else 'clear')

def check_ffmpeg():
    """检查 FFmpeg 是否已安装"""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

def get_video_dimensions(video_path, console):
    """使用 ffprobe 获取视频的原始宽度和高度"""
    try:
        command = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', video_path
        ]
        result = subprocess.check_output(command).decode('utf-8').strip()
        width, height = map(int, result.split('x'))
        return width, height
    except Exception as e:
        console.print(f"[red]错误：无法获取视频尺寸。请检查文件路径和 FFprobe 是否正常。[/red]")
        console.print(f"[dim]{e}[/dim]")
        return None, None

def hex_to_rgb(hex_color):
    """将 #RRGGBB 格式的十六进制颜色转为 (R, G, B) 元组"""
    try:
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6: return (0, 0, 0)
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)

def ease_in_out_cubic(t):
    """一个标准的缓入缓出函数，t的取值范围为 0.0 到 1.0"""
    return t * t * (3.0 - 2.0 * t)

def apply_effects_to_image(image_path, processing_settings, console):
    """重构版: 根据指定顺序，对图片应用综合效果"""
    try:
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size

        # --- 预先生成所有效果需要的基础蒙版 ---
        # 1. 圆角蒙版 (C)
        corner_mask = Image.new("L", (width, height), 255)
        radius_percent = processing_settings['corner_radius']
        if radius_percent > 0:
            shortest_side = min(width, height)
            radius_px = int(shortest_side * radius_percent / 100)
            if radius_px > 0:
                corner_mask_temp = Image.new("L", (width, height), 0)
                draw = ImageDraw.Draw(corner_mask_temp)
                draw.rounded_rectangle((0, 0, width, height), radius=radius_px, fill=255)
                corner_mask = corner_mask_temp
        
        # 2. 平滑虚化蒙版 (F)
        feather_mask_final = Image.new("L", (width, height), 255)
        feather_settings = processing_settings['feathering']
        if any(v > 0 for v in feather_settings.values()):
            top_mask = Image.new("L", (width, height), 255)
            if feather_settings['top'] > 0:
                top_px = int(height * feather_settings['top'] / 100)
                if top_px > 1:
                    top_gradient = Image.new("L", (width, top_px))
                    denominator = top_px - 1
                    for y in range(top_px):
                        alpha = int(255 * ease_in_out_cubic(y / denominator))
                        ImageDraw.Draw(top_gradient).line([(0, y), (width, y)], fill=alpha)
                    top_mask.paste(top_gradient, (0, 0))

            bottom_mask = Image.new("L", (width, height), 255)
            if feather_settings['bottom'] > 0:
                bottom_px = int(height * feather_settings['bottom'] / 100)
                if bottom_px > 1:
                    bottom_gradient = Image.new("L", (width, bottom_px))
                    denominator = bottom_px - 1
                    for y in range(bottom_px):
                        alpha = int(255 * (1 - ease_in_out_cubic(y / denominator)))
                        ImageDraw.Draw(bottom_gradient).line([(0, y), (width, y)], fill=alpha)
                    bottom_mask.paste(bottom_gradient, (0, height - bottom_px))

            left_mask = Image.new("L", (width, height), 255)
            if feather_settings['left'] > 0:
                left_px = int(width * feather_settings['left'] / 100)
                if left_px > 1:
                    left_gradient = Image.new("L", (left_px, height))
                    denominator = left_px - 1
                    for x in range(left_px):
                        alpha = int(255 * ease_in_out_cubic(x / denominator))
                        ImageDraw.Draw(left_gradient).line([(x, 0), (x, height)], fill=alpha)
                    left_mask.paste(left_gradient, (0, 0))

            right_mask = Image.new("L", (width, height), 255)
            if feather_settings['right'] > 0:
                right_px = int(width * feather_settings['right'] / 100)
                if right_px > 1:
                    right_gradient = Image.new("L", (right_px, height))
                    denominator = right_px - 1
                    for x in range(right_px):
                        alpha = int(255 * (1 - ease_in_out_cubic(x / denominator)))
                        ImageDraw.Draw(right_gradient).line([(x, 0), (x, height)], fill=alpha)
                    right_mask.paste(right_gradient, (width - right_px, 0))
            
            feather_mask_final = ImageChops.multiply(ImageChops.multiply(top_mask, bottom_mask), ImageChops.multiply(left_mask, right_mask))

        # --- 按照指定顺序应用效果 ---
        final_mask = Image.new("L", (width, height), 255)
        order = processing_settings.get('order', 'C-F-B') # 默认为标准顺序
        blur_strength = processing_settings['blur_strength']

        if order == 'C-F-B':
            # 顺序 A: 圆角 -> 虚化 -> 模糊 (标准柔和)
            mask = ImageChops.multiply(final_mask, corner_mask)
            mask = ImageChops.multiply(mask, feather_mask_final)
            if blur_strength > 0:
                mask = mask.filter(ImageFilter.GaussianBlur(blur_strength))
            final_mask = mask
        elif order == 'C-B-F':
            # 顺序 B: 圆角 -> 模糊 -> 虚化 (轮廓感)
            mask = ImageChops.multiply(final_mask, corner_mask)
            if blur_strength > 0:
                mask = mask.filter(ImageFilter.GaussianBlur(blur_strength))
            final_mask = ImageChops.multiply(mask, feather_mask_final)
        
        img.putalpha(final_mask)
        img.save(image_path, "PNG")
        return True
    except Exception as e:
        console.print(f"\n[red]图片效果应用失败 ({os.path.basename(image_path)}): {e}[/red]")
        return False

def _get_scale_filter(scaling_settings, original_dims):
    if not scaling_settings['enabled']: return None
    mode = scaling_settings['mode']
    orig_w, orig_h = original_dims
    if orig_w == 0 or orig_h == 0: return None
    target_w, target_h = -1, -1
    if mode == 'A': target_w = scaling_settings['a_width']
    elif mode == 'B': target_h = scaling_settings['b_height']
    elif mode == 'C':
        w, h = orig_w, orig_h
        limit_w, limit_h = scaling_settings['c_width'], scaling_settings['c_height']
        new_w, new_h = limit_w, h * (limit_w / w)
        if new_h > limit_h: new_h, new_w = limit_h, w * (limit_h / h)
        target_w, target_h = floor(new_w), floor(new_h)
    elif mode == 'D':
        w, h = orig_w, orig_h
        limit_w, limit_h = scaling_settings['d_width'], scaling_settings['d_height']
        new_h, new_w = limit_h, w * (limit_h / h)
        if new_w > limit_w: new_w, new_h = limit_w, h * (limit_w / w)
        target_w, target_h = floor(new_w), floor(new_h)
    elif mode == 'E':
        percent = scaling_settings['e_percent'] / 100
        target_w, target_h = floor(orig_w * percent), floor(orig_h * percent)

    if target_w > 0 and target_h > 0: return f"scale={target_w}:{target_h}"
    elif target_w > 0: return f"scale={target_w}:-1"
    elif target_h > 0: return f"scale=-1:{target_h}"
    return None

def module_1_extract(settings, console):
    input_file = settings['paths']['input']
    temp_folder = settings['paths']['temp_extraction_folder']
    os.makedirs(temp_folder, exist_ok=True)
    vf_filters = []
    scale_filter = _get_scale_filter(settings['scaling'], settings['original_dims'])
    if scale_filter: vf_filters.append(scale_filter)
    vf_filters.append(f"fps={settings['extraction']['fps']}")
    console.print("[yellow]步骤 1/3: 使用 ffmpeg 提取并缩放帧...[/yellow]")
    with console.status("[bold green]FFmpeg 正在运行...", spinner="dots"):
        output_pattern = os.path.join(temp_folder, "%03d.png")
        command = ['ffmpeg', '-i', input_file, '-vf', ",".join(vf_filters), '-start_number', '0', '-y', output_pattern]
        try: subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            console.print(f"\n[bold red]ffmpeg 提取失败！[/bold red]\n{e.stderr}"); return False
    console.print("[green]帧提取成功！[/green]")
    return True

def module_2_process(settings, console):
    if not settings['processing']['enabled']:
        console.print("[dim]步骤 2/3: 图片加工已跳过。[/dim]"); return True
    console.print("[yellow]步骤 2/3: 加工图片效果...[/yellow]")
    temp_folder = settings['paths']['temp_extraction_folder']
    image_files = sorted([f for f in os.listdir(temp_folder) if f.endswith('.png')])
    with Progress(TextColumn("[progress.description]{task.description}"), BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"), TimeRemainingColumn(), console=console) as progress:
        task = progress.add_task("[green]加工中...", total=len(image_files))
        for filename in image_files:
            image_path = os.path.join(temp_folder, filename)
            if not apply_effects_to_image(image_path, settings['processing'], console): return False
            progress.update(task, advance=1)
    console.print("[green]图片加工完成！[/green]")
    return True

def module_3_compose(settings, console):
    if not settings['composition']['enabled']:
        console.print("[dim]步骤 3/3: 画布合成已跳过。[/dim]")
        output_folder = settings['paths']['output']
        temp_folder = settings['paths']['temp_extraction_folder']
        if temp_folder != output_folder:
             os.makedirs(output_folder, exist_ok=True)
             for f in os.listdir(temp_folder): shutil.move(os.path.join(temp_folder, f), os.path.join(output_folder, f))
        return True
    console.print("[yellow]步骤 3/3: 进行画布合成...[/yellow]")
    temp_folder = settings['paths']['temp_extraction_folder']
    output_folder = settings['paths']['output']
    os.makedirs(output_folder, exist_ok=True)
    image_files = sorted([f for f in os.listdir(temp_folder) if f.endswith('.png')])
    comp_settings = settings['composition']
    canvas_w, canvas_h = comp_settings['width'], comp_settings['height']
    bg_color_rgb = hex_to_rgb(comp_settings['bg_color'])
    bg_alpha = floor(255 * (comp_settings['bg_opacity'] / 100))
    bg_color_rgba = (*bg_color_rgb, bg_alpha)
    with Progress(TextColumn("[progress.description]{task.description}"), BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"), TimeRemainingColumn(), console=console) as progress:
        task = progress.add_task("[green]合成中...", total=len(image_files))
        for filename in image_files:
            try:
                image_path = os.path.join(temp_folder, filename)
                frame_img = Image.open(image_path)
                canvas = Image.new('RGBA', (canvas_w, canvas_h), bg_color_rgba)
                paste_x = (canvas_w - frame_img.width) // 2
                paste_y = (canvas_h - frame_img.height) // 2
                canvas.paste(frame_img, (paste_x, paste_y), frame_img)
                output_path = os.path.join(output_folder, filename)
                canvas.save(output_path)
                progress.update(task, advance=1)
            except Exception as e:
                console.print(f"\n[bold red]合成图片时发生错误({filename}):[/bold red] {e}"); return False
    console.print("[green]画布合成完成！[/green]")
    return True

def generate_preview(settings):
    console = Console()
    input_file = settings['paths']['input']
    preview_temp_path = os.path.join(os.path.dirname(settings['paths']['output']), "temp_preview_image.png")
    console.print("\n[bold cyan]--- 正在生成单帧预览 ---[/bold cyan]")
    try:
        with console.status("[bold green]正在分析视频...", spinner="dots"):
            duration_str = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_file]).decode('utf-8').strip()
            duration = float(duration_str)
            middle_point = duration / 2
        console.print("[yellow]步骤 1/3: 提取预览帧...[/yellow]")
        vf_filters = []
        scale_filter = _get_scale_filter(settings['scaling'], settings['original_dims'])
        if scale_filter: vf_filters.append(scale_filter)
        extract_command = ['ffmpeg', '-ss', str(middle_point), '-i', input_file, '-vframes', '1']
        if vf_filters: extract_command.extend(['-vf', ",".join(vf_filters)])
        extract_command.extend(['-y', '-update', '1', preview_temp_path])
        subprocess.run(extract_command, check=True, capture_output=True, text=True)
        console.print("[green]预览帧提取成功！[/green]")
        if settings['processing']['enabled']:
            console.print("[yellow]步骤 2/3: 加工预览帧...[/yellow]")
            apply_effects_to_image(preview_temp_path, settings['processing'], console)
            console.print("[green]预览帧加工成功！[/green]")
        else: console.print("[dim]步骤 2/3: 图片加工已跳过。[/dim]")
        if settings['composition']['enabled']:
            console.print("[yellow]步骤 3/3: 合成预览帧...[/yellow]")
            frame_img = Image.open(preview_temp_path)
            comp_settings = settings['composition']
            canvas_w, canvas_h = comp_settings['width'], comp_settings['height']
            bg_color_rgb = hex_to_rgb(comp_settings['bg_color'])
            bg_alpha = floor(255 * (comp_settings['bg_opacity'] / 100))
            bg_color_rgba = (*bg_color_rgb, bg_alpha)
            canvas = Image.new('RGBA', (canvas_w, canvas_h), bg_color_rgba)
            paste_x = (canvas_w - frame_img.width) // 2
            paste_y = (canvas_h - frame_img.height) // 2
            canvas.paste(frame_img, (paste_x, paste_y), frame_img)
            canvas.save(preview_temp_path)
            console.print("[green]预览帧合成成功！[/green]")
        else: console.print("[dim]步骤 3/3: 画布合成已跳过。[/dim]")
        console.print(f"[green]预览生成成功！正在尝试打开...[/green]")
        try:
            if platform.system() == "Windows": os.startfile(preview_temp_path)
            elif platform.system() == "Darwin": subprocess.call(['open', preview_temp_path])
            else: subprocess.call(['xdg-open', preview_temp_path])
        except Exception:
            console.print(f"[red]自动打开失败，请手动查看文件:[/red]", preview_temp_path)
    except Exception as e:
        console.print(f"\n[bold red]预览失败！错误:[/bold red] {e}")
        if isinstance(e, subprocess.CalledProcessError): console.print(f"FFmpeg 错误信息: \n{e.stderr}")
    console.input("\n预览结束，按 Enter 返回配置菜单...")
    if os.path.exists(preview_temp_path): os.remove(preview_temp_path)

def configure_settings_interactively(initial_settings, console):
    settings = json.loads(json.dumps(initial_settings))
    def scaling_submenu():
        while True:
            clear_screen(); sca = settings['scaling']; orig_w, orig_h = settings['original_dims']
            previews = {'A': 'N/A', 'B': 'N/A', 'C': 'N/A', 'D': 'N/A', 'E': 'N/A'}
            try:
                if orig_w > 0 and orig_h > 0:
                    previews['A'] = f"-> {sca['a_width']}x{floor(orig_h * sca['a_width'] / orig_w)}"
                    previews['B'] = f"-> {floor(orig_w * sca['b_height'] / orig_h)}x{sca['b_height']}"
                    w, h = orig_w, orig_h; limit_w, limit_h = sca['c_width'], sca['c_height']; new_w, new_h = limit_w, h * (limit_w / w)
                    if new_h > limit_h: new_h, new_w = limit_h, w * (limit_h / h)
                    previews['C'] = f"-> {floor(new_w)}x{floor(new_h)}"
                    limit_w, limit_h = sca['d_width'], sca['d_height']; new_h, new_w = limit_h, w * (limit_h / h)
                    if new_w > limit_w: new_w, new_h = limit_w, h * (limit_w / w)
                    previews['D'] = f"-> {floor(new_w)}x{floor(new_h)}"
                    previews['E'] = f"-> {floor(orig_w*sca['e_percent']/100)}x{floor(orig_h*sca['e_percent']/100)}"
            except ZeroDivisionError: pass
            console.print(Panel("[bold yellow]--- 配置模块2: 图片剪裁与缩放 ---[/bold yellow]")); console.print(f"当前缩放模式: [bold green]{sca['mode']}[/bold green]")
            console.print("\n[cyan]-- 切换模式 --[/cyan]"); console.print(f"  [bold]A.[/bold] 设为「等比缩放-基于宽」"); console.print(f"  [bold]B.[/bold] 设为「等比缩放-基于高」"); console.print(f"  [bold]C.[/bold] 设为「等比缩放-基于宽-限最大高」"); console.print(f"  [bold]D.[/bold] 设为「等比缩放-基于高-限最大宽」"); console.print(f"  [bold]E.[/bold] 设为「按原始比例缩放」")
            console.print("\n[cyan]-- 修改各模式参数 --[/cyan]")
            console.print(f"  [bold]S1.[/bold] 修改模式A参数 (宽度): [yellow]{sca['a_width']}px[/yellow] [dim]{previews['A']}[/dim]"); console.print(f"  [bold]S2.[/bold] 修改模式B参数 (高度): [yellow]{sca['b_height']}px[/yellow] [dim]{previews['B']}[/dim]"); console.print(f"  [bold]S3.[/bold] 修改模式C参数 (宽,高): [yellow]{sca['c_width']}x{sca['c_height']}px[/yellow] [dim]{previews['C']}[/dim]"); console.print(f"  [bold]S4.[/bold] 修改模式D参数 (高,宽): [yellow]{sca['d_height']}x{sca['d_width']}px[/yellow] [dim]{previews['D']}[/dim]"); console.print(f"  [bold]S5.[/bold] 修改模式E参数 (百分比): [yellow]{sca['e_percent']}%[/yellow] [dim]{previews['E']}[/dim]")
            console.print("\n[bold]B.[/bold] 返回主配置菜单")
            choice = console.input("\n[bold]请选择操作:[/bold] ").upper()
            if choice == 'B': break
            try:
                if choice in ['A', 'B', 'C', 'D', 'E']: sca['mode'] = choice
                elif choice == 'S1': sca['a_width'] = int(console.input("模式A - 新宽度: "))
                elif choice == 'S2': sca['b_height'] = int(console.input("模式B - 新高度: "))
                elif choice == 'S3': w, h = map(int, console.input("模式C - 新 宽,高 (用逗号分隔): ").split(',')); sca['c_width'], sca['c_height'] = w, h
                elif choice == 'S4': h, w = map(int, console.input("模式D - 新 高,宽 (用逗号分隔): ").split(',')); sca['d_height'], sca['d_width'] = h, w
                elif choice == 'S5': sca['e_percent'] = int(console.input("模式E - 新缩放百分比 (1-200): "))
                else: console.print("[red]无效的选项。[/red]"); time.sleep(1)
            except (ValueError, IndexError): console.print("[red]输入无效，请确保格式正确。[/red]"); time.sleep(1)

    while True:
        clear_screen(); orig_w, orig_h = settings['original_dims']; ext, sca, pro, com = settings['extraction'], settings['scaling'], settings['processing'], settings['composition']
        console.print(Panel("[bold cyan]--- 请配置您的处理任务 ---[/bold cyan]"))
        console.print(Text.from_markup("\n--- [green]模块1: 图片帧提取[/green] ---")); console.print(f"  [bold]1.[/bold] [dim]源视频文件:[/dim] [cyan]{os.path.basename(settings['paths']['input'])}[/cyan]"); console.print(f"  [bold]2.[/bold] [dim]任务输出位置:[/dim] [cyan]{settings['paths']['output']}[/cyan]"); console.print(f"  [bold]3.[/bold] [dim]帧率 (FPS):[/dim] [yellow]{ext['fps']}[/yellow]"); console.print(f"     [dim]原始尺寸:[/dim] {orig_w} x {orig_h}")
        console.print(Text.from_markup("\n--- [green]模块2: 图片剪裁与缩放[/green] ---")); console.print(f"  [bold]4.[/bold] [dim]启用缩放:[/dim] {'[bold green]是[/bold green]' if sca['enabled'] else '[bold red]否[/bold red]'}")
        console.print(f"  [bold]5.[/bold] [dim]配置缩放模式与参数... (当前: {sca['mode']})[/dim]")
        console.print(Text.from_markup("\n--- [green]模块3: 图片加工[/green] ---")); console.print(f"  [bold]6.[/bold] [dim]启用图片加工:[/dim] {'[bold green]是[/bold green]' if pro['enabled'] else '[bold red]否[/bold red]'}")
        console.print(f"  [bold]7.[/bold] [dim]效果叠加顺序:[/dim] [yellow]{'标准柔和 (C-F-B)' if pro.get('order', 'C-F-B') == 'C-F-B' else '轮廓感 (C-B-F)'}[/yellow]")
        console.print(f"  [bold]8.[/bold] [dim]边缘虚化 (上/下/左/右):[/dim] [yellow]{pro['feathering']['top']}/{pro['feathering']['bottom']}/{pro['feathering']['left']}/{pro['feathering']['right']}[/yellow]")
        console.print(f"  [bold]9.[/bold] [dim]圆角比例:[/dim] [yellow]{pro['corner_radius']}%[/yellow]")
        console.print(f" [bold]10.[/bold] [dim]边缘模糊强度:[/dim] [yellow]{pro['blur_strength']}[/yellow]")
        console.print(Text.from_markup("\n--- [green]模块4: 画布合成[/green] ---")); console.print(f" [bold]11.[/bold] [dim]启用画布合成:[/dim] {'[bold green]是[/bold green]' if com['enabled'] else '[bold red]否[/bold red]'}")
        console.print(f" [bold]12.[/bold] [dim]画布大小 (宽x高):[/dim] [yellow]{com['width']}x{com['height']}[/yellow]"); console.print(f" [bold]13.[/bold] [dim]叠底画布颜色:[/dim] [yellow]{com['bg_color']}[/yellow]"); console.print(f" [bold]14.[/bold] [dim]叠底画布透明度:[/dim] [yellow]{com['bg_opacity']}%[/yellow]")
        console.print(Text.from_markup("\n--- [cyan]执行操作[/cyan] ---")); console.print("[bold]S.[/bold] 开始处理   [bold]P.[/bold] 生成预览   [bold]R.[/bold] 重置所有配置   [bold]Q.[/bold] 退出")
        choice = console.input("\n[bold]请输入编号修改配置或执行操作:[/bold] ").upper()
        if choice == 'Q': return None
        if choice == 'R': settings = json.loads(json.dumps(initial_settings)); console.print("[green]所有配置已重置为默认值。[/green]"); time.sleep(1); continue
        if choice == 'S': return settings
        if choice == 'P': generate_preview(settings); continue
        try:
            if choice == '3': ext['fps'] = int(console.input("新帧率 (1-120): "))
            elif choice == '4': sca['enabled'] = not sca['enabled']
            elif choice == '5': scaling_submenu()
            elif choice == '6': pro['enabled'] = not pro['enabled']
            elif choice == '7': pro['order'] = 'C-B-F' if pro.get('order', 'C-F-B') == 'C-F-B' else 'C-F-B'
            elif choice == '8':
                console.print("请输入新的边缘虚化值 (上,下,左,右)，用逗号分隔:")
                vals = list(map(int, console.input("> ").split(','))); pro['feathering'].update({'top': vals[0], 'bottom': vals[1], 'left': vals[2], 'right': vals[3]})
            elif choice == '9': pro['corner_radius'] = int(console.input("新圆角比例 (0-50): "))
            elif choice == '10': pro['blur_strength'] = int(console.input("新模糊强度 (0-50): "))
            elif choice == '11': com['enabled'] = not com['enabled']
            elif choice == '12': w, h = map(int, console.input("新画布宽高 (宽,高): ").split(',')); com['width'], com['height'] = w, h
            elif choice == '13': com['bg_color'] = console.input("新背景色 (#RRGGBB): ")
            elif choice == '14': com['bg_opacity'] = int(console.input("新背景透明度 (0-100): "))
            else: console.print("[red]无效的选项，请重试。[/red]"); time.sleep(1)
        except (ValueError, IndexError): console.print("[red]输入无效，请确保输入了正确的格式。[/red]"); time.sleep(1)

def main():
    console = Console()
    clear_screen()
    console.print(Panel("[bold green]      PicoPico MP4 to PNG 高级处理引擎 v5.0 (最终交付版)[/bold green]"))
    if not check_ffmpeg():
        console.print("[bold red]错误: 未找到 FFmpeg，请先安装。[/bold red]"); input("按 Enter 退出。")
        return
    input_file = None
    while not input_file:
        console.print("\n请将要转换的视频文件拖动至此，按回车确认 (输入 'Q' 退出)：")
        path = input("> ").strip().replace("'", "").strip()
        if path.upper() == 'Q': return
        if os.path.isfile(path) and path.lower().endswith('.mp4'):
            input_file = path
        else: console.print("[red]路径无效或不是 .mp4 文件，请重试。[/red]")
    console.print("\n请输入输出文件夹路径 (直接回车，则在视频所在文件夹下创建同名目录):")
    output_path = input("> ").strip().replace("'", "").strip()
    if not output_path:
        output_folder = os.path.join(os.path.dirname(input_file), os.path.splitext(os.path.basename(input_file))[0])
    else: output_folder = output_path
    temp_folder = os.path.join(output_folder, "temp_frames_PicoPico")
    orig_w, orig_h = get_video_dimensions(input_file, console)
    if not orig_w: input("按 Enter 退出。"); return
    initial_settings = {
        'paths': {'input': input_file, 'output': output_folder, 'temp_extraction_folder': temp_folder},
        'original_dims': (orig_w, orig_h),
        'extraction': {'fps': 40},
        'scaling': { 'enabled': True, 'mode': 'A', 'a_width': 750, 'b_height': 1624, 'c_width': 750, 'c_height': 1504, 'd_height': 1624, 'd_width': 750, 'e_percent': 100 },
        'processing': {'enabled': True, 'order': 'C-F-B', 'feathering': {'top': 5, 'bottom': 5, 'left': 5, 'right': 5}, 'corner_radius': 20, 'blur_strength': 10},
        'composition': {'enabled': False, 'width': 750, 'height': 1624, 'bg_color': '#000000', 'bg_opacity': 0, 'mode': 'center'}
    }
    final_settings = configure_settings_interactively(initial_settings, console)
    if not final_settings:
        console.print("\n操作已取消。"); time.sleep(1); return
    clear_screen()
    console.print(Panel(f"[bold blue]任务开始: {os.path.basename(input_file)}[/bold blue]"))
    if os.path.exists(temp_folder): shutil.rmtree(temp_folder)
    if module_1_extract(final_settings, console):
        if module_2_process(final_settings, console):
            module_3_compose(final_settings, console)
    if os.path.exists(temp_folder): shutil.rmtree(temp_folder)
    console.print(Panel(f"[bold green]所有流程执行完毕！\n输出文件夹: {final_settings['paths']['output']}[/bold green]"))
    input("\n按 Enter 键退出。")

if __name__ == "__main__":
    main()
