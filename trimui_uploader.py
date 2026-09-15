import os
import sys
import json
import datetime
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from rom_viewer_ssh import RomViewerSSH

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

APP_TITLE = "TrimUI Game Uploader"
CONFIG_FILE = "trimui_uploader.json"

def get_config_path():
    """Возвращает путь к конфигу: рядом с .exe или в текущей папке."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, CONFIG_FILE)
    else:
        return CONFIG_FILE

SYSTEM_PATHS = {
    "ARCADE": "/mnt/sdcard/mmcblk1p1/Roms/ARCADE",
    "CPS1": "/mnt/sdcard/mmcblk1p1/Roms/CPS1",
    "CPS2": "/mnt/sdcard/mmcblk1p1/Roms/CPS2",
    "CPS3": "/mnt/sdcard/mmcblk1p1/Roms/CPS3",
    "DC": "/mnt/sdcard/mmcblk1p1/Roms/DC",
    "DOS": "/mnt/sdcard/mmcblk1p1/Roms/DOS",
    "FBNEO": "/mnt/sdcard/mmcblk1p1/Roms/FBNEO",
    "FC": "/mnt/sdcard/mmcblk1p1/Roms/FC",
    "FDS": "/mnt/sdcard/mmcblk1p1/Roms/FDS",
    "GB": "/mnt/sdcard/mmcblk1p1/Roms/GB",
    "GBA": "/mnt/sdcard/mmcblk1p1/Roms/GBA",
    "GBC": "/mnt/sdcard/mmcblk1p1/Roms/GBC",
    "GG": "/mnt/sdcard/mmcblk1p1/Roms/GG",
    "MAME2003PLUS": "/mnt/sdcard/mmcblk1p1/Roms/MAME2003PLUS",
    "MD": "/mnt/sdcard/mmcblk1p1/Roms/MD",
    "MS": "/mnt/sdcard/mmcblk1p1/Roms/MS",
    "N64": "/mnt/sdcard/mmcblk1p1/Roms/N64",
    "NDS": "/mnt/sdcard/mmcblk1p1/Roms/NDS",
    "NEOGEO": "/mnt/sdcard/mmcblk1p1/Roms/NEOGEO",
    "NEOMVS": "/mnt/sdcard/mmcblk1p1/Roms/NEOMVS",
    "NGP": "/mnt/sdcard/mmcblk1p1/Roms/NGP",
    "PCE": "/mnt/sdcard/mmcblk1p1/Roms/PCE",
    "PORTS": "/mnt/sdcard/mmcblk1p1",
    "PS": "/mnt/sdcard/mmcblk1p1/Roms/PS",
    "PSP": "/mnt/sdcard/mmcblk1p1/Roms/PSP",
    "SATURN": "/mnt/sdcard/mmcblk1p1/Roms/SATURN",
    "SCUMMVM": "/mnt/sdcard/mmcblk1p1/Roms/SCUMMVM",
    "SEGA32X": "/mnt/sdcard/mmcblk1p1/Roms/SEGA32X",
    "SEGACD": "/mnt/sdcard/mmcblk1p1/Roms/SEGACD",
    "SFC": "/mnt/sdcard/mmcblk1p1/Roms/SFC",
    "Custom": "",
}

BASE_SYSTEMS = set(SYSTEM_PATHS.keys())



class TrimUIUploader:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x680")
        self.root.minsize(600, 600)
        self.config_path = get_config_path()
        self.config = self.load_config()
        self.game_files = []
        self.image_files = []
        self.preserve_structure_var = tk.BooleanVar(value=False)
        self.lowercase_var = tk.BooleanVar(value=False)
        self.uppercase_var = tk.BooleanVar(value=False)
        self._updating_system = False
        self.build_ui()

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    custom_systems = config.get("custom_systems", {})
                    SYSTEM_PATHS.update(custom_systems)
                    return config
            except Exception:
                pass
        return {"ip": "", "username": "root", "password": "",
                "system": "PORTS", "remote_base": "/mnt/sdcard/mmcblk1p1/Roms"}


    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def save_config_data(self):
        self.config["ip"] = self.ip_var.get()
        self.config["username"] = self.user_var.get()
        self.config["system"] = self.system_var.get()
        self.config["password"] = self.pass_var.get() if self.save_pass_var.get() else ""

    def build_ui(self):
        style = ttk.Style()
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))

        # --- СОЗДАЁМ ВКЛАДКИ ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        # Вкладка 1: Загрузка
        self.upload_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.upload_frame, text="📤 Загрузка")

        # Вкладка 2: Просмотр ROM (пока пустая, наполнится при переключении)
        self.rom_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.rom_frame, text="📂 Просмотр ROM")

        # Вкладка 3: Файловый менеджер
        self.file_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.file_frame, text="📁 Файлы")

        self.rom_viewer = None  # будет создан при первом переключении
        self.file_manager = None  # будет создан при первом переключении
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # --- Блок подключения ---
        conn_frame = ttk.LabelFrame(self.upload_frame, text="Подключение к консоли", padding=10)  # ← root → upload_frame
        conn_frame.pack(fill="x", padx=10, pady=(10, 5))

        ttk.Label(conn_frame, text="IP:").grid(row=0, column=0, sticky="w", pady=2)
        self.ip_var = tk.StringVar(value=self.config.get("ip", ""))
        ttk.Entry(conn_frame, textvariable=self.ip_var, width=20).grid(row=0, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(conn_frame, text="Пользователь:").grid(row=0, column=2, sticky="w", pady=2)
        self.user_var = tk.StringVar(value=self.config.get("username", "root"))
        ttk.Entry(conn_frame, textvariable=self.user_var, width=12).grid(row=0, column=3, sticky="w", padx=5, pady=2)

        ttk.Label(conn_frame, text="Пароль:").grid(row=1, column=0, sticky="w", pady=2)
        self.pass_var = tk.StringVar(value=self.config.get("password", ""))
        ttk.Entry(conn_frame, textvariable=self.pass_var, width=20, show="*").grid(row=1, column=1, sticky="w", padx=5, pady=2)

        self.save_pass_var = tk.BooleanVar(value=bool(self.config.get("password", "")))
        ttk.Checkbutton(conn_frame, text="Запомнить", variable=self.save_pass_var).grid(row=1, column=2, columnspan=2, sticky="w", padx=5)

        # --- Блок назначения ---
        dest_frame = ttk.LabelFrame(self.upload_frame, text="Куда заливать", padding=10)  # ← root → upload_frame
        dest_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(dest_frame, text="Система:").grid(row=0, column=0, sticky="w", pady=2)
        self.system_var = tk.StringVar(value=self.config.get("system", "PORTS"))
        self.system_combo = ttk.Combobox(dest_frame, textvariable=self.system_var, values=list(SYSTEM_PATHS.keys()), width=15, state="readonly")
        self.system_combo.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        self.system_combo.bind("<<ComboboxSelected>>", self.on_system_change)

        ttk.Label(dest_frame, text="Путь:").grid(row=0, column=2, sticky="w", pady=2)
        self.path_var = tk.StringVar(value=SYSTEM_PATHS.get(self.system_var.get(), ""))
        path_entry = ttk.Entry(dest_frame, textvariable=self.path_var, width=45)
        path_entry.grid(row=0, column=3, sticky="we", padx=5, pady=2)
        dest_frame.columnconfigure(3, weight=1)

        ttk.Button(dest_frame, text="🔍 Найти путь", command=self.detect_path).grid(row=0, column=4, sticky="w", padx=5, pady=2)

        self.subfolder_label = ttk.Label(dest_frame, text="Подпапка:")
        self.subfolder_label.grid(row=1, column=0, sticky="w", pady=2)
        self.subfolder_var = tk.StringVar(value="")
        self.subfolder_entry = ttk.Combobox(dest_frame, textvariable=self.subfolder_var, width=43)
        self.subfolder_entry.grid(row=1, column=1, columnspan=3, sticky="we", padx=5, pady=2)
        self.fetch_subfolders_btn = ttk.Button(dest_frame, text="📂", command=self.fetch_port_subfolders)
        self.fetch_subfolders_btn.grid(row=1, column=4, sticky="w", padx=(0, 5), pady=2)

        self.subfolder_hint = ttk.Label(dest_frame, text="(имя игры — для PortMaster: будет папка Data/ports/<имя>)", foreground="#666")
        self.subfolder_hint.grid(row=2, column=0, columnspan=5, sticky="w")

        self.custom_name_label = ttk.Label(dest_frame, text="Имя системы:")
        self.custom_name_var = tk.StringVar(value="")
        self.custom_name_entry = ttk.Entry(dest_frame, textvariable=self.custom_name_var, width=18)
        self.save_system_btn = ttk.Button(dest_frame, text="💾 Сохранить", command=self.save_custom_system)
        self.custom_name_label.grid(row=3, column=0, sticky="w", pady=2)
        self.custom_name_entry.grid(row=3, column=1, sticky="w", padx=5, pady=2)
        self.save_system_btn.grid(row=3, column=2, sticky="w", pady=2)
        self.custom_name_label.grid_remove()
        self.custom_name_entry.grid_remove()
        self.save_system_btn.grid_remove()

        # --- Блок файлов игры ---
        game_frame = ttk.LabelFrame(self.upload_frame, text="Файлы игры", padding=10)  # ← root → upload_frame
        game_frame.pack(fill="both", expand=True, padx=10, pady=5)

        btn_frame = ttk.Frame(game_frame)
        btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame, text="Добавить файлы", command=self.add_game_files).pack(side="left", padx=(0, 5))
        ttk.Button(btn_frame, text="Добавить папку", command=self.add_game_folder).pack(side="left", padx=(0, 5))
        ttk.Button(btn_frame, text="Очистить", command=self.clear_game_files).pack(side="left")

        opts_frame = ttk.Frame(game_frame)
        opts_frame.pack(fill="x", pady=(0, 5))
        ttk.Checkbutton(opts_frame, text="Сохранить структуру папок", variable=self.preserve_structure_var).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(opts_frame, text="Нижний регистр", variable=self.lowercase_var).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(opts_frame, text="Верхний регистр", variable=self.uppercase_var).pack(side="left")

        self.game_listbox = tk.Listbox(game_frame, height=5, selectmode=tk.EXTENDED)
        self.game_listbox.pack(side="left", fill="both", expand=True, pady=(0, 5))
        game_scroll = ttk.Scrollbar(game_frame, orient="vertical", command=self.game_listbox.yview)
        game_scroll.pack(side="right", fill="y")
        self.game_listbox.configure(yscrollcommand=game_scroll.set)

        # --- Блок картинок ---
        img_frame = ttk.LabelFrame(self.upload_frame, text="Картинки (обложки/скриншоты)", padding=10)  # ← root → upload_frame
        img_frame.pack(fill="both", expand=True, padx=10, pady=5)

        img_btn_frame = ttk.Frame(img_frame)
        img_btn_frame.pack(fill="x", pady=(0, 5))
        ttk.Button(img_btn_frame, text="Добавить картинки", command=self.add_image_files).pack(side="left", padx=(0, 5))
        ttk.Button(img_btn_frame, text="Очистить", command=self.clear_image_files).pack(side="left")

        self.img_listbox = tk.Listbox(img_frame, height=3, selectmode=tk.EXTENDED)
        self.img_listbox.pack(side="left", fill="both", expand=True, pady=(0, 5))
        img_scroll = ttk.Scrollbar(img_frame, orient="vertical", command=self.img_listbox.yview)
        img_scroll.pack(side="right", fill="y")
        self.img_listbox.configure(yscrollcommand=img_scroll.set)

        # --- Панель действий ---
        action_frame = ttk.Frame(self.upload_frame)
        action_frame.pack(fill="x", padx=10, pady=(5, 5))

        self.transfer_btn = ttk.Button(action_frame, text="Залить на консоль", command=self.start_transfer)
        self.transfer_btn.pack(side="left", padx=(0, 10))

        ttk.Button(action_frame, text="Проверить соединение", command=self.test_connection).pack(side="left", padx=(0, 10))

        self.progress = ttk.Progressbar(action_frame, mode="determinate")
        self.progress.pack(side="right", fill="x", expand=True, padx=(10, 0))

        self.status_label = ttk.Label(self.upload_frame, text="Готово к работе", font=("Segoe UI", 9))  # ← root → upload_frame
        self.status_label.pack(fill="x", padx=10, pady=(0, 5))

        # --- Лог ---
        log_frame = ttk.LabelFrame(self.upload_frame, text="Лог", padding=5)  # ← root → upload_frame
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log_text = tk.Text(log_frame, height=6, state="disabled", font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.copy_btn = ttk.Button(action_frame, text="📋 Скопировать логи", command=self.copy_logs)
        self.copy_btn.pack(side="right")

        self.on_system_change()



    def on_system_change(self, event=None):
        if self._updating_system:
            return
        self._updating_system = True
        try:
            system = self.system_var.get()

            if system == "Custom":
                self.path_var.set("")
            elif system in SYSTEM_PATHS and SYSTEM_PATHS[system]:
                self.path_var.set(SYSTEM_PATHS[system])

            if system == "PORTS":
                self.subfolder_label.grid()
                self.subfolder_entry.grid()
                self.subfolder_hint.grid()
                self.fetch_subfolders_btn.grid()
            else:
                self.subfolder_label.grid_remove()
                self.subfolder_entry.grid_remove()
                self.subfolder_hint.grid_remove()
                self.fetch_subfolders_btn.grid_remove()
                self.subfolder_var.set("")

            if system == "Custom":
                self.custom_name_label.grid(row=3, column=0, sticky="w", pady=2)
                self.custom_name_entry.grid(row=3, column=1, sticky="w", padx=5, pady=2)
                self.save_system_btn.grid(row=3, column=2, sticky="w", pady=2)
            else:
                self.custom_name_label.grid_remove()
                self.custom_name_entry.grid_remove()
                self.save_system_btn.grid_remove()
        finally:
            self._updating_system = False


# Страница ромов
    def on_tab_changed(self, event):
        """Срабатывает при переключении вкладки."""
        current = self.notebook.select()
        if not current:
            return

        # Получаем текст активной вкладки
        tab_text = self.notebook.tab(current, "text")

        if tab_text == "📂 Просмотр ROM":
            self.init_rom_viewer()
        elif tab_text == "📁 Файлы":
            self.init_file_manager()

    def init_rom_viewer(self):
        """Создаёт ROM-вьюер при первом переходе на вкладку."""
        if not HAS_PARAMIKO:
            messagebox.showerror("Ошибка", "paramiko не установлен.\nВыполните: pip install paramiko")
            self.notebook.select(0)  # возвращаем на вкладку загрузки
            return
        if not self.ip_var.get():
            messagebox.showwarning("Внимание", "Укажите IP консоли.")
            self.notebook.select(0)
            return

        roms_base = self.get_roms_base()
        if roms_base.endswith("/Roms"):
            imgs_base = roms_base[:-5] + "/Imgs"
        else:
            imgs_base = None

        if self.rom_viewer is None:
            self.rom_viewer = RomViewerSSH(
                parent=self.rom_frame,
                root_window=self.root,
                host=self.ip_var.get(),
                username=self.user_var.get(),
                password=self.pass_var.get(),
                rom_path=roms_base,
                imgs_path=imgs_base,
            )
            self.rom_viewer.pack(fill="both", expand=True)

    def init_file_manager(self):
        if not HAS_PARAMIKO:
            messagebox.showerror("Ошибка", "paramiko не установлен.\nВыполните: pip install paramiko")
            self.notebook.select(0)
            return
        if not self.ip_var.get():
            messagebox.showwarning("Внимание", "Укажите IP консоли.")
            self.notebook.select(0)
            return

        if self.file_manager is None:
            # Вычисляем безопасный корень так же, как для ROM-вьюера
            roms_base = self.get_roms_base()
            if roms_base.endswith("/Roms"):
                safe_root = roms_base[:-5]
            else:
                safe_root = roms_base

            try:
                from file_manager_ssh import FileManagerSSH
                self.file_manager = FileManagerSSH(
                    parent=self.file_frame,
                    root_window=self.root,
                    host=self.ip_var.get(),
                    username=self.user_var.get(),
                    password=self.pass_var.get(),
                    start_path=safe_root,
                    safe_mode=True,
                    safe_root=safe_root,
                )
                self.file_manager.pack(fill="both", expand=True)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть файловый менеджер:\n{e}")
                self.notebook.select(0)

    def get_roms_base(self):
        """Извлекает базовый путь к папке Roms из текущих настроек."""
        # Пытаемся получить из текущего пути
        current = self.path_var.get().strip()
        if "/Roms/" in current:
            return current.split("/Roms/")[0] + "/Roms"
        if current.endswith("/Roms"):
            return current

        # Пытаемся получить из любой системы в SYSTEM_PATHS
        for sys_name, sys_path in SYSTEM_PATHS.items():
            if sys_name == "Custom":
                continue
            if sys_path and "/Roms/" in sys_path:
                return sys_path.split("/Roms/")[0] + "/Roms"
            if sys_path and sys_path.endswith("/Roms"):
                return sys_path

        # Fallback — значение по умолчанию
        return "/mnt/sdcard/mmcblk1p1/Roms"


    def save_custom_system(self):
        name = self.custom_name_var.get().strip()
        path = self.path_var.get().strip()
        if not name:
            messagebox.showwarning("Внимание", "Введите имя для новой системы.")
            return
        if not path:
            messagebox.showwarning("Внимание", "Укажите путь для системы.")
            return

        SYSTEM_PATHS[name] = path

        if "custom_systems" not in self.config:
            self.config["custom_systems"] = {}
        self.config["custom_systems"][name] = path
        self.save_config()

        self.system_combo["values"] = list(SYSTEM_PATHS.keys())
        self.system_var.set(name)
        self.on_system_change()

        self.log(f"Система «{name}» сохранена: {path}")
        self.set_status(f"Система «{name}» добавлена в список")

    def detect_path(self):
        if not HAS_PARAMIKO:
            messagebox.showerror("Ошибка", "paramiko не установлен.")
            return
        if not self.ip_var.get():
            messagebox.showwarning("Внимание", "Укажите IP консоли.")
            return

        def do_detect():
            try:
                self.set_status("Определение пути...")
                self.log("Поиск папки Roms на консоли...")
                client = self.get_ssh_client()

                cmd = "find /mnt /media /sdcard /tmp -maxdepth 4 -name 'Roms' -type d 2>/dev/null"
                stdin, stdout, stderr = client.exec_command(cmd)
                result = stdout.read().decode().strip()

                if not result:
                    self.log("Папка Roms не найдена. Укажите путь вручную через Custom.")
                    self.set_status("Папка Roms не найдена")
                    client.close()
                    return

                paths = [p.strip() for p in result.split('\n') if p.strip()]
                self.log(f"Найдено путей: {len(paths)}")
                for p in paths:
                    self.log(f"  {p}")

                roms_base = paths[0]
                self.log(f"Используется: {roms_base}")

                for system in BASE_SYSTEMS:
                    if system != "Custom" and SYSTEM_PATHS[system]:
                        if system == "PORTS":
                            # PORTS — это корень монтирования, а не Roms/PORTS
                            SYSTEM_PATHS[system] = roms_base.replace("/Roms", "")
                        else:
                            SYSTEM_PATHS[system] = f"{roms_base}/{system}"

                # Обновляем UI без авто-вызовов
                self._updating_system = True
                try:
                    current_system = self.system_var.get()
                    if current_system in SYSTEM_PATHS and SYSTEM_PATHS[current_system]:
                        self.path_var.set(SYSTEM_PATHS[current_system])
                finally:
                    self._updating_system = False

                self.set_status(f"Путь определён: {roms_base}")
                self.log("Базовый путь обновлён для всех систем.")
                client.close()
            except Exception as e:
                self.set_status(f"Ошибка: {e}")
                self.log(f"Ошибка при определении пути: {e}")

        threading.Thread(target=do_detect, daemon=True).start()

    def fetch_port_subfolders(self):
        if not HAS_PARAMIKO:
            messagebox.showerror("Ошибка", "paramiko не установлен.")
            return
        if not self.ip_var.get():
            messagebox.showwarning("Внимание", "Укажите IP консоли.")
            return


        def do_fetch():
            try:
                self.set_status("Загрузка списка подпапок...")
                self.log("Получение списка портов с консоли...")
                client = self.get_ssh_client()

                # Путь к Data/ports — в КОРНЕ монтирования, а не в Roms/PORTS
                base_path = self.path_var.get().rstrip("/")
                if "/Roms/" in base_path:
                    mount_root = base_path.split("/Roms/")[0]
                else:
                    mount_root = base_path

                ports_dir = f"{mount_root}/Data/ports"

                self.log(f"Поиск портов в: {ports_dir}")
                stdin, stdout, stderr = client.exec_command(
                    f"ls -1d {ports_dir}/*/ 2>/dev/null"
                )
                result = stdout.read().decode().strip()

                if not result:
                    self.log(f"Папка {ports_dir} пуста или не существует.")
                    self.set_status("Существующих подпапок не найдено")
                    client.close()
                    return

                subfolders = []
                for line in result.splitlines():
                    name = line.strip().rstrip("/")
                    name = os.path.basename(name)
                    if name:
                        subfolders.append(name)

                subfolders.sort()
                self.subfolder_entry["values"] = subfolders
                self.log(f"Найдено подпапок: {len(subfolders)}")
                for s in subfolders:
                    self.log(f"  {s}")
                self.set_status(f"Загружено {len(subfolders)} подпапок")

                client.close()
            except Exception as e:
                self.set_status(f"Ошибка: {e}")
                self.log(f"Ошибка при получении подпапок: {e}")

        threading.Thread(target=do_fetch, daemon=True).start()

    def log(self, msg):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        full = f"[{timestamp}] {msg}"
        if not hasattr(self, "log_messages"):
            self.log_messages = []
        self.log_messages.append(full)
        # Запись в Text-виджет (чтобы видно было в окне)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", full + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()


    def copy_logs(self):
        # Если у тебя логи в Text-виджете:
        if hasattr(self, "log_text") and isinstance(self.log_text, tk.Text):
            content = self.log_text.get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.set_status("Логи скопированы в буфер обмена!")
        else:
            # Если логи просто накапливаются в строке/списке:
            content = "\n".join(self.log_messages)  # если ты хранишь их в списке
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            self.set_status("Логи скопированы в буфер обмена!")


    def set_status(self, text):
        self.status_label.configure(text=text)
        self.root.update_idletasks()

    def _make_callback(self, remote_name, file_idx, total_files, file_offset, file_size, grand_total):
        def callback(transferred, total):
            overall = file_offset + transferred
            pct = int((overall / grand_total) * 100) if grand_total > 0 else 0
            file_pct = int((transferred / total) * 100) if total > 0 else 0
            self.set_status(f"[{file_idx}/{total_files}] {remote_name} — {file_pct}%  (всего {pct}%)")
            self.progress["value"] = pct
            self.root.update_idletasks()
        return callback


    def add_game_files(self):
        files = filedialog.askopenfilenames(title="Выберите файлы игры")
        for f in files:
            rel = os.path.basename(f)  # отдельные файлы — всегда basename
            self.game_listbox.insert("end", f)
            self.game_files.append((f, rel))
        if files:
            self.log(f"Добавлено файлов: {len(files)}")

    def add_game_folder(self):
        folder = filedialog.askdirectory(title="Выберите папку с игрой")
        if folder:
            preserve = self.preserve_structure_var.get()
            folder_name = os.path.basename(folder)
            count = 0
            for root_dir, dirs, files in os.walk(folder):
                for f in files:
                    full = os.path.join(root_dir, f)
                    # Относительный путь внутри выбранной папки (со всеми подпапками)
                    rel = os.path.relpath(full, folder).replace("\\", "/")
                    if preserve:
                        # Добавляем имя самой папки в начало пути
                        rel = f"{folder_name}/{rel}"
                    # Без флага — rel уже содержит подпапки, но без имени выбранной папки
                    self.game_listbox.insert("end", full)
                    self.game_files.append((full, rel))
                    count += 1
            self.log(f"Добавлена папка: {folder} ({count} файлов)")

    def clear_game_files(self):
        self.game_files.clear()
        self.game_listbox.delete(0, "end")

    def add_image_files(self):
        files = filedialog.askopenfilenames(title="Выберите картинки", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif")])
        for f in files:
            self.img_listbox.insert("end", f)
            self.image_files.append(f)
        if files:
            self.log(f"Добавлено картинок: {len(files)}")

    def clear_image_files(self):
        self.image_files.clear()
        self.img_listbox.delete(0, "end")

    def get_remote_path(self):
        base = self.path_var.get().rstrip("/")
        sub = self.subfolder_var.get().strip()
        system_name = self.system_var.get()

        if system_name == "PORTS":
            if sub:
                return f"{base}/Data/ports/{sub}"
            return f"{base}/Data/ports"

        if sub:
            return f"{base}/{sub}"
        return base



    def get_ssh_client(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=self.ip_var.get(), username=self.user_var.get(),
                        password=self.pass_var.get(), timeout=10,
                        look_for_keys=False, allow_agent=False)
        return client

    def run_remote(self, client, cmd):
        stdin, stdout, stderr = client.exec_command(cmd)
        err = stderr.read().decode().strip()
        if err:
            self.log(f"cmd: {cmd} -> {err}")

    def test_connection(self):
        if not HAS_PARAMIKO:
            messagebox.showerror("Ошибка", "paramiko не установлен.\nВыполните: pip install paramiko")
            return
        def do_test():
            try:
                self.log("Проверка соединения...")
                client = self.get_ssh_client()
                stdin, stdout, stderr = client.exec_command("uname -a")
                self.log(f"OK: {stdout.read().decode().strip()}")
                client.close()
            except Exception as e:
                self.log(f"Ошибка: {e}")
        threading.Thread(target=do_test, daemon=True).start()

    def start_transfer(self):
        if not HAS_PARAMIKO:
            messagebox.showerror("Ошибка", "paramiko не установлен.\nВыполните: pip install paramiko")
            return
        if not self.game_files and not self.image_files:
            messagebox.showwarning("Внимание", "Нет файлов для передачи.")
            return
        if not self.ip_var.get():
            messagebox.showwarning("Внимание", "Укажите IP консоли.")
            return
        self.save_config_data()
        self.transfer_btn.configure(state="disabled")
        self.progress["value"] = 0
        threading.Thread(target=self.do_transfer, daemon=True).start()

    def do_transfer(self):
        try:
            self.set_status("Подключение...")
            self.log("Подключение...")
            client = self.get_ssh_client()
            sftp = client.open_sftp()
            remote_base = self.get_remote_path()

            system_name = self.system_var.get()
            base_path = self.path_var.get().rstrip("/")

            if "/Roms/" in base_path:
                mount_root = base_path.split("/Roms/")[0]
            else:
                mount_root = base_path

            if system_name == "Custom":
                folder_name = base_path.split("/")[-1]
                img_dir = f"{mount_root}/Imgs/{folder_name}"
            else:
                img_dir = f"{mount_root}/Imgs/{system_name}"

            self.run_remote(client, f"mkdir -p '{remote_base}'")
            self.run_remote(client, f"mkdir -p '{img_dir}'")

            sub_name = self.subfolder_var.get().strip()
            # Группируем файлы игр по "играм" — по первому компоненту пути
            game_groups = []
            seen_groups = set()
            for local_path, rel_path in self.game_files:
                if "/" in rel_path:
                    group_key = rel_path.split("/")[0]
                else:
                    group_key = os.path.splitext(rel_path)[0]
                if group_key not in seen_groups:
                    seen_groups.add(group_key)
                    game_groups.append(group_key)

            renamed_images = []
            used_names = set()
            for idx, local_path in enumerate(self.image_files):
                ext = os.path.splitext(local_path)[1]
                if sub_name:
                    base_name = sub_name
                elif idx < len(game_groups):
                    # Картинка №1 → имя игры №1, картинка №2 → имя игры №2 и т.д.
                    base_name = game_groups[idx]
                elif game_groups:
                    # Лишние картинки (больше чем игр) → имя последней игры + суффикс
                    base_name = game_groups[-1]
                else:
                    base_name = os.path.splitext(os.path.basename(local_path))[0]
                if base_name in used_names:
                    i = 1
                    while f"{base_name}_{i}" in used_names:
                        i += 1
                    base_name = f"{base_name}_{i}"
                used_names.add(base_name)
                renamed_images.append((local_path, f"{base_name}{ext}"))

            # Функция конвертации регистра
            def convert_case(name):
                if self.lowercase_var.get():
                    return name.lower()
                elif self.uppercase_var.get():
                    return name.upper()
                return name

            # Сборка списка с применением регистра
            game_entries = []
            for local_path, rel_path in self.game_files:
                remote_name = convert_case(rel_path)
                game_entries.append(("game", local_path, remote_name))

            image_entries = [("image", local, convert_case(remote)) 
                            for local, remote in renamed_images]

            all_files = game_entries + image_entries

            # Считаем общий вес
            grand_total = sum(os.path.getsize(f[1]) for f in all_files)
            self.progress["maximum"] = 100
            self.progress["value"] = 0
            total_mb = grand_total / (1024 * 1024)
            self.log(f"Передача {len(all_files)} файлов ({total_mb:.1f} МБ) в {remote_base}...")
            self.log(f"Картинки -> {img_dir}")

            # Множество уже созданных удалённых папок
            created_dirs = set()

            file_offset = 0
            for i, (ftype, local_path, remote_name) in enumerate(all_files):
                if ftype == "image":
                    remote_path = f"{img_dir}/{remote_name}"
                else:
                    if "/" in remote_name:
                        # Создаём подпапки на консоли
                        parts = remote_name.split("/")
                        current = remote_base
                        for part in parts[:-1]:
                            current = f"{current}/{part}"
                            if current not in created_dirs:
                                try:
                                    sftp.mkdir(current)
                                except IOError:
                                    pass  # уже существует
                                created_dirs.add(current)
                        remote_path = f"{remote_base}/{remote_name}"
                    else:
                        # Без структуры — только имя файла
                        remote_path = f"{remote_base}/{os.path.basename(remote_name)}"

                file_size = os.path.getsize(local_path)
                file_mb = file_size / (1024 * 1024)
                self.log(f"[{i+1}/{len(all_files)}] {remote_name} ({file_mb:.1f} МБ) -> {remote_path}")
                callback = self._make_callback(remote_name, i + 1, len(all_files), file_offset, file_size, grand_total)
                sftp.put(local_path, remote_path, callback=callback)
                sftp.chmod(remote_path, 0o777)
                file_offset += file_size

            self.progress["value"] = 100
            self.set_status("Готово! Обновите список ROMs на консоли.")
            self.log("Готово! Обновите список ROMs на консоли.")
            self.transfer_btn.configure(state="normal")
            sftp.close()
            client.close()
        except Exception as e:
            self.set_status(f"Ошибка: {e}")
            self.log(f"Ошибка: {e}")
            self.transfer_btn.configure(state="normal")


    def run(self):
        def on_close():
            self.save_config_data()
            self.save_config()
            self.root.destroy()
        self.root.protocol("WM_DELETE_WINDOW", on_close)
        if not HAS_PARAMIKO:
            self.log("Внимание: paramiko не установлен. Выполните: pip install paramiko")
        else:
            self.log("Готово. Укажите файлы и нажмите «Залить на консоль».")
        self.root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    app = TrimUIUploader(root)
    app.run()
