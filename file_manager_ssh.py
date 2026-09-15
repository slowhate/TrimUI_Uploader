import os
import posixpath
import threading
import tkinter as tk
from tkinter import simpledialog
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

import paramiko


def _fmt_size(n):
    if n < 1024:
        return f"{n} Б"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} КБ"
    elif n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} МБ"
    else:
        return f"{n / 1024 / 1024 / 1024:.2f} ГБ"


def _fmt_date(ts):
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%d.%m.%Y %H:%M")


class FileManagerSSH(ttk.Frame):
    """Файловый менеджер по SSH/SFTP для TrimUI Smart Pro."""

    def __init__(self, parent, root_window, host, username="root",
                 password="", start_path=None, safe_mode=True, safe_root="/"):
        super().__init__(parent)
        self.parent = parent
        self.root_window = root_window

        self.host = host
        self.username = username
        self.password = password
        self.safe_mode = safe_mode
        self.safe_root = safe_root
        self._dir_size_cache = {}

        # Стартовый путь: если безопасный режим и путь вне safe_root — обрезаем
        if start_path:
            self.current_path = start_path
        else:
            self.current_path = self.safe_root if self.safe_mode else "/"

        if self.safe_mode and not self.current_path.startswith(self.safe_root):
            self.current_path = self.safe_root

        self.ssh = None
        self.sftp = None
        self._alive = True
        self._clipboard = None  # для вырезания/копирования (перемещение)

        self._build_ui()
        self.after(100, self._connect_and_list)

    # ── Интерфейс ────────────────────────────────────────────────

    def _build_ui(self):
        # Статус-бар
        bottom_bar = ttk.Frame(self)
        bottom_bar.pack(fill="x", side="bottom")

        self.progress = ttk.Progressbar(bottom_bar, mode="determinate", maximum=100)
        self.progress.pack(fill="x")

        self.lbl_status = ttk.Label(bottom_bar, text="Подключение…",
                                    anchor="w", relief="sunken", padding=4)
        self.lbl_status.pack(fill="x")

        # Верхняя панель — навигация
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")

        self.btn_up = ttk.Button(top, text="🠕 Вверх", command=self._go_up)
        self.btn_up.pack(side="left", padx=(0, 4))

        self.btn_refresh = ttk.Button(top, text="🔄 Обновить", command=self._refresh)
        self.btn_refresh.pack(side="left", padx=(0, 10))

        ttk.Label(top, text="Путь:").pack(side="left")
        self.path_var = tk.StringVar(value=self.current_path)
        path_entry = ttk.Entry(top, textvariable=self.path_var, width=55)
        path_entry.pack(side="left", padx=(4, 8), fill="x", expand=True)

        self.btn_goto = ttk.Button(top, text="Перейти", command=self._goto_path)
        self.btn_goto.pack(side="left", padx=(0, 10))

        # Переключатель безопасного режима
        self.safe_var = tk.BooleanVar(value=self.safe_mode)
        self.chk_safe = ttk.Checkbutton(
            top, text="🔒 Безопасный режим (только SD)",
            variable=self.safe_var, command=self._toggle_safe_mode)
        self.chk_safe.pack(side="right")

        # Панель действий
        actions = ttk.Frame(self, padding=(6, 2, 6, 2))
        actions.pack(fill="x")

        self.btn_download = ttk.Button(actions, text="⬇️ Скачать",
                                       command=self._download_file, state="disabled")
        self.btn_download.pack(side="left", padx=(0, 4))

        self.btn_upload = ttk.Button(actions, text="⬆️ Загрузить",
                                     command=self._upload_file)
        self.btn_upload.pack(side="left", padx=(0, 4))

        self.btn_rename = ttk.Button(actions, text="✏️ Переименовать",
                                     command=self._rename_file, state="disabled")
        self.btn_rename.pack(side="left", padx=(0, 4))

        self.btn_delete = ttk.Button(actions, text="🗑 Удалить",
                                     command=self._delete_file, state="disabled")
        self.btn_delete.pack(side="left", padx=(0, 4))

        # Кнопка «Вырезать»
        self.btn_cut = ttk.Button(actions, text="✂️ Вырезать",
                                  command=self._cut_file, state="disabled")
        self.btn_cut.pack(side="left", padx=(0, 4))

        # Кнопка «Вставить» (изначально отключена)
        self.btn_paste = ttk.Button(actions, text="📋 Вставить",
                                    command=self._paste_file, state="disabled")
        self.btn_paste.pack(side="left", padx=(0, 4))

        self.btn_mkdir = ttk.Button(actions, text="📁 Создать папку",
                                    command=self._mkdir)
        self.btn_mkdir.pack(side="left", padx=(0, 4))

        # Дерево файлов
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=4)

        cols = ("name", "type", "size", "modified")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings",
                                selectmode="browse")
        self.tree.heading("#0", text="")
        self.tree.heading("name", text="Имя")
        self.tree.heading("type", text="Тип")
        self.tree.heading("size", text="Размер")
        self.tree.heading("modified", text="Изменён")

        self.tree.column("#0", width=0, stretch=False)
        self.tree.column("name", width=350, anchor="w")
        self.tree.column("type", width=70, anchor="center")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("modified", width=130, anchor="center")

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)

    # ── Подключение ───────────────────────────────────────────────

    def _connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            hostname=self.host,
            username=self.username,
            password=self.password,
            timeout=10,
            look_for_keys=False,
            allow_agent=False,
        )
        self.sftp = self.ssh.open_sftp()

    def _connect_and_list(self):
        if not self._alive:
            return
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        try:
            self._connect()
            self._set_status("Подключено")
            self.after(0, self._list_dir)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror(
                "Ошибка SSH", f"Не удалось подключиться:\n{err}",
                parent=self.root_window))
            self._set_status(f"Ошибка: {err}")

    # ── Навигация ─────────────────────────────────────────────────

    def _is_path_allowed(self, path):
        """Проверяет, разрешён ли путь в текущем режиме."""
        if not self.safe_mode:
            return True
        norm = posixpath.normpath(path)
        safe = posixpath.normpath(self.safe_root)
        return norm == safe or norm.startswith(safe + "/")

    def _go_up(self):
        parent = posixpath.dirname(self.current_path.rstrip("/"))
        if not parent:
            parent = "/"
        if not self._is_path_allowed(parent):
            self._set_status("🔒 Безопасный режим: нельзя подняться выше SD-карты")
            return
        self.current_path = parent
        self._list_dir()

    def _goto_path(self):
        new_path = self.path_var.get().strip()
        if not new_path:
            return
        if not self._is_path_allowed(new_path):
            self._set_status("🔒 Безопасный режим: доступ только к SD-карте")
            messagebox.showwarning("Ограничение",
                                   "В безопасном режиме доступен только путь:\n" + self.safe_root,
                                   parent=self.root_window)
            self.path_var.set(self.current_path)
            return
        self.current_path = new_path
        self._list_dir()

    def _refresh(self):
        self._dir_size_cache.clear()
        self._list_dir()

    def _on_double_click(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        item_type = item["values"][1]
        if item_type == "Папка":
            name = item["values"][0]
            new_path = posixpath.join(self.current_path, name)
            if not self._is_path_allowed(new_path):
                self._set_status("🔒 Доступ запрещён")
                return
            self.current_path = new_path
            self._list_dir()

    # ── Список файлов ─────────────────────────────────────────────

    def _list_dir(self):
        if not self._alive:
            return
        threading.Thread(target=self._list_dir_thread, daemon=True).start()

    def _list_dir_thread(self):
        if not self.sftp:
            self._set_status("Нет подключения")
            return
        try:
            entries = self.sftp.listdir_attr(self.current_path)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._set_status(f"Ошибка чтения: {err}"))
            return

        dirs = []
        files = []

        for attr in entries:
            name = attr.filename
            is_dir = bool(attr.st_mode and (attr.st_mode & 0o040000))
            if is_dir:
                dirs.append((name, 0, attr.st_mtime or 0))
            else:
                files.append((name, attr.st_size or 0, attr.st_mtime or 0))

        dirs.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())

        def update_ui():
            self.tree.delete(*self.tree.get_children())
            for name, _size, mtime in dirs:
                self.tree.insert("", "end", iid=name,
                                text="📁",
                                values=(name, "Папка", "…", _fmt_date(mtime)))
            for name, size, mtime in files:
                self.tree.insert("", "end", iid=name,
                                text="📄",
                                values=(name, "Файл", _fmt_size(size), _fmt_date(mtime)))
            self.path_var.set(self.current_path)
            self._set_status(f"Папка: {self.current_path} — {len(dirs)} папок, {len(files)} файлов")
            self._update_buttons(None)

        self.after(0, update_ui)

        # Считаем размеры папок в фоне
        if dirs:
            threading.Thread(target=self._calc_dir_sizes_thread,
                            args=([d[0] for d in dirs],), daemon=True).start()

    def _calc_dir_sizes_thread(self, dir_names):
        """Считает размеры папок с кэшированием, в отдельном SFTP-подключении."""
        aux_ssh = None
        aux_sftp = None

        # Сначала проверяем кэш
        uncached = []
        for name in dir_names:
            full_path = posixpath.join(self.current_path, name)
            if full_path in self._dir_size_cache:
                size = self._dir_size_cache[full_path]
                if name in self.tree.get_children():
                    self.after(0, lambda n=name, s=size: self._update_dir_size(n, s))
            else:
                uncached.append(name)

        if not uncached:
            return  # всё из кэша, подключение не нужно

        try:
            aux_ssh = paramiko.SSHClient()
            aux_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            aux_ssh.connect(
                hostname=self.host,
                username=self.username,
                password=self.password,
                timeout=10,
                look_for_keys=False,
                allow_agent=False,
            )
            aux_sftp = aux_ssh.open_sftp()

            for name in uncached:
                if not self._alive:
                    break
                full_path = posixpath.join(self.current_path, name)
                try:
                    size = self._dir_size_recursive_safe(aux_sftp, full_path)
                    self._dir_size_cache[full_path] = size  # ← сохраняем в кэш
                    if name in self.tree.get_children():
                        self.after(0, lambda n=name, s=size: self._update_dir_size(n, s))
                except Exception:
                    if name in self.tree.get_children():
                        self.after(0, lambda n=name: self._update_dir_size(n, -1))
        except Exception:
            pass
        finally:
            try:
                if aux_sftp:
                    aux_sftp.close()
            except Exception:
                pass
            try:
                if aux_ssh:
                    aux_ssh.close()
            except Exception:
                pass

    def _dir_size_recursive_safe(self, sftp, path):
        """Рекурсивно считает размер папки через отдельное SFTP-соединение."""
        total = 0
        try:
            entries = sftp.listdir_attr(path)
        except Exception:
            return 0
        for attr in entries:
            full = posixpath.join(path, attr.filename)
            if attr.st_mode and (attr.st_mode & 0o040000):
                total += self._dir_size_recursive_safe(sftp, full)
            else:
                total += attr.st_size or 0
        return total

    def _update_dir_size(self, name, size):
        """Обновляет размер папки в дереве."""
        if not self._alive or name not in self.tree.get_children():
            return
        item = self.tree.item(name)
        values = list(item["values"])
        if size < 0:
            values[2] = "—"
        else:
            values[2] = _fmt_size(size)
        self.tree.item(name, values=values)

    # ── Выбор ─────────────────────────────────────────────────────

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self._update_buttons(None)
            self.btn_cut.config(state="disabled")
            return
        name = sel[0]
        item = self.tree.item(name)
        is_dir = item["values"][1] == "Папка"
        self._update_buttons({"name": name, "is_dir": is_dir})
        self.btn_cut.config(state="normal")

    def _update_buttons(self, selection):
        if selection is None:
            self.btn_download.config(state="disabled")
            self.btn_rename.config(state="disabled")
            self.btn_delete.config(state="disabled")
            return
        is_dir = selection["is_dir"]
        self.btn_download.config(state="disabled" if is_dir else "normal")
        self.btn_rename.config(state="normal")
        self.btn_delete.config(state="normal")

    # ── Безопасный режим ──────────────────────────────────────────

    def _toggle_safe_mode(self):
        self.safe_mode = self.safe_var.get()
        if self.safe_mode:
            # Если включили — проверяем текущий путь
            if not self._is_path_allowed(self.current_path):
                self.current_path = self.safe_root
                self._list_dir()
            self._set_status("🔒 Безопасный режим включён")
        else:
            self._set_status("⚠️ Безопасный режим выключен — полный доступ")

    # ── Действия ──────────────────────────────────────────────────

    def _get_selected_path(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return posixpath.join(self.current_path, sel[0])

    def _download_file(self):
        remote_path = self._get_selected_path()
        if not remote_path:
            return
        if not self._is_path_allowed(remote_path):
            self._set_status("🔒 Доступ запрещён")
            return

        filename = posixpath.basename(remote_path)
        local_path = filedialog.asksaveasfilename(
            parent=self.root_window,
            title="Сохранить файл",
            initialfile=filename,
        )
        if not local_path:
            return

        self.btn_download.config(state="disabled")
        self._set_status(f"Скачивание: {filename}…")
        threading.Thread(target=self._download_thread,
                         args=(remote_path, local_path), daemon=True).start()

    def _download_thread(self, remote_path, local_path):
        filename = posixpath.basename(remote_path)
        try:
            file_size = self.sftp.stat(remote_path).st_size
        except Exception:
            file_size = 0

        self.after(0, lambda: self.progress.config(maximum=100, value=0))

        def callback(transferred, total):
            pct = int((transferred / total) * 100) if total > 0 else 0
            self.after(0, lambda p=pct: (
                self.progress.config(value=p),
                self._set_status(f"⬇️ {filename}… {p}%")
            ))

        try:
            self.sftp.get(remote_path, local_path, callback=callback)
            self.after(0, lambda: self.progress.config(value=100))
            self.after(0, lambda: self._set_status(f"✅ Скачано: {os.path.basename(local_path)}"))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror(
                "Ошибка", f"Не удалось скачать:\n{err}", parent=self.root_window))
            self.after(0, lambda: self._set_status(f"❌ Ошибка: {err}"))
        finally:
            self.after(0, lambda: self.progress.config(value=0))
            self.after(0, lambda: self.btn_download.config(state="normal"))

    def _upload_file(self):
        if not self._is_path_allowed(self.current_path):
            self._set_status("🔒 Доступ запрещён")
            return

        local_path = filedialog.askopenfilename(
            parent=self.root_window,
            title="Выберите файл для загрузки",
        )
        if not local_path:
            return

        filename = os.path.basename(local_path)
        remote_path = posixpath.join(self.current_path, filename)

        self.btn_upload.config(state="disabled")
        self._set_status(f"Загрузка: {filename}…")
        threading.Thread(target=self._upload_thread,
                         args=(local_path, remote_path), daemon=True).start()

    def _upload_thread(self, local_path, remote_path):
        filename = os.path.basename(local_path)
        try:
            file_size = os.path.getsize(local_path)
        except Exception:
            file_size = 0

        self.after(0, lambda: self.progress.config(maximum=100, value=0))

        def callback(transferred, total):
            pct = int((transferred / total) * 100) if total > 0 else 0
            self.after(0, lambda p=pct: (
                self.progress.config(value=p),
                self._set_status(f"⬆️ {filename}… {p}%")
            ))

        try:
            self.sftp.put(local_path, remote_path, callback=callback)
            self._dir_size_cache.pop(self.current_path, None)
            self.after(0, lambda: self.progress.config(value=100))
            self.after(0, lambda: self._set_status(f"✅ Загружено: {filename}"))
            self.after(0, self._list_dir)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror(
                "Ошибка", f"Не удалось загрузить:\n{err}", parent=self.root_window))
            self.after(0, lambda: self._set_status(f"❌ Ошибка: {err}"))
        finally:
            self.after(0, lambda: self.progress.config(value=0))
            self.after(0, lambda: self.btn_upload.config(state="normal"))

    def _rename_file(self):
        remote_path = self._get_selected_path()
        if not remote_path:
            return
        if not self._is_path_allowed(remote_path):
            self._set_status("🔒 Доступ запрещён")
            return

        old_name = posixpath.basename(remote_path)
        new_name = tk.simpledialog.askstring(
            "Переименование", "Новое имя:", initialvalue=old_name,
            parent=self.root_window)
        if not new_name or new_name == old_name:
            return

        new_path = posixpath.join(self.current_path, new_name)
        self.btn_rename.config(state="disabled")
        self._set_status(f"Переименование: {old_name} → {new_name}…")
        threading.Thread(target=self._rename_thread,
                        args=(remote_path, new_path, old_name, new_name),
                        daemon=True).start()

    def _rename_thread(self, remote_path, new_path, old_name, new_name):
        if not self._alive:
            return
        try:
            # Проверяем, не существует ли уже файл с новым именем
            try:
                self.sftp.stat(new_path)
                self.after(0, lambda: messagebox.showerror(
                    "Ошибка", f"Файл или папка «{new_name}» уже существует.",
                    parent=self.root_window))
                self.after(0, lambda: self._set_status(f"❌ Имя «{new_name}» занято"))
                return
            except IOError:
                pass  # файла нет — отлично, переименовываем

            # Используем только shell mv (SFTP rename на TrimUI не работает)
            stdin, stdout, stderr = self.ssh.exec_command(
                f'mv "{remote_path}" "{new_path}"', timeout=10)
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if err:
                raise Exception(err)

            self._dir_size_cache.pop(remote_path, None)
            self._dir_size_cache.pop(self.current_path, None)
            self.after(0, lambda: self._set_status(f"✅ Переименовано: {old_name} → {new_name}"))
            self.after(0, self._list_dir)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror(
                "Ошибка", f"Не удалось переименовать:\n{err}",
                parent=self.root_window))
            self.after(0, lambda: self._set_status(f"❌ Ошибка: {err}"))
        finally:
            self.after(0, lambda: self.btn_rename.config(state="normal"))


    def _delete_file(self):
        remote_path = self._get_selected_path()
        if not remote_path:
            return
        if not self._is_path_allowed(remote_path):
            self._set_status("🔒 Доступ запрещён")
            return

        name = posixpath.basename(remote_path)
        item = self.tree.item(name)
        is_dir = item["values"][1] == "Папка"

        if is_dir:
            msg = f"Удалить папку со всем содержимым?\n{name}\n\nЭто необратимо!"
        else:
            msg = f"Удалить файл?\n{name}\n\nЭто необратимо!"

        if not messagebox.askyesno("Удаление", msg, icon="warning",
                                   parent=self.root_window):
            return

        self.btn_delete.config(state="disabled")
        self._set_status(f"Удаление: {name}…")
        threading.Thread(target=self._delete_thread,
                         args=(remote_path, is_dir), daemon=True).start()

    def _delete_thread(self, remote_path, is_dir):
        try:
            if is_dir:
                self._rmdir_recursive(remote_path)
                self._dir_size_cache.pop(remote_path, None)
            else:
                self.sftp.remove(remote_path)
            self._dir_size_cache.pop(self.current_path, None)
            self.after(0, lambda: self._set_status(f"✅ Удалено: {posixpath.basename(remote_path)}"))
            self.after(0, self._list_dir)
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror(
                "Ошибка", f"Не удалось удалить:\n{err}", parent=self.root_window))
            self.after(0, lambda: self._set_status(f"❌ Ошибка: {err}"))
        finally:
            self.after(0, lambda: self.btn_delete.config(state="normal"))

    def _rmdir_recursive(self, path):
        """Рекурсивное удаление папки по SFTP."""
        entries = self.sftp.listdir(path)
        for entry in entries:
            full = posixpath.join(path, entry)
            try:
                attr = self.sftp.stat(full)
                if attr.st_mode and (attr.st_mode & 0o040000):
                    self._rmdir_recursive(full)
                else:
                    self.sftp.remove(full)
            except Exception:
                # Пробуем удалить как файл, если stat не помог
                try:
                    self.sftp.remove(full)
                except Exception:
                    pass
        self.sftp.rmdir(path)

    def _mkdir(self):
        if not self._is_path_allowed(self.current_path):
            self._set_status("🔒 Доступ запрещён")
            return

        name = tk.simpledialog.askstring(
            "Создать папку", "Имя папки:", parent=self.root_window)
        if not name:
            return

        new_path = posixpath.join(self.current_path, name)
        try:
            self.sftp.mkdir(new_path)
            self._dir_size_cache.pop(self.current_path, None)
            self._set_status(f"✅ Папка создана: {name}")
            self._list_dir()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать папку:\n{e}",
                                parent=self.root_window)

    # ── Cut/Paste логика ─────────────────────────────────────────

    def _cut_file(self):
        """Вырезает выбранный файл/папку (запоминает путь)."""
        remote_path = self._get_selected_path()
        if not remote_path:
            return
        if not self._is_path_allowed(remote_path):
            self._set_status("🔒 Доступ запрещён для вырезания")
            return

        name = posixpath.basename(remote_path)
        item = self.tree.item(name)
        is_dir = item["values"][1] == "Папка"

        msg = f"Вырезать «{name}»?\nЭто переместит объект в другую папку."
        if not messagebox.askyesno("Вырезать", msg, icon="warning", parent=self.root_window):
            return

        # Сохраняем в clipboard: путь и тип
        self._clipboard = {"path": remote_path, "is_dir": is_dir}
        self.btn_paste.config(state="normal")
        self._set_status(f"✂️ Вырезано: {name}")
        # Визуально можно подсветить выделение, но пока просто сообщение

    def _paste_file(self):
        """Вставляет (перемещает) вырезанный объект в текущую папку."""
        if self._clipboard is None:
            return

        src_path = self._clipboard["path"]
        is_dir = self._clipboard["is_dir"]
        src_name = posixpath.basename(src_path)

        dst_path = posixpath.join(self.current_path, src_name)

        # Проверка безопасности и для источника, и для назначения
        if not self._is_path_allowed(src_path):
            self._set_status("🔒 Источник вне безопасной зоны")
            messagebox.showerror("Ошибка", "Нельзя вырезать из запрещённой зоны.", parent=self.root_window)
            self._clipboard = None
            self.btn_paste.config(state="disabled")
            return

        if not self._is_path_allowed(dst_path):
            self._set_status("🔒 Нельзя вставить в запрещённую зону")
            messagebox.showerror("Ошибка", "Целевая папка вне безопасной зоны.", parent=self.root_window)
            return

        # Проверяем, не занято ли имя
        try:
            self.sftp.stat(dst_path)
            self._set_status(f"❌ Имя «{src_name}» уже занято")
            messagebox.showerror(
                "Ошибка", f"В текущей папке уже есть «{src_name}». Переименуйте или удалите его.",
                parent=self.root_window
            )
            return
        except IOError:
            pass  # имени нет — ок

        self.btn_paste.config(state="disabled")
        self.btn_cut.config(state="disabled")
        self._set_status(f"📋 Перемещаем: {src_name}…")

        threading.Thread(target=self._move_thread,
                         args=(src_path, dst_path, src_name), daemon=True).start()

    def _move_thread(self, src_path, dst_path, name):
        if not self._alive:
            return
        try:
            # Используем mv через SSH — надёжно на TrimUI
            stdin, stdout, stderr = self.ssh.exec_command(
                f'mv "{src_path}" "{dst_path}"', timeout=15)
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if err:
                raise Exception(err)

            # Очищаем кэш для обеих папок
            self._dir_size_cache.pop(src_path, None)
            self._dir_size_cache.pop(self.current_path, None)

            self.after(0, lambda: self._set_status(f"✅ Перемещено: {name}"))
            self.after(0, self._list_dir)  # обновить текущую

            # Сбрасываем clipboard
            self._clipboard = None
            self.after(0, lambda: self.btn_paste.config(state="disabled"))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: messagebox.showerror(
                "Ошибка перемещения", f"Не удалось переместить:\n{err}", parent=self.root_window))
            self.after(0, lambda: self._set_status(f"❌ Ошибка: {err}"))
        finally:
            self.after(0, lambda: self.btn_paste.config(state="disabled"))

    # ── Вспомогательные ───────────────────────────────────────────

    def _set_status(self, text):
        if not self._alive:
            return
        self.after(0, lambda: self.lbl_status.config(text=text))

    def destroy(self):
        self._alive = False
        try:
            if self.sftp:
                self.sftp.close()
        except Exception:
            pass
        try:
            if self.ssh:
                self.ssh.close()
        except Exception:
            pass
        super().destroy()

