import os
# -*- coding: utf-8 -*-
import re
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import winreg
except ImportError:
    import _winreg as winreg


class FontTempLoader:
    def __init__(self):
        self.loaded_fonts = []
        self.debug_log = []

    @staticmethod
    def _clean(s):
        return re.sub(r'[\s\-_.]', '', s.lower())
    
    @staticmethod
    def _extract_base(s):
        s = re.sub(r'(\s*)W[3-9](\s*)', r'\1\2', s)
        s = re.sub(r'\s*(RD|SB|LT|MD|BK)\s*', '', s, flags=re.IGNORECASE)
        return s.strip()

    @staticmethod
    def is_font_installed_in_system(font_name):
        font_display_name = font_name.lower()
        keys_paths = [r"Software\Microsoft\Windows NT\CurrentVersion\Fonts", 
                     r"Software\Microsoft\Windows NT\CurrentVersion\FontSubstitutes"]
        hkeys = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]

        for key_path in keys_paths:
            for hkey_root in hkeys:
                try:
                    key = winreg.OpenKey(hkey_root, key_path, 0, winreg.KEY_READ)
                    i = 0
                    while True:
                        try:
                            val_name, _, _ = winreg.EnumValue(key, i)
                            if font_display_name in val_name.lower():
                                winreg.CloseKey(key)
                                return True
                        except EnvironmentError:
                            break
                        i += 1
                    winreg.CloseKey(key)
                except EnvironmentError:
                    continue
        return False

    def find_font_file_in_source(self, font_folder, font_name):
        if not os.path.isdir(font_folder):
            return None
        
        self.debug_log.append(f"寻找目标: {font_name}")
        clean_target = self._clean(font_name)
        base_target = self._extract_base(font_name)
        
        best_match = None
        best_score = -1
        
        for root, _, files in os.walk(font_folder):
            for f in files:
                if not (f.lower().endswith(('.ttf', '.otf', '.ttc', '.fon'))):
                    continue
                
                fname_clean = self._clean(f)
                base_fname = self._extract_base(f)
                
                score = 0
                if self._clean(base_target) == self._clean(base_fname):
                    score += 100
                elif clean_target in fname_clean:
                    score += 80
                elif base_target.lower() in base_fname.lower():
                    score += 60
                
                if score > best_score:
                    best_score = score
                    best_match = os.path.join(root, f)
        
        if best_score >= 80 and best_match:
            self.debug_log.append(f"  -> OK 找到物理文件 ({best_score}分): {os.path.basename(best_match)}")
            return best_match
            
        self.debug_log.append(f"  -> FAIL 未找到对应物理文件 (最高分: {best_score})")
        return None

    def load_fonts(self, font_folder):
        all_needed = set()
        for f in self.file_fonts.values():
            all_needed.update(f)
        
        loaded = []
        failed = []
        already_in_session = []
        reg_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"

        def is_hkcu_loaded(font_name):
            try:
                h = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ)
                for i in range(1024):
                    try:
                        val_name, _, _ = winreg.EnumValue(h, i)
                        if font_name.lower() in val_name.lower(): 
                            h.Close()
                            return True
                    except: 
                        break
                h.Close()
            except: pass
            return False

        for font_name in sorted(all_needed):
            if self.is_font_installed_in_system(font_name):
                already_in_session.append((font_name, "系统中已永久安装"))
                continue
            
            if is_hkcu_loaded(font_name):
                already_in_session.append((font_name, "当前会话已临时挂载"))
                continue

            font_file = self.find_font_file_in_source(font_folder, font_name)
            if not font_file:
                failed.append((font_name, "在字体源文件夹中未找到对应文件"))
                continue
            
            try:
                font_file = os.path.abspath(font_file)
                
                hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
                display_name = font_name
                value_name = f"{display_name} (TrueType)"
                
                winreg.SetValueEx(hkey, value_name, 0, winreg.REG_SZ, font_file)
                hkey.Close()
                
                # 【修复】使用 gdi32.dll 而不是 user32.dll
                try:
                    result = ctypes.windll.gdi32.AddFontResourceExW(font_file, 0x10, 0)
                except AttributeError:
                    result = ctypes.windll.gdi32.AddFontResourceW(font_file)
                
                if result > 0:
                    self.loaded_fonts.append((display_name, font_file))
                    loaded.append(display_name)
                else:
                    err = ctypes.get_last_error()
                    hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
                    try: 
                        winreg.DeleteValue(hkey, value_name)
                    except: pass
                    hkey.Close()
                    failed.append((font_name, f"API加载失败 (错误码:{err}))"))
                    
            except Exception as e:
                import traceback
                failed.append((font_name, f"{str(e)}\n{traceback.format_exc()}"))
        
        return loaded, failed, already_in_session

    def unload_all(self):
        if not self.loaded_fonts:
            return [], []
        
        removed = []
        failed = []
        reg_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
        
        for font_name, font_file in reversed(self.loaded_fonts):
            try:
                # 【修复】使用 gdi32.dll
                ctypes.windll.gdi32.RemoveFontResourceExW(font_file)
                
                hkey = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_WRITE)
                key_name = f"{font_name} (TrueType)"
                
                try:
                    winreg.DeleteValue(hkey, key_name)
                    removed.append(font_name)
                except WindowsError as e:
                    failed.append((font_name, str(e)))
                
                hkey.Close()
            except Exception as e:
                failed.append((font_name, str(e)))
        
        try:
            ctypes.windll.user32.SendMessageW(0xFFFF, 0x001D, 0, "FONTFAMILY|NOVECTOR_FONTFILE")
        except: pass
        
        self.loaded_fonts.clear()
        return removed, failed


class FontScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ASS/SSA \u5b57\u4f53\u626b\u63cf & \u4e34\u65f6\u52a0\u8f7d\u5de5\u5177")
        self.root.geometry("1100x800")
        self.root.minsize(900, 650)

        self.folder_var = tk.StringVar(value="\u672a\u9009\u62e9 (\u5b57\u5e55\u6587\u4ef6\u5939)")
        self.font_folder_var = tk.StringVar(value="\u672a\u9009\u62e9 (\u5b57\u4f53\u6e90\u6587\u4ef6\u5939)")

        self.temp_loader = FontTempLoader()
        self.file_fonts_dict = {}
        self.needed_for_temp_install = []
        self._scanning = False

        self._setup_style()
        self.create_widgets()

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except:
            pass

        # Color palette
        BG = "#f5f6fa"
        ACCENT = "#2c3e50"
        BLUE = "#2980b9"
        GREEN = "#27ae60"
        RED = "#e74c3c"
        LIGHT_BLUE = "#3498db"

        style.configure(".", font=("Microsoft YaHei UI", 9))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"), foreground=ACCENT)
        style.configure("Section.TLabelframe", padding=12, relief="solid", borderwidth=1)
        style.configure("Section.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"), foreground=ACCENT)
        style.configure("Action.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 6))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 6))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 9), foreground="#7f8c8d")
        style.configure("Count.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Path.TEntry", font=("Consolas", 9), fieldbackground="white")

        self.root.configure(bg=BG)
        self.style = style

    def create_widgets(self):
        PAD_X = 12
        PAD_Y = 6

        # ---- Title Banner ----
        banner = tk.Frame(self.root, bg="#2c3e50", height=50)
        banner.pack(fill=tk.X)
        banner.pack_propagate(False)
        tk.Label(banner, text="ASS/SSA \u5b57\u4f53\u626b\u63cf\u4e0e\u4e34\u65f6\u52a0\u8f7d\u5de5\u5177",
                 font=("Microsoft YaHei UI", 16, "bold"),
                 bg="#2c3e50", fg="white").pack(side=tk.LEFT, padx=16, pady=8)
        tk.Label(banner, text="\u626b\u63cf \u2192 \u68c0\u67e5\u7f3a\u5931 \u2192 \u4e34\u65f6\u5b89\u88c5 \u2192 \u4e00\u952e\u5378\u8f7d",
                 font=("Microsoft YaHei UI", 9),
                 bg="#2c3e50", fg="#95a5a6").pack(side=tk.RIGHT, padx=16, pady=8)

        # ---- Content Area ----
        content_frame = ttk.Frame(self.root, padding=(PAD_X, PAD_Y))
        content_frame.pack(fill=tk.BOTH, expand=True)

        # ---- Folder Selection Section ----
        folder_section = ttk.LabelFrame(content_frame, text="\u6587\u4ef6\u5939\u9009\u62e9",
                                        style="Section.TLabelframe")
        folder_section.pack(fill=tk.X, pady=(0, PAD_Y))

        row1 = ttk.Frame(folder_section, padding=(4, 4))
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="\u5b57\u5e55\u6587\u4ef6\u5939:", width=14).pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.folder_var, state='readonly', style="Path.TEntry").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(row1, text="\u6d4f\u89c8...", command=self.browse_subtitles_folder, style="Action.TButton").pack(
            side=tk.LEFT)

        row2 = ttk.Frame(folder_section, padding=(4, 4))
        row2.pack(fill=tk.X)
        ttk.Label(row2, text="\u5b57\u4f53\u6e90\u6587\u4ef6\u5939:", width=14).pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.font_folder_var, state='readonly', style="Path.TEntry").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        ttk.Button(row2, text="\u6d4f\u89c8...", command=self.browse_font_folder, style="Action.TButton").pack(
            side=tk.LEFT)

        # ---- Action Buttons ----
        btn_frame = ttk.Frame(content_frame, padding=(4, PAD_Y))
        btn_frame.pack(fill=tk.X)

        self.scan_btn = ttk.Button(btn_frame, text="\U0001f50d \u626b\u63cf\u5b57\u5e55\u5b57\u4f53",
                                   command=self.start_scan, style="Action.TButton")
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.load_btn = ttk.Button(btn_frame, text="\u25b6 \u4e34\u65f6\u52a0\u8f7d\u7f3a\u5931\u5b57\u4f53",
                                   command=self.temp_load_fonts, state=tk.DISABLED, style="Action.TButton")
        self.load_btn.pack(side=tk.LEFT, padx=8)

        self.unload_btn = ttk.Button(btn_frame, text="\u2716 \u4e00\u952e\u5378\u8f7d\u6240\u6709\u4e34\u65f6\u5b57\u4f53",
                                     command=self.temp_unload_all, state=tk.DISABLED, style="Action.TButton")
        self.unload_btn.pack(side=tk.LEFT, padx=8)

        # ---- Loaded Fonts Display ----
        loaded_section = ttk.LabelFrame(content_frame, text="\U0001f4cb \u5df2\u4e34\u65f6\u52a0\u8f7d\u7684\u5b57\u4f53",
                                        style="Section.TLabelframe")
        loaded_section.pack(fill=tk.X, pady=(PAD_Y, PAD_Y))

        self.loaded_fonts_text = scrolledtext.ScrolledText(
            loaded_section, wrap=tk.WORD, font=("Consolas", 9),
            height=4, bg="#fafbfc", fg="#2c3e50",
            state=tk.DISABLED, relief="flat", borderwidth=0)
        self.loaded_fonts_text.pack(fill=tk.X, padx=2, pady=2)

        # ---- Progress Bar ----
        self.progress = ttk.Progressbar(content_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress.pack(fill=tk.X, pady=(0, PAD_Y))

        # ---- Report Section ----
        report_section = ttk.LabelFrame(content_frame, text="\U0001f4c4 \u62a5\u544a",
                                        style="Section.TLabelframe")
        report_section.pack(fill=tk.BOTH, expand=True, pady=(0, PAD_Y))

        self.text_area = scrolledtext.ScrolledText(
            report_section, wrap=tk.WORD, font=("Consolas", 10),
            bg="#fafbfc", relief="flat", borderwidth=0)
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # ---- Status Bar ----
        status_frame = tk.Frame(self.root, bg="#ecf0f1", height=28)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        status_frame.pack_propagate(False)

        self.status_var = tk.StringVar(value="\u5c31\u7eea")
        self.status_icon = tk.Label(status_frame, text="\U0001f7e2", font=("Segoe UI", 10),
                                    bg="#ecf0f1", fg="#27ae60")
        self.status_icon.pack(side=tk.LEFT, padx=(16, 2), pady=4)
        tk.Label(status_frame, textvariable=self.status_var, font=("Microsoft YaHei UI", 9),
                 bg="#ecf0f1", fg="#7f8c8d").pack(side=tk.LEFT, pady=4)

        self.load_count_label = tk.Label(status_frame, text="\u5df2\u52a0\u8f7d\u5b57\u4f53: 0",
                                         font=("Microsoft YaHei UI", 9, "bold"),
                                         bg="#ecf0f1", fg="#2980b9")
        self.load_count_label.pack(side=tk.RIGHT, padx=16, pady=4)

        # Initialize loaded fonts display
        self.update_loaded_fonts_display()

    def browse_subtitles_folder(self):
        folder = filedialog.askdirectory(title="\u8bf7\u9009\u62e9\u5305\u542b ASS/SSA \u5b57\u5e55\u7684\u6587\u4ef6\u5939")
        if not folder:
            return
        old_folder = self.folder_var.get()
        if "\u672a\u9009\u62e9" not in old_folder and old_folder != folder:
            msg = f"\u5b57\u5e55\u6587\u4ef6\u5939\u5df2\u53d8\u66f4:\n\n\u65b0: {folder}\n\u65e7: {old_folder}\n\n\u662f\u5426\u9700\u8981\u91cd\u65b0\u626b\u63cf\u5b57\u4f53\uff1f"
            if messagebox.askyesno("\u91cd\u65b0\u626b\u63cf\uff1f", msg):
                self.folder_var.set(folder)
                self.start_scan()
                return
        self.folder_var.set(folder)

    def browse_font_folder(self):
        folder = filedialog.askdirectory(title="\u8bf7\u9009\u62e9\u5b57\u4f53\u6e90\u6587\u4ef6\u5939\uff08\u5b58\u653e .ttf/.otf \u7b49\uff09")
        if folder:
            self.font_folder_var.set(folder)

    def get_fonts_from_file(self, filepath):
        fonts = set()
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as fh:
                content = fh.read()
        except UnicodeDecodeError:
            with open(filepath, 'r', encoding='gbk') as fh:
                content = fh.read()

        style_pattern = r'\[V4\+?\s*Styles\](.*?)(?=\[|$)'
        matches = re.findall(style_pattern, content, re.IGNORECASE | re.DOTALL)

        for section_content in matches:
            lines = section_content.strip().split('\n')
            fmt_idx = -1; font_idx = -1

            for i, line in enumerate(lines):
                if line.strip().upper().startswith('FORMAT'):
                    parts = [p.strip() for p in line.split(',')]
                    fmt_idx = i
                    try:
                        font_idx = parts.index('Fontname')
                    except ValueError:
                        pass
                    break

            if fmt_idx == -1:
                continue
            for line in lines[fmt_idx+1:]:
                if not line.strip() or line.startswith('[') or line.upper().startswith('FORMAT'):
                    break
                parts = [p.strip() for p in line.split(',')]
                if len(parts) > font_idx:
                    f = parts[font_idx].strip('"').strip("'")
                    if f:
                        fonts.add(f)

        return fonts

    def start_scan(self):
        folder = self.folder_var.get()
        if "\u672a\u9009\u62e9" in folder:
            messagebox.showerror("\u9519\u8bef", "\u8bf7\u5148\u9009\u62e9\u5b57\u5e55\u6587\u4ef6\u5939\uff01")
            return

        if self._scanning:
            return
        self._scanning = True

        files = []
        for root, _, fnames in os.walk(folder):
            for f in fnames:
                if f.lower().endswith(('.ass', '.ssa')):
                    files.append(os.path.join(root, f))

        if not files:
            messagebox.showinfo("\u63d0\u793a", "\u8be5\u6587\u4ef6\u5939\u4e0b\u6ca1\u6709\u627e\u5230 .ass \u6216 .ssa \u6587\u4ef6\u3002")
            self._scanning = False
            return

        self.progress['value'] = 0
        self.root.update()

        self.file_fonts_dict.clear()
        all_fonts = set()
        total = len(files)

        for i, fp in enumerate(files):
            fns = self.get_fonts_from_file(fp)
            if fns:
                self.file_fonts_dict[os.path.relpath(fp, folder)] = sorted(fns)
                all_fonts.update(fns)
            self.progress['value'] = (i + 1) / total * 100
            self.root.update()

        self.needed_for_temp_install = []
        for font_name in sorted(all_fonts):
            if not FontTempLoader.is_font_installed_in_system(font_name):
                self.needed_for_temp_install.append(font_name)

        self.temp_loader.file_fonts = {fp: fns for fp, fns in self.file_fonts_dict.items()}
        self.temp_loader.debug_log.clear()

        if not self.font_folder_var.get().startswith("\u672a\u9009\u62e9"):
            for font_name in self.needed_for_temp_install:
                self.temp_loader.find_font_file_in_source(self.font_folder_var.get(), font_name)

        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("\u626b\u63cf\u7ed3\u679c")
        report_lines.append("=" * 60)
        report_lines.append(f"\u76ee\u6807\u6587\u4ef6\u5939: {folder}")
        report_lines.append(f"\u6587\u4ef6\u6570\u91cf:   {len(files)} \u4e2a")
        report_lines.append(f"\u53d1\u73b0\u5b57\u4f53:   {len(all_fonts)} \u79cd")
        report_lines.append("")

        if self.needed_for_temp_install:
            report_lines.append(f"\u9700\u8981\u4e34\u65f6\u52a0\u8f7d\u7684\u5b57\u4f53 ({len(self.needed_for_temp_install)} \u79cd):")
            report_lines.append("-" * 50)
            for m in self.needed_for_temp_install:
                font_folder = self.font_folder_var.get()
                match_status = "[\u672a\u63d0\u4f9b\u5b57\u4f53\u6e90\u6587\u4ef6\u5939]"
                if not font_folder.startswith("\u672a\u9009\u62e9"):
                    f_file = self.temp_loader.find_font_file_in_source(font_folder, m)
                    match_status = "[\u5df2\u5339\u914d\u5230\u6587\u4ef6\uff0c\u70b9\u51fb\u52a0\u8f7d\u5373\u53ef\u751f\u6548]" if f_file else "[\u5b57\u4f53\u6e90\u4e2d\u627e\u4e0d\u5230\u5bf9\u5e94\u6587\u4ef6]"
                report_lines.append(f"  - {m}  {match_status}")
        else:
            report_lines.append("\u6240\u6709\u5b57\u4f53\u5747\u5df2\u5b89\u88c5\u5728\u7cfb\u7edf\u4e2d\uff0c\u65e0\u9700\u4e34\u65f6\u5b89\u88c5\u3002")

        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(tk.END, "\n".join(report_lines))

        if self.needed_for_temp_install:
            self.load_btn.config(state=tk.NORMAL)
            self.status_var.set(f"\u53d1\u73b0 {len(self.needed_for_temp_install)} \u79cd\u5b57\u4f53\u9700\u8981\u4e34\u65f6\u5b89\u88c5")

        self._scanning = False

    def update_loaded_fonts_display(self):
        self.loaded_fonts_text.config(state=tk.NORMAL)
        self.loaded_fonts_text.delete(1.0, tk.END)
        loaded = self.temp_loader.loaded_fonts
        if not loaded:
            self.loaded_fonts_text.insert(tk.END, "  (\u5c1a\u672a\u4e34\u65f6\u52a0\u8f7d\u4efb\u4f55\u5b57\u4f53)")
        else:
            for name, path in loaded:
                short_path = path if len(path) <= 100 else "..." + path[-97:]
                self.loaded_fonts_text.insert(tk.END, f"  \u2714 {name}\n     \u2514 {short_path}\n")
        self.loaded_fonts_text.config(state=tk.DISABLED)

    def temp_load_fonts(self):
        font_folder = self.font_folder_var.get()
        if "\u672a\u9009\u62e9" in font_folder:
            messagebox.showerror("\u9519\u8bef", "\u8bf7\u5148\u9009\u62e9\u5b57\u4f53\u6e90\u6587\u4ef6\u5939\uff01")
            return

        if not self.needed_for_temp_install:
            messagebox.showinfo("\u63d0\u793a", "\u6ca1\u6709\u9700\u8981\u4e34\u65f6\u52a0\u8f7d\u7684\u5b57\u4f53\u3002")
            return

        confirm_lines = []
        confirm_lines.append(f"\u5b57\u4f53\u6e90\u6587\u4ef6\u5939: {font_folder}")
        confirm_lines.append(f"\u5373\u5c06\u4e34\u65f6\u5b89\u88c5 {len(self.needed_for_temp_install)} \u79cd\u5b57\u4f53:\n")
        for i, font_name in enumerate(self.needed_for_temp_install, 1):
            f_file = self.temp_loader.find_font_file_in_source(font_folder, font_name)
            status = os.path.basename(f_file) if f_file else "[\u672a\u627e\u5230\u6587\u4ef6]"
            confirm_lines.append(f"  {i}. {font_name}  ->  {status}")
        confirm_lines.append(f"\n\u786e\u5b9a\u8981\u4e34\u65f6\u5b89\u88c5\u4ee5\u4e0a\u5b57\u4f53\u5417\uff1f")

        if not messagebox.askyesno("\u786e\u8ba4\u5b89\u88c5", "\n".join(confirm_lines)):
            return

        loaded, failed, already_installed = self.temp_loader.load_fonts(font_folder)

        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("\u4e34\u65f6\u5b57\u4f53\u52a0\u8f7d\u7ed3\u679c")
        report_lines.append("=" * 60)
        report_lines.append(f"\u5b57\u4f53\u6e90\u6587\u4ef6\u5939: {font_folder}")
        report_lines.append("")

        if already_installed:
            report_lines.append(f"\u65e0\u9700\u91cd\u590d\u5904\u7406\u7684\u5b57\u4f53 ({len(already_installed)}):")
            for name, reason in already_installed:
                report_lines.append(f"    ~ {name} ({reason})")
            report_lines.append("")

        if loaded:
            report_lines.append("\u6210\u529f\u52a0\u8f7d:")
            for name in loaded:
                font_file = self.temp_loader.find_font_file_in_source(font_folder, name)
                report_lines.append(f"    + {name} ({os.path.basename(font_file) if font_file else ''})")
            report_lines.append("")

        if failed:
            report_lines.append("\u52a0\u8f7d\u5931\u8d25:")
            for name, reason in failed:
                report_lines.append(f"    - {name} ({reason})")
            report_lines.append("")

        self.text_area.insert(tk.END, "\n" + "\n".join(report_lines))

        count = len(self.temp_loader.loaded_fonts)
        self.load_count_label.config(text=f"\u5df2\u52a0\u8f7d\u5b57\u4f53: {count}", fg="#27ae60")
        self.unload_btn.config(state=tk.NORMAL if count > 0 else tk.DISABLED)
        self.status_var.set(f"\u5f53\u524d\u5df2\u6709 {count} \u79cd\u5b57\u4f53\u751f\u6548\uff0c\u8bf7\u91cd\u542f\u64ad\u653e\u5668\u67e5\u770b\u6548\u679c")
        self.update_loaded_fonts_display()
        self.status_icon.config(text="\U0001f7e2", fg="#27ae60")

    def temp_unload_all(self):
        if not self.temp_loader.loaded_fonts:
            return

        result = messagebox.askyesno("\u786e\u8ba4", f"\u5373\u5c06\u5378\u8f7d {len(self.temp_loader.loaded_fonts)} \u79cd\u4e34\u65f6\u5b57\u4f53\n\u662f\u5426\u7ee7\u7eed\uff1f")
        if result:
            removed, failed = self.temp_loader.unload_all()

            report_lines = []
            report_lines.append("=" * 60)
            report_lines.append("\u4e00\u952e\u5378\u8f7d\u7ed3\u679c")
            report_lines.append("=" * 60)
            report_lines.append(f"\u6210\u529f\u79fb\u9664: {len(removed)} \u79cd\u5b57\u4f53")
            for name in removed:
                report_lines.append(f"  - {name}")

            self.text_area.insert(tk.END, "\n" + "\n".join(report_lines))
            self.load_count_label.config(text="\u5df2\u52a0\u8f7d\u5b57\u4f53: 0", fg="#2980b9")
            self.unload_btn.config(state=tk.DISABLED)
            self.status_var.set("\u6240\u6709\u4e34\u65f6\u5b57\u4f53\u5df2\u5378\u8f7d\uff0c\u7cfb\u7edf\u6062\u590d\u539f\u72b6")
            self.update_loaded_fonts_display()
            self.status_icon.config(text="\U0001f7e2", fg="#27ae60")

if __name__ == "__main__":
    root = tk.Tk()
    app = FontScannerApp(root)
    root.mainloop()
