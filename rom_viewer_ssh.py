import os
import io
import threading
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

import paramiko
from PIL import Image, ImageTk


# ── База платформ Trimui Smart Pro ─────────────────────────────
PLATFORM_MAP = {
    "FC": "NES (Famicom)",
    "NES": "NES",
    "SFC": "SNES (Super Famicom)",
    "SNES": "SNES",
    "MD": "Mega Drive (Genesis)",
    "GENESIS": "Mega Drive (Genesis)",
    "GB": "Game Boy",
    "GBC": "Game Boy Color",
    "GBA": "Game Boy Advance",
    "N64": "Nintendo 64",
    "NDS": "Nintendo DS",
    "PSP": "PlayStation Portable",
    "PS1": "PlayStation",
    "PSX": "PlayStation",
    "ATARI": "Atari 2600",
    "ATARI2600": "Atari 2600",
    "ATARI5200": "Atari 5200",
    "ATARI7800": "Atari 7800",
    "LYNX": "Atari Lynx",
    "NGP": "Neo Geo Pocket",
    "NGC": "Neo Geo Pocket Color",
    "NEOGEO": "Neo Geo",
    "MS": "Master System",
    "SMS": "Master System",
    "GG": "Game Gear",
    "PCE": "PC Engine (TurboGrafx-16)",
    "TG16": "PC Engine (TurboGrafx-16)",
    "WSC": "WonderSwan Color",
    "WS": "WonderSwan",
    "VB": "Virtual Boy",
    "32X": "Mega Drive 32X",
    "SCD": "Sega CD",
    "SATURN": "Sega Saturn",
    "DREAMCAST": "Dreamcast",
    "FBNEO": "FinalBurn Neo (Arcade)",
    "FBA": "FinalBurn Alpha (Arcade)",
    "MAME": "MAME (Arcade)",
    "CPS1": "CPS1 (Arcade)",
    "CPS2": "CPS2 (Arcade)",
    "CPS3": "CPS3 (Arcade)",
    "NEOCD": "Neo Geo CD",
    "PCECD": "PC Engine CD",
    "SFX": "Super FX",
    "MSX": "MSX",
    "MSX2": "MSX2",
    "COLECO": "ColecoVision",
    "INTELLIVISION": "Intellivision",
    "VECTREX": "Vectrex",
    "ODYSSEY2": "Magnavox Odyssey 2",
    "FAIRCHILD": "Fairchild Channel F",
    "AMIGA": "Amiga",
    "ATARI800": "Atari 800",
    "ATARIST": "Atari ST",
    "COMMODORE64": "Commodore 64",
    "ZX81": "ZX81",
    "ZXS": "ZX Spectrum",
    "DOS": "DOS",
    "SCUMMVM": "ScummVM",
    "OPENBOR": "OpenBOR",
    "PSPMINIS": "PSP Minis",
    "PS2": "PlayStation 2",
    "N64DD": "Nintendo 64DD",
    "SG1000": "Sega SG-1000",
}

# Папки, где обычно лежат обложки на Trimui Smart Pro
COVER_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]
ROM_EXTS = {
    ".nes", ".fc", ".sfc", ".smc", ".fig",
    ".md", ".gen", ".sms", ".gg",
    ".gb", ".gbc", ".gba",
    ".n64", ".z64", ".v64", ".ndd",
    ".nds", ".ids",
    ".iso", ".cso", ".pbp", ".bin", ".img", ".ecm",
    ".pce", ".tg16", ".ngp", ".ngc",
    ".ws", ".wsc", ".lyx", ".lbyn",
    ".vec", ".col", ".int", ".o2",
    ".d64", ".t64", ".tap", ".prg",
    ".msx", ".mx2", ".cas", ".rom",
    ".zip", ".7z",
    ".scummvm",
    ".fds", ".gbh", ".pok",
    ".smd", ".32x", ".cue",
    ".m3u", ".sh",
}

DEFAULT_ROM_PATH = "/mnt/sdcard/mmcblk1p1/Roms"


class SSHConnection:
    """Обёртка над paramiko для удобной работы."""

    def __init__(self, host, username="root", password="", callback=None):
        self.host = host
        self.username = username
        self.password = password
        self.client = None
        self.callback = callback

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            hostname=self.host,
            username=self.username,
            password=self.password,
            timeout=10,
            look_for_keys=False,   # ← не ищем ключи на компе
            allow_agent=False,     # ← не обращаемся к ssh-agent
        )
        if self.callback:
            self.callback(f"Подключено к {self.host}")

    def exec(self, command, timeout=10):
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            stdout.channel.settimeout(timeout)
            return stdout.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""


    def list_dir(self, path):
        sftp = self.client.open_sftp()
        try:
            entries = sftp.listdir(path)
            return entries
        finally:
            sftp.close()

    def stat_file(self, path):
        sftp = self.client.open_sftp()
        try:
            attr = sftp.stat(path)
            return attr.st_size, attr.st_mtime, getattr(attr, 'st_ctime', 0)
        finally:
            sftp.close()

    def read_file_bytes(self, path, max_bytes=16 * 1024 * 1024):
        sftp = self.client.open_sftp()
        try:
            with sftp.file(path, "rb") as f:
                data = f.read(max_bytes)
            return data
        finally:
            sftp.close()

    def read_file_md5(self, path, max_bytes=16 * 1024 * 1024):
        data = self.read_file_bytes(path, max_bytes)
        return hashlib.md5(data).hexdigest()

    def close(self):
        if self.client:
            self.client.close()
            self.client = None


class RomViewerSSH(ttk.Frame):
    """Окно просмотра ROM-ов по SSH."""

    def __init__(self, parent, root_window, host, username="root",
                 password="", rom_path=None, imgs_path=None):
        super().__init__(parent) 
        self.parent = parent  # ← это фрейм вкладки из Notebook
        self.root_window = root_window
    

        self.host = host
        self.username = username
        self.password = password
        self.rom_path = rom_path or DEFAULT_ROM_PATH
        self.imgs_path = imgs_path

        self.ssh = None
        self.roms = []
        self.filtered = []
        self.cover_cache = {}
        self.cover_size = 300
        self.current_cover_path = None
        self.cover_photo = None
        self._alive = True
        self.current_rom = None

        self._build_ui()
        self.parent.after(100, self._connect_and_scan)

    # ── Интерфейс ────────────────────────────────────────────────

    def _build_ui(self):
        # Статус-бар — на self, отдельно от main_frame
        bottom_bar = ttk.Frame(self)
        bottom_bar.pack(fill="x", side="bottom")

        self.progress = ttk.Progressbar(bottom_bar, mode="determinate", maximum=100)
        self.progress.pack(fill="x")

        self.lbl_status = ttk.Label(bottom_bar, text="Подключение…",
                                     anchor="w", relief="sunken", padding=4)
        self.lbl_status.pack(fill="x")

        # Контейнер для всего, кроме статус-бара
        main_frame = ttk.Frame(self)
        main_frame.pack(fill="both", expand=True)

        # Верхняя панель
        top = ttk.Frame(main_frame, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Хост:").pack(side="left")
        self.lbl_host = ttk.Label(top, text=f"{self.host}",
                                 foreground="gray")
        self.lbl_host.pack(side="left", padx=(4, 16))

        ttk.Label(top, text="ROM-ы:").pack(side="left")
        self.lbl_path = ttk.Label(top, text=self.rom_path,
                                  foreground="gray")
        self.lbl_path.pack(side="left", padx=(4, 16))

        ttk.Label(top, text="Обложки:").pack(side="left")
        self.imgs_var = tk.StringVar(value=self.imgs_path or "")
        imgs_entry = ttk.Entry(top, textvariable=self.imgs_var, width=35)
        imgs_entry.pack(side="left", padx=(4, 4))

        self.btn_rescan = ttk.Button(top, text="🔄 Обновить",
                                     command=self._connect_and_scan)
        self.btn_rescan.pack(side="right")

        # Фильтры
        filt = ttk.Frame(main_frame, padding=(8, 0, 8, 4))
        filt.pack(fill="x")

        ttk.Label(filt, text="Платформа:").pack(side="left")
        self.cmb_platform = ttk.Combobox(filt, width=25, state="readonly")
        self.cmb_platform.pack(side="left", padx=(4, 12))
        self.cmb_platform.bind("<<ComboboxSelected>>", self._apply_filters)

        ttk.Label(filt, text="Поиск:").pack(side="left")
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_: self._apply_filters())
        ttk.Entry(filt, textvariable=self.var_search, width=30).pack(
            side="left", padx=(4, 12))

        self.lbl_count = ttk.Label(filt, text="", foreground="gray")
        self.lbl_count.pack(side="right")

        # Основная область — две колонки
        body = ttk.PanedWindow(main_frame, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=4)

        # Левая — список
        left = ttk.Frame(body)
        body.add(left, weight=2)

        cols = ("name", "platform", "size")
        self.tree = ttk.Treeview(left, columns=cols, show="headings",
                                selectmode="browse")
        self.tree.heading("name", text="Название")
        self.tree.heading("platform", text="Платформа")
        self.tree.heading("size", text="Размер")
        self.tree.column("name", width=320, anchor="w")
        self.tree.column("platform", width=180, anchor="w")
        self.tree.column("size", width=90, anchor="e")
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Правая — карточка
        right = ttk.Frame(body, padding=10)
        body.add(right, weight=1)

        # Grid: обложка (фикс), инфо (растягивается), кнопки (фикс)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=0)

        # Обложка — динамический контейнер
        self.cover_frame = ttk.Frame(right, width=300, height=300)
        self.cover_frame.grid(row=0, column=0, pady=(0, 10), sticky="n")
        self.cover_frame.pack_propagate(False)

        self.lbl_cover = ttk.Label(self.cover_frame, text="Обложка\nне найдена",
                                   anchor="center", justify="center")
        self.lbl_cover.pack(expand=True, fill="both")

        right.bind("<Configure>", self._on_right_configure)

        # Информация — с прокруткой
        info_frame = ttk.LabelFrame(right, text="Информация", padding=2)
        info_frame.grid(row=1, column=0, sticky="nsew")
        info_frame.grid_propagate(False)
        info_frame.grid_rowconfigure(0, weight=1)
        info_frame.grid_columnconfigure(0, weight=1)

        # Canvas + Scrollbar
        info_canvas = tk.Canvas(info_frame, highlightthickness=0,
                                bg="#f0f0f0")
        info_scroll = ttk.Scrollbar(info_frame, orient="vertical",
                                    command=info_canvas.yview)
        info_canvas.configure(yscrollcommand=info_scroll.set)

        info_scroll.grid(row=0, column=1, sticky="ns")
        info_canvas.grid(row=0, column=0, sticky="nsew")

        # Внутренний фрейм для строк
        info_inner = ttk.Frame(info_canvas)
        info_window = info_canvas.create_window((0, 0), window=info_inner,
                                                anchor="nw")

        # Обновляем scrollregion при добавлении виджетов
        def _on_inner_configure(event):
            info_canvas.configure(scrollregion=info_canvas.bbox("all"))

        info_inner.bind("<Configure>", _on_inner_configure)

        # Растягиваем inner по ширине canvas
        def _on_canvas_configure(event):
            info_canvas.itemconfig(info_window, width=event.width)

        info_canvas.bind("<Configure>", _on_canvas_configure)

        # Прокрутка колесом мыши
        def _on_mousewheel(event):
            info_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        info_canvas.bind("<Enter>", lambda e: info_canvas.bind_all(
            "<MouseWheel>", _on_mousewheel))
        info_canvas.bind("<Leave>", lambda e: info_canvas.unbind_all(
            "<MouseWheel>"))

        self.info_labels = {}
        for key in ("name", "platform", "filename", "format", "size",
                     "path", "modified", "md5"):
            row = ttk.Frame(info_inner)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=self._info_label_text(key) + ":",
                      width=14, anchor="w").pack(side="left")
            val = ttk.Label(row, text="—", wraplength=230, anchor="w",
                            justify="left")
            val.pack(side="left", fill="x", expand=True)
            self.info_labels[key] = val


        # Кнопки — сетка 3×2 + 1 кнопка на всю ширину (или 4×2, если хочешь 4 ряда)
        btns = ttk.Frame(right, padding=(0, 10, 0, 0))
        btns.grid(row=2, column=0, sticky="ew")

        # Вес колонок одинаковый
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        # Опционально: чтобы все строки были одинаковой высоты, можно задать weight для строк
        btns.rowconfigure(0, weight=0)
        btns.rowconfigure(1, weight=0)
        btns.rowconfigure(2, weight=0)  # если 3 ряда
        # btns.rowconfigure(3, weight=0)  # если будет 4‑й ряд

        # Row 0
        self.btn_copy = ttk.Button(btns, text="📋 Копировать путь",
                                command=self._copy_path)
        self.btn_copy.grid(row=0, column=0, padx=(0, 4), pady=2, sticky="ew")

        self.btn_download = ttk.Button(btns, text="📂 Скачать на ПК",
                                    command=self._download_rom)
        self.btn_download.grid(row=0, column=1, padx=(4, 0), pady=2, sticky="ew")

        # Row 1
        self.btn_pack = ttk.Button(btns, text="📦 Скачать ПАК",
                                command=self._download_pack)
        self.btn_pack.grid(row=1, column=0, padx=(0, 4), pady=2, sticky="ew")

        self.btn_cover = ttk.Button(btns, text="🖼 Изменить обложку",
                                    command=self._change_cover)
        self.btn_cover.grid(row=1, column=1, padx=(4, 0), pady=2, sticky="ew")

        # Row 2 — теперь обе кнопки с одинаковым pady сверху и снизу
        self.btn_dl_cover = ttk.Button(btns, text="💾 Скачать обложку",
                                    command=self._download_cover)
        self.btn_dl_cover.grid(row=2, column=0, padx=(0, 4), pady=2, sticky="ew")

        self.btn_delete = ttk.Button(btns, text="🗑 Удалить ROM",
                                    command=self._delete_rom)
        self.btn_delete.grid(row=2, column=1, padx=(4, 0), pady=2, sticky="ew")


    # ── Подключение и сканирование ───────────────────────────────

    def _connect_and_scan(self):
        self.btn_rescan.config(state="disabled")
        self.lbl_status.config(text="Подключение…")
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        if not self._alive:
            return
        try:
            if self.ssh:
                self.ssh.close()
            self.ssh = SSHConnection(
                self.host, self.username, self.password,
                callback=lambda msg: self._set_status(msg),
            )
            self.ssh.connect()
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror(
                "Ошибка SSH", f"Не удалось подключиться:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(
                text=f"Ошибка: {err}"))
            self.parent.after(0, lambda: self.btn_rescan.config(state="normal"))
            return

        self._set_status("Сканирование папок…")
        self.roms = []

        try:
            platform_dirs = self.ssh.list_dir(self.rom_path)
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror(
                "Ошибка", f"Не удалось прочитать папку {self.rom_path}:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(text=f"Ошибка: {err}"))
            self.parent.after(0, lambda: self.btn_rescan.config(state="normal"))
            return

        # ── Вычисляем путь к обложкам ────────────────────────────
        # Берём из поля ввода, если заполнено; иначе вычисляем автоматически
        user_imgs = self.imgs_var.get().strip()
        if user_imgs:
            imgs_root = user_imgs.rstrip("/")
        else:
            mount_root = self.rom_path
            if mount_root.endswith("/Roms"):
                mount_root = mount_root[:-5]
            elif "/Roms" in mount_root:
                mount_root = mount_root.rsplit("/Roms", 1)[0]
            imgs_root = f"{mount_root}/Imgs"

        # Проверяем, существует ли папка обложек
        has_imgs_dir = False
        try:
            self.ssh.list_dir(imgs_root)
            has_imgs_dir = True
        except Exception:
            pass

        for i, pdir in enumerate(platform_dirs):
            full = f"{self.rom_path}/{pdir}"

            platform_name = PLATFORM_MAP.get(pdir.upper(), pdir)
            self._set_status(f"Сканирование… [{i + 1}/{len(platform_dirs)}] {pdir}")

            try:
                files = self.ssh.list_dir(full)
            except Exception:
                continue

            rom_files = []
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in ROM_EXTS:
                    rom_files.append(f)

            # ── Поиск обложек: только в Imgs/<platform_dir>/ ──────
            cover_map = {}
            if has_imgs_dir:
                imgs_platform_path = f"{imgs_root}/{pdir}"
                try:
                    img_files = self.ssh.list_dir(imgs_platform_path)
                    for sf in img_files:
                        ext = os.path.splitext(sf)[1].lower()
                        if ext in COVER_EXTS:
                            base = os.path.splitext(sf)[0]
                            cover_map[base] = f"{imgs_platform_path}/{sf}"
                except Exception:
                    pass

            # ── Сбор ROM-ов ────────────────────────────────────────
            for rf in rom_files:
                rom_full = f"{full}/{rf}"
                base = os.path.splitext(rf)[0]
                cover_path = cover_map.get(base)
                try:
                    size, mtime, _ = self.ssh.stat_file(rom_full)
                except Exception:
                    size, mtime = 0, 0


                self.roms.append({
                    "name": base,
                    "platform": platform_name,
                    "platform_dir": pdir,
                    "filename": rf,
                    "format": os.path.splitext(rf)[1].lower(),
                    "size": size,
                    "path": rom_full,
                    "modified": mtime,
                    "cover": cover_path,
                })

        platforms = sorted(set(r["platform"] for r in self.roms))
        if not self._alive:
            return
        self.parent.after(0, lambda: self._on_scan_done(platforms))

    def _change_cover(self):
        if not self.current_rom:
            return
        rom = self.current_rom

        local_path = filedialog.askopenfilename(
            parent=self.root_window,
            title="Выберите новую обложку",
            filetypes=[("Изображения", "*.png *.jpg *.jpeg *.bmp *.webp")]
        )
        if not local_path:
            return

        # Вычисляем удалённый путь: Imgs/<platform_dir>/<game_name>.png
        imgs_root = self.imgs_var.get().strip()
        if not imgs_root:
            mount_root = self.rom_path
            if mount_root.endswith("/Roms"):
                mount_root = mount_root[:-5]
            elif "/Roms" in mount_root:
                mount_root = mount_root.rsplit("/Roms", 1)[0]
            imgs_root = f"{mount_root}/Imgs"

        platform_dir = rom["platform_dir"]
        game_name = rom["name"]
        remote_cover_path = f"{imgs_root}/{platform_dir}/{game_name}.png"

        self.lbl_status.config(text=f"Загрузка обложки на консоль…")
        self.btn_cover.config(state="disabled")

        threading.Thread(
            target=self._change_cover_thread,
            args=(local_path, remote_cover_path, rom),
            daemon=True
        ).start()

    def _change_cover_thread(self, local_path, remote_path, rom):
        if not self._alive:
            return
        cover_path = rom.get("cover")
        temp_png = None
        upload_path = local_path

        try:
            sftp = self.ssh.client.open_sftp()

            ext = os.path.splitext(local_path)[1].lower()
            if ext != ".png":
                try:
                    img = Image.open(local_path)
                    img = img.convert("RGBA")
                    dir_name = os.path.dirname(local_path) or "."
                    temp_png = os.path.join(dir_name, "_cover_tmp.png")
                    img.save(temp_png, "PNG")
                    upload_path = temp_png
                except Exception:
                    pass  # если конвертация не удалась — грузим как есть

            sftp.put(upload_path, remote_path)
            sftp.close()

            # Обновляем кэш и сбрасываем старый
            if cover_path in self.cover_cache:
                del self.cover_cache[cover_path]
            rom["cover"] = remote_path
            self.parent.after(0, lambda: self._show_cover_from_local(local_path))
            self.parent.after(0, lambda: self.lbl_status.config(text="✅ Обложка обновлена"))

        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось загрузить обложку:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(text=f"❌ Ошибка: {err}"))
        finally:
            self.parent.after(0, lambda: self.btn_cover.config(state="normal"))
            # Гарантированно удаляем временный файл, если он был создан
            if temp_png and os.path.exists(temp_png):
                try:
                    os.remove(temp_png)
                except OSError:
                    pass


    def _on_scan_done(self, platforms):
        if not self._alive:
            return
        self.cmb_platform["values"] = ["Все"] + platforms
        self.cmb_platform.set("Все")
        self._apply_filters()
        self.lbl_status.config(text=f"Готово: {len(self.roms)} ROM-ов найдено")
        self.btn_rescan.config(state="normal")

    # ── Фильтрация и список ──────────────────────────────────────

    def _apply_filters(self, *_):
        plat = self.cmb_platform.get()
        search = self.var_search.get().lower().strip()
        self.filtered = []
        for r in self.roms:
            if plat != "Все" and r["platform"] != plat:
                continue
            if search and search not in r["name"].lower():
                continue
            self.filtered.append(r)

        self.tree.delete(*self.tree.get_children())
        for r in self.filtered:
            self.tree.insert("", "end", iid=r["path"],
                             values=(r["name"], r["platform"],
                                     self._fmt_size(r["size"])))
        self.lbl_count.config(text=f"Найдено: {len(self.filtered)}")

    # ── Выбор ROM-а ──────────────────────────────────────────────

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        rom_path = sel[0]
        rom = next((r for r in self.filtered if r["path"] == rom_path), None)
        if not rom:
            return
        self.current_rom = rom
        self._update_buttons_state(rom)
        self._update_card(rom)

    def _update_card(self, rom):
        self.info_labels["name"].config(text=rom["name"])
        self.info_labels["platform"].config(text=rom["platform"])
        self.info_labels["filename"].config(text=rom["filename"])
        self.info_labels["format"].config(text=rom["format"])
        self.info_labels["size"].config(text=self._fmt_size(rom["size"]))
        self.info_labels["path"].config(text=rom["path"])
        if rom["modified"]:
            dt = datetime.fromtimestamp(rom["modified"])
            self.info_labels["modified"].config(text=dt.strftime("%d.%m.%Y %H:%M"))
        else:
            self.info_labels["modified"].config(text="—")

        self.info_labels["md5"].config(text="расчёт…")

        # Обложка
        self._load_cover(rom)

        # MD5 в отдельном потоке
        threading.Thread(
            target=self._calc_md5, args=(rom,), daemon=True).start()


    def _load_cover(self, rom):
        if not rom.get("cover"):
            self.current_cover_path = None
            self.lbl_cover.config(image="", text="Обложка\nне найдена")
            return

        cover_path = rom["cover"]
        self.current_cover_path = cover_path

        if cover_path in self.cover_cache:
            self._render_current_cover()
            return

        self.lbl_cover.config(image="", text="Загрузка…")
        threading.Thread(
            target=self._load_cover_thread, args=(cover_path,), daemon=True
        ).start()

    def _on_right_configure(self, event):
        """Динамически меняет размер обложки от 200 до 300."""
        # event.height — полная высота right с padding
        # Вычитаем примерную высоту кнопок (~110) и минимальную высоту инфо (~220)
        available = event.height - 340
        new_size = max(200, min(300, available))
        if abs(new_size - self.cover_size) >= 5:
            self.cover_size = new_size
            self.cover_frame.config(width=new_size, height=new_size)
            self._render_current_cover()


    def _render_current_cover(self):
        """Перерисовывает текущую обложку под актуальный размер."""
        if not self.current_cover_path or self.current_cover_path not in self.cover_cache:
            self.lbl_cover.config(image="", text="Обложка\nне найдена")
            return
        img = self.cover_cache[self.current_cover_path]
        img_resized = img.copy()
        img_resized.thumbnail((self.cover_size, self.cover_size), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img_resized)
        self.cover_photo = photo
        self.lbl_cover.config(image=photo, text="")


    def _show_cover_from_local(self, local_path):
        try:
            img = Image.open(local_path)
            cover_path = self.current_rom.get("cover")
            if cover_path:
                self.cover_cache[cover_path] = img
                self.current_cover_path = cover_path
            self._render_current_cover()
        except Exception:
            self.lbl_status.config(text="Обложка обновлена (превью недоступно)")


    def _load_cover_thread(self, cover_path):
        if not self._alive:
            return
        try:
            data = self.ssh.read_file_bytes(cover_path, max_bytes=5 * 1024 * 1024)
            img = Image.open(io.BytesIO(data))
            self.cover_cache[cover_path] = img
            self.parent.after(0, self._render_current_cover)
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: self.lbl_cover.config(
                image="", text=f"Ошибка\n{err}"))


    def _calc_md5(self, rom):
        if not self._alive:
            return
        try:
            md5 = self.ssh.read_file_md5(rom["path"], max_bytes=16 * 1024 * 1024)
            self.parent.after(0, lambda: self.info_labels["md5"].config(text=md5))
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: self.info_labels["md5"].config(
                text=f"ошибка: {err}"))

    # ── Кнопки ───────────────────────────────────────────────────

    def _copy_path(self):
        if not self.current_rom:
            return
        self.root_window.clipboard_clear()
        self.root_window.clipboard_append(self.current_rom["path"])
        self.lbl_status.config(text="Путь скопирован")

    def _delete_rom(self):
        if not self.current_rom:
            messagebox.showwarning("Внимание", "Выберите игру в списке.", parent=self.root_window)
            return

        rom = self.current_rom
        msg = f"Удалить файл:\n{rom['path']}"
        if rom.get("cover"):
            msg += f"\nи обложку:\n{rom['cover']}"
        msg += "\n\nЭто действие необратимо!"

        if not messagebox.askyesno("Удаление", msg, icon="warning", parent=self.root_window):
            return

        self.btn_delete.config(state="disabled")
        self.lbl_status.config(text=f"Удаление: {rom['filename']}...")
        threading.Thread(
            target=self._delete_rom_thread,
            args=(rom,),
            daemon=True
        ).start()

    def _delete_rom_thread(self, rom):
        if not self._alive:
            return
        try:
            sftp = self.ssh.client.open_sftp()

            # Удаляем файл игры
            try:
                sftp.remove(rom["path"])
            except Exception as e:
                err = str(e)
                self.parent.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось удалить ROM:\n{err}", parent=self.root_window))
                return

            # Удаляем обложку, если есть
            cover_path = rom.get("cover")
            if cover_path:
                try:
                    sftp.remove(cover_path)
                except Exception:
                    pass  # обложка могла уже не существовать

            sftp.close()

            self.parent.after(0, lambda: self.lbl_status.config(
                text=f"✅ Удалено: {rom['filename']}"))

            # Пересканируем список
            self.parent.after(100, self._connect_and_scan)

        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось удалить:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(text=f"❌ Ошибка: {err}"))
        finally:
            self.parent.after(0, lambda: self.btn_delete.config(state="normal"))

    def _download_rom(self):
        if not self.current_rom:
            messagebox.showwarning("Внимание", "Выберите игру в списке.", parent=self.root_window)
            return

        rom = self.current_rom
        
        initial_name = rom["filename"]
        file_path = filedialog.asksaveasfilename(
            parent=self.root_window,
            title="Сохранить ROM",
            initialfile=initial_name,
            filetypes=[
                ("All files", "*"),
                ("Shell scripts", "*.sh"),
                ("ROM files", "*.nes *.smc *.iso *.cso *.bin")
            ]
        )

        if not file_path:
            return  # нажали "Отмена"

        # Блокируем кнопку, чтобы не нажали дважды
        self.btn_download.config(state="disabled")
        self.lbl_status.config(text=f"Скачивание: {rom['filename']}...")

        # Запускаем скачивание в фоне
        threading.Thread(target=self._download_thread, args=(rom, file_path), daemon=True).start()

    def _download_cover(self):
        if not self.current_rom:
            return
        rom = self.current_rom
        cover_path = rom.get("cover")

        if not cover_path:
            messagebox.showinfo("Нет обложки", "У этой игры нет обложки на консоли.", parent=self.root_window)
            return

        initial_name = os.path.basename(cover_path)
        save_path = filedialog.asksaveasfilename(
            parent=self.root_window,
            title="Сохранить обложку",
            initialfile=initial_name,
            filetypes=[("PNG", "*.png"), ("All files", "*")]
        )
        if not save_path:
            return

        # Добавляем .png, если расширения нет
        if not os.path.splitext(save_path)[1]:
            save_path += ".png"

        self.lbl_status.config(text="Скачивание обложки…")
        threading.Thread(
            target=self._download_cover_thread,
            args=(cover_path, save_path),
            daemon=True
        ).start()


    def _download_cover_thread(self, remote_path, local_path):
        if not self._alive:
            return
        try:
            sftp = self.ssh.client.open_sftp()

            try:
                file_size = sftp.stat(remote_path).st_size
            except Exception:
                file_size = 0

            self.parent.after(0, lambda: self.progress.config(maximum=100, value=0))

            def callback(transferred, total):
                pct = int((transferred / total) * 100) if total > 0 else 0
                self.parent.after(0, lambda p=pct: (
                    self.progress.config(value=p),
                    self.lbl_status.config(text=f"⬇ Обложка… {p}%")
                ))

            sftp.get(remote_path, local_path, callback=callback)
            sftp.close()
            self.parent.after(0, lambda: self.progress.config(value=100))
            self.parent.after(0, lambda: self.lbl_status.config(
                text=f"✅ Обложка сохранена: {os.path.basename(local_path)}"))
        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror(
                "Ошибка", f"Не удалось скачать обложку:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(text=f"❌ Ошибка: {err}"))
        finally:
            self.parent.after(0, lambda: self.progress.config(value=0))



    def _download_pack(self):
        if not self.current_rom:
            messagebox.showwarning("Внимание", "Выберите игру в списке.", parent=self.root_window)
            return

        rom = self.current_rom

        # Формируем имя папки: "Platform - Game"
        # Если платформа неизвестна или пустая — ставим "Unknown"
        platform = rom["platform"] or "Unknown"
        game_name = rom["name"]  # без расширения
        folder_name = f"{platform} - {game_name}"

        # Диалог выбора ПАПКИ (не файла!), куда положить этот пак
        dir_path = filedialog.askdirectory(
            parent=self.root_window,
            title="Выберите папку для сохранения ПАКа")
        if not dir_path:
            return  # отмена

        target_folder = os.path.join(dir_path, folder_name)

        # Блокируем кнопки
        self.btn_download.config(state="disabled")
        self.btn_pack.config(state="disabled")
        self.lbl_status.config(text=f"Создание ПАКа: {folder_name}...")

        threading.Thread(target=self._download_pack_thread, args=(rom, target_folder), daemon=True).start()


    def _download_thread(self, rom, local_path):
        if not self._alive:
            return
        remote_path = rom["path"]
        try:
            sftp = self.ssh.client.open_sftp()

            try:
                attr = sftp.stat(remote_path)
                file_size = attr.st_size
            except Exception:
                file_size = 0

            self.parent.after(0, lambda: self.progress.config(maximum=100, value=0))

            def callback(transferred, total):
                pct = int((transferred / total) * 100) if total > 0 else 0
                self.parent.after(0, lambda p=pct, t=transferred: (
                    self.progress.config(value=p),
                    self.lbl_status.config(
                        text=f"⬇ {t // 1024} / {file_size // 1024} КБ ({pct}%)")
                ))

            sftp.get(remote_path, local_path, callback=callback)
            sftp.close()

            self.parent.after(0, lambda: self.progress.config(value=100))
            self.parent.after(0, lambda: self.lbl_status.config(
                text=f"✅ Готово: {os.path.basename(local_path)}"))

        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror(
                "Ошибка скачивания", f"Не удалось скачать файл:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(text=f"❌ Ошибка: {err}"))
        finally:
            self.parent.after(0, lambda: self.progress.config(value=0))
            self.parent.after(0, lambda: self.btn_download.config(state="normal"))

    def _download_pack_thread(self, rom, target_folder):
        if not self._alive:
            return
        remote_rom_path = rom["path"]
        remote_cover_path = rom.get("cover")

        try:
            os.makedirs(target_folder, exist_ok=True)
            sftp = self.ssh.client.open_sftp()

            # Считаем общий размер обоих файлов
            rom_size = 0
            cover_size = 0
            try:
                rom_size = sftp.stat(remote_rom_path).st_size
            except Exception:
                pass
            if remote_cover_path:
                try:
                    cover_size = sftp.stat(remote_cover_path).st_size
                except Exception:
                    pass
            total_size = rom_size + cover_size

            self.parent.after(0, lambda: self.progress.config(maximum=100, value=0))

            def make_callback(file_label, file_offset):
                def callback(transferred, total):
                    overall = file_offset + transferred
                    pct = int((overall / total_size) * 100) if total_size > 0 else 0
                    self.parent.after(0, lambda p=pct, l=file_label: (
                        self.progress.config(value=p),
                        self.lbl_status.config(text=f"⬇ {l}… {p}%")
                    ))
                return callback

            # 1. Качаем игру
            game_filename = os.path.basename(remote_rom_path)
            game_local_path = os.path.join(target_folder, game_filename)
            sftp.get(remote_rom_path, game_local_path,
                     callback=make_callback(game_filename, 0))

            # 2. Если есть обложка — качаем её
            if remote_cover_path:
                cover_filename = os.path.basename(remote_cover_path)
                cover_local_path = os.path.join(target_folder, cover_filename)
                sftp.get(remote_cover_path, cover_local_path,
                         callback=make_callback(cover_filename, rom_size))

            sftp.close()

            self.parent.after(0, lambda: self.progress.config(value=100))
            self.parent.after(0, lambda: self.lbl_status.config(
                text=f"✅ ПАК сохранён: {os.path.basename(target_folder)}"))

        except Exception as e:
            err = str(e)
            self.parent.after(0, lambda: messagebox.showerror(
                "Ошибка скачивания ПАКа", f"Не удалось скачать:\n{err}", parent=self.root_window))
            self.parent.after(0, lambda: self.lbl_status.config(text=f"❌ Ошибка: {err}"))
        finally:
            self.parent.after(0, lambda: self.progress.config(value=0))
            self.parent.after(0, lambda: self.btn_download.config(state="normal"))
            self.parent.after(0, lambda: self.btn_pack.config(state="normal"))

    def _update_buttons_state(self, rom):
        """Включает/выключает кнопки в зависимости от типа игры."""
        if not rom:
            self.btn_download.config(state="disabled")
            self.btn_pack.config(state="disabled")
            self.btn_cover.config(state="disabled")
            self.btn_dl_cover.config(state="disabled")
            self.btn_delete.config(state="disabled")
            return

        is_ports = rom["platform_dir"].upper() == "PORTS"

        # Для PORTS отключаем скачивание игры и пак
        self.btn_download.config(state="disabled" if is_ports else "normal")
        self.btn_pack.config(state="disabled" if is_ports else "normal")
        self.btn_delete.config(state="disabled" if is_ports else "normal")

        # Обложки — всегда доступны
        self.btn_cover.config(state="normal")
        self.btn_dl_cover.config(state="normal")



    # ── Вспомогательные ──────────────────────────────────────────

    def _set_status(self, text):
        if not self._alive:
            return
        self.parent.after(0, lambda: self.lbl_status.config(text=text))

    @staticmethod
    def _fmt_size(n):
        if n < 1024:
            return f"{n} Б"
        elif n < 1024 * 1024:
            return f"{n / 1024:.1f} КБ"
        elif n < 1024 * 1024 * 1024:
            return f"{n / 1024 / 1024:.1f} МБ"
        else:
            return f"{n / 1024 / 1024 / 1024:.2f} ГБ"

    @staticmethod
    def _info_label_text(key):
        return {
            "name": "Название",
            "platform": "Платформа",
            "filename": "Файл",
            "format": "Формат",
            "size": "Размер",
            "path": "Путь",
            "modified": "Дата",
            "md5": "MD5",
        }.get(key, key)

    def destroy(self):
        self._alive = False
        if self.ssh:
            self.ssh.close()
        super().destroy()