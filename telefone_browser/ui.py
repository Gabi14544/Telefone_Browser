"""Ventanas de GTK y tareas en segundo plano."""

import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event, Thread

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from .core import (
    APP_NAME, PHONE_ROOT, QUALITIES, AppError, Backend,
    act_on_window, pairing_code, screen_window, wireless_address,
)


def styled(widget, css_class):
    widget.get_style_context().add_class(css_class)
    return widget


def row(spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)


def column(spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)


def label(text="", css_class=None, *, wrap=False, lines=-1):
    widget = Gtk.Label(label=text, xalign=0)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_max_width_chars(62)
    if lines > 0:
        widget.set_lines(lines)
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    if css_class:
        styled(widget, css_class)
    return widget


def button(title, icon=None, css_class=None):
    widget = Gtk.Button(label=title)
    if icon:
        widget.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        widget.set_always_show_image(True)
    if css_class:
        styled(widget, css_class)
    return widget


def card(title, icon, css_class="card"):
    panel = styled(column(10), css_class)
    heading = row(8)
    heading.add(styled(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), "accent-icon"))
    heading.add(label(title, "section-title"))
    panel.add(heading)
    return panel


def feedback(widget, text, error=False):
    widget.set_text(text)
    widget.set_tooltip_text(text if error else None)
    context = widget.get_style_context()
    if error:
        context.add_class("error")
    else:
        context.remove_class("error")


def background(work, success, failure):
    def execute():
        try:
            result = work()
        except (AppError, OSError) as error:
            GLib.idle_add(failure, str(error))
        except Exception:
            logging.exception("Error en una tarea de Telefone Browser")
            GLib.idle_add(failure, "Ocurrió un error inesperado. Consultá la salida de la terminal.")
        else:
            GLib.idle_add(success, result)

    Thread(target=execute, daemon=True).start()


class AppDialog(Gtk.Dialog):
    def __init__(self, parent, title, width, height=-1):
        super().__init__(title=title, transient_for=parent, modal=True, destroy_with_parent=True)
        styled(self, "telefone-dialog")
        self.set_default_size(width, height)
        self.alive = True
        self.close_button = self.add_button("Cerrar", Gtk.ResponseType.CLOSE)
        self.connect("response", self._close_requested)
        self.connect("destroy", self._destroyed)
        self.body = column(12)
        self.body.set_border_width(16)
        self.get_content_area().pack_start(self.body, True, True, 0)

    def _close_requested(self, *_):
        self.destroy()

    def _destroyed(self, *_):
        self.alive = False


class WifiDialog(AppDialog):
    def __init__(self, parent):
        super().__init__(parent, "Conexión por Wi-Fi", 570)
        self.parent = parent
        self.backend = parent.backend
        self.body.add(label("Vinculá tu Samsung", "dialog-title"))
        self.body.add(label(
            "Conectá ambos equipos a la misma red. En el Samsung abrí Ajustes → "
            "Opciones de desarrollador → Depuración inalámbrica.",
            "secondary", wrap=True,
        ))

        pair_card = card("Vincular por primera vez", "network-wireless-symbolic")
        pair_card.add(label("Abrí «Vincular dispositivo mediante código de vinculación».", "secondary", wrap=True))
        pair_form = row()
        self.pair_address = self._entry("IP y puerto de vinculación", "192.168.1.45:37119")
        self.code = self._entry("Código de 6 dígitos", "••••••")
        self.code.set_width_chars(10)
        self.code.set_max_length(6)
        self.code.set_visibility(False)
        self.code.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.pair_button = button("Vincular", css_class="primary")
        self.pair_button.connect("clicked", self._pair)
        self.code.connect("activate", self._pair)
        pair_form.pack_start(self._field("IP y puerto de vinculación", self.pair_address), True, True, 0)
        pair_form.add(self._field("Código", self.code))
        pair_form.add(self.pair_button)
        self.pair_button.set_valign(Gtk.Align.END)
        pair_card.add(pair_form)
        self.body.add(pair_card)

        connect_card = card("Conectar el teléfono", "network-transmit-receive-symbolic")
        connect_card.add(label(
            "Usá «Dirección IP y puerto» en la pantalla principal de Depuración inalámbrica. "
            "El puerto de conexión es distinto al de vinculación.",
            "secondary", wrap=True,
        ))
        connect_form = row()
        self.connect_address = self._entry("IP y puerto de conexión", "192.168.1.45:42207")
        self.connect_button = button("Conectar", css_class="primary")
        self.connect_button.connect("clicked", self._connect_phone)
        self.connect_address.connect("activate", self._connect_phone)
        connect_form.pack_start(self._field("IP y puerto de conexión", self.connect_address), True, True, 0)
        connect_form.add(self.connect_button)
        self.connect_button.set_valign(Gtk.Align.END)
        connect_card.add(connect_form)
        self.body.add(connect_card)
        self.status = label("Si ya vinculaste este equipo, podés ir directo a Conectar.",
                            "secondary", wrap=True, lines=3)
        self.body.add(self.status)
        self.busy = False

    @staticmethod
    def _entry(name, placeholder):
        entry = Gtk.Entry(placeholder_text=placeholder)
        entry.get_accessible().set_name(name)
        entry.set_tooltip_text(name)
        return entry

    @staticmethod
    def _field(name, entry):
        field = column(4)
        title = label(name, "field-label")
        title.set_mnemonic_widget(entry)
        field.add(title)
        field.add(entry)
        return field

    def _set_busy(self, busy):
        self.busy = busy
        for widget in (self.pair_address, self.code, self.connect_address,
                       self.pair_button, self.connect_button):
            widget.set_sensitive(not busy)

    def _failure(self, message):
        if self.alive:
            self._set_busy(False)
            feedback(self.status, message, error=True)

    def _pair(self, *_):
        if self.busy:
            return
        try:
            address = wireless_address(self.pair_address.get_text())
            code = pairing_code(self.code.get_text())
        except AppError as error:
            self._failure(str(error))
            return
        self.code.set_text("")
        self._set_busy(True)
        feedback(self.status, "Vinculando. Mantené abierto el código en el Samsung…")

        def paired(_):
            if self.alive:
                self._set_busy(False)
                if not self.connect_address.get_text():
                    self.connect_address.set_text(address.split(":")[0] + ":")
                self.connect_address.grab_focus()
                self.connect_address.set_position(-1)
                feedback(self.status, "Equipo vinculado. Ingresá ahora la dirección de conexión.")

        background(lambda: self.backend.pair(address, code), paired, self._failure)

    def _connect_phone(self, *_):
        if self.busy:
            return
        try:
            address = wireless_address(self.connect_address.get_text())
        except AppError as error:
            self._failure(str(error))
            return
        self._set_busy(True)
        feedback(self.status, "Conectando al Samsung…")

        def connected(_):
            if self.parent.alive:
                self.parent.refresh_devices(preferred=address)
            if self.alive:
                self.destroy()

        background(lambda: self.backend.connect(address), connected, self._failure)


class FilesDialog(AppDialog):
    def __init__(self, parent, device):
        super().__init__(parent, "Archivos del teléfono", 610, 500)
        self.backend = parent.backend
        self.device = device
        self.folder = PHONE_ROOT
        self.loading = False
        self.cancel = None

        header = row()
        header.pack_start(label("Archivos del teléfono", "dialog-title"), True, True, 0)
        header.add(styled(label(device.transport), "connection-pill"))
        self.body.add(header)
        shortcuts = row()
        self.up = button("Subir", "go-up-symbolic")
        self.up.connect("clicked", lambda _: self.open_folder(self.folder.parent))
        shortcuts.add(self.up)
        self.shortcuts = []
        for title, path in (("Cámara", "DCIM/Camera"), ("Imágenes", "Pictures"), ("Descargas", "Download")):
            shortcut = button(title)
            shortcut.connect("clicked", lambda _, target=PHONE_ROOT / path: self.open_folder(target))
            shortcuts.add(shortcut)
            self.shortcuts.append(shortcut)
        refresh = button("Actualizar", "view-refresh-symbolic")
        refresh.connect("clicked", lambda _: self.open_folder(self.folder))
        shortcuts.pack_end(refresh, False, False, 0)
        self.shortcuts.append(refresh)
        self.body.add(shortcuts)
        self.path_label = label("Almacenamiento compartido", "path-label")
        self.path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.body.add(self.path_label)

        self.store = Gtk.ListStore(str, str, bool)
        self.tree = Gtk.TreeView(model=self.store, headers_visible=False, enable_search=True, search_column=1)
        icon_cell = Gtk.CellRendererPixbuf(xpad=9, ypad=6)
        self.tree.append_column(Gtk.TreeViewColumn("Tipo", icon_cell, icon_name=0))
        name_cell = Gtk.CellRendererText(ypad=6, ellipsize=Pango.EllipsizeMode.END)
        names = Gtk.TreeViewColumn("Nombre", name_cell, text=1)
        names.set_expand(True)
        self.tree.append_column(names)
        self.selection = self.tree.get_selection()
        self.selection.set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.connect("row-activated", self._activate_row)
        self.tree.get_accessible().set_name("Archivos y carpetas de Android")
        scroll = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        scroll.set_min_content_height(200)
        scroll.add(self.tree)
        self.body.pack_start(scroll, True, True, 0)

        actions = row(10)
        self.status = label("", "secondary", wrap=True, lines=3)
        actions.pack_start(self.status, True, True, 0)
        self.download_button = button("Descargar selección", "folder-download-symbolic", "primary")
        self.download_button.connect("clicked", self._choose_destination)
        actions.add(self.download_button)
        self.body.add(actions)
        self.selection.connect("changed", lambda _: self._update_actions())
        self.open_folder(self.folder)

    def _close_requested(self, *_):
        if self.cancel is not None:
            self.cancel.set()
            self.close_button.set_sensitive(False)
            feedback(self.status, "Cancelando la descarga…")
        else:
            self.destroy()

    def _destroyed(self, *_):
        if self.cancel is not None:
            self.cancel.set()
        super()._destroyed()

    def _selected_files(self):
        model, selected = self.selection.get_selected_rows()
        return [self.folder / model[path][1] for path in selected if not model[path][2]]

    def _update_actions(self):
        idle = not self.loading and self.cancel is None
        self.tree.set_sensitive(idle)
        self.up.set_sensitive(idle and self.folder != PHONE_ROOT)
        for shortcut in self.shortcuts:
            shortcut.set_sensitive(idle)
        self.download_button.set_sensitive(idle and bool(self._selected_files()))

    def _activate_row(self, _, path, _column):
        _, name, directory = self.store[path]
        if directory:
            self.open_folder(self.folder / name)

    def open_folder(self, folder):
        if self.loading or self.cancel is not None:
            return
        self.loading = True
        self._update_actions()
        feedback(self.status, "Leyendo la carpeta…")

        def opened(entries):
            if not self.alive:
                return
            self.folder = folder
            relative = folder.relative_to(PHONE_ROOT)
            self.path_label.set_text("Almacenamiento compartido" if not relative.parts else f"/{relative}")
            self.store.clear()
            for item in entries:
                self.store.append(("folder-symbolic" if item.directory else "text-x-generic-symbolic",
                                   item.name, item.directory))
            self.loading = False
            self._update_actions()
            message = f"{len(entries)} elementos" if entries else "La carpeta está vacía."
            feedback(self.status, message)

        def failed(message):
            if self.alive:
                self.loading = False
                self._update_actions()
                feedback(self.status, message, error=True)

        background(lambda: self.backend.list_folder(self.device.serial, folder), opened, failed)

    def _choose_destination(self, *_):
        files = self._selected_files()
        if not files or self.cancel is not None:
            return
        chooser = Gtk.FileChooserDialog(title="Guardar en la computadora", transient_for=self,
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Guardar aquí", Gtk.ResponseType.ACCEPT)
        chooser.set_default_response(Gtk.ResponseType.ACCEPT)
        downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        chooser.set_current_folder(downloads if downloads and Path(downloads).is_dir() else str(Path.home()))
        response = chooser.run()
        folder = chooser.get_filename()
        chooser.destroy()
        if response == Gtk.ResponseType.ACCEPT and folder:
            self._download(files, Path(folder))

    def _download(self, files, destination):
        cancel = self.cancel = Event()
        self.close_button.set_label("Cancelar descarga")
        self._update_actions()
        feedback(self.status, "Preparando descarga…")

        def progress(index, count, name):
            def update():
                if self.alive and not cancel.is_set():
                    feedback(self.status, f"Descargando {index} de {count} · {name}")
            GLib.idle_add(update)

        def finished(result=None, error=""):
            if not self.alive:
                return
            self.cancel = None
            self.close_button.set_label("Cerrar")
            self.close_button.set_sensitive(True)
            self._update_actions()
            if result is None:
                feedback(self.status, error, error=True)
                return
            count = len(result.saved)
            summary = f"{count} archivo(s) guardado(s) en {destination}."
            if cancel.is_set() and result.error:
                feedback(self.status, f"Descarga cancelada. {summary}")
            elif result.error:
                feedback(self.status, f"{summary}\n{result.error}", error=True)
            else:
                feedback(self.status, summary)

        background(lambda: self.backend.download(self.device.serial, files, destination, progress, cancel),
                   finished, lambda error: finished(error=error))


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(760, 548)
        self.set_position(Gtk.WindowPosition.CENTER)
        styled(self, "telefone")
        self.alive = True
        self.backend = Backend()
        self.devices = {}
        self.refreshing = False
        self.pending_preferred = None
        self.process = None
        self.screen_serial = None
        self.log = None
        self.window_id = None
        self.start_time = 0
        self.stopping_at = None
        self.window_error = False

        body = column(14)
        body.set_border_width(22)
        self.add(body)

        hero = styled(row(14), "hero")
        mark = styled(row(), "brand-mark")
        icon = Gtk.Image.new_from_icon_name("phone-symbolic", Gtk.IconSize.DIALOG)
        icon.set_pixel_size(28)
        mark.add(icon)
        mark.set_valign(Gtk.Align.CENTER)
        hero.add(mark)
        heading = column(3)
        heading.add(label(APP_NAME, "hero-title"))
        heading.add(label("La pantalla y los archivos de tu Android en la PC", "hero-subtitle", wrap=True))
        hero.pack_start(heading, True, True, 0)
        self.connection_badge = styled(label("Sin conexión"), "connection-pill")
        self.connection_badge.set_valign(Gtk.Align.CENTER)
        hero.add(self.connection_badge)
        body.add(hero)

        connection = card("Teléfono", "phone-symbolic")
        device_row = row()
        self.device_combo = Gtk.ComboBoxText()
        self.device_combo.get_accessible().set_name("Elegí el teléfono conectado")
        for cell in self.device_combo.get_cells():
            cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        device_row.pack_start(self.device_combo, True, True, 0)
        self.refresh_button = button("Actualizar", "view-refresh-symbolic")
        self.refresh_button.connect("clicked", lambda _: self.refresh_devices())
        device_row.add(self.refresh_button)
        wifi = button("Conectar por Wi-Fi", "network-wireless-symbolic", "primary")
        wifi.connect("clicked", self._open_wifi)
        device_row.add(wifi)
        connection.add(device_row)
        self.connection_status = label("", "secondary", wrap=True, lines=3)
        connection.add(self.connection_status)
        body.add(connection)

        controls = row(12)
        controls.set_homogeneous(True)
        screen = card("Compartir pantalla", "video-display-symbolic")
        controls.pack_start(screen, True, True, 0)
        quality_row = row()
        quality_row.add(label("Calidad", "field-label"))
        self.quality = Gtk.ComboBoxText()
        self.quality.get_accessible().set_name("Calidad de la transmisión")
        for preset in QUALITIES:
            self.quality.append_text(preset.label)
        self.quality.set_active(1)
        quality_row.pack_start(self.quality, True, True, 0)
        screen.add(quality_row)
        control_row = row()
        control_row.pack_start(label("Control con mouse y teclado"), True, True, 0)
        self.allow_control = Gtk.Switch(active=True)
        self.allow_control.get_accessible().set_name("Control con mouse y teclado")
        control_row.add(self.allow_control)
        screen.add(control_row)
        self.start_button = button("Iniciar transmisión", "media-playback-start-symbolic", "primary")
        self.start_button.connect("clicked", self._toggle_screen)
        screen.add(self.start_button)

        files = card("Archivos del teléfono", "folder-symbolic")
        controls.pack_start(files, True, True, 0)
        files.pack_start(label("Guardá fotos, videos y documentos del almacenamiento compartido.",
                               "secondary", wrap=True), True, True, 0)
        self.files_button = button("Explorar archivos", "folder-open-symbolic")
        self.files_button.connect("clicked", self._open_files)
        files.add(self.files_button)
        body.add(controls)

        window = card("Ventana de transmisión", "window-maximize-symbolic")
        actions = row()
        self.window_buttons = []
        for action, title, icon_name in (
            ("show", "Mostrar", "view-reveal-symbolic"),
            ("hide", "Ocultar", "window-minimize-symbolic"),
            ("fullscreen", "Pantalla completa", "view-fullscreen-symbolic"),
            ("above", "Siempre visible", "view-pin-symbolic"),
        ):
            action_button = button(title, icon_name)
            action_button.connect("clicked", lambda _, name=action: self._window_action(name))
            actions.pack_start(action_button, True, True, 0)
            self.window_buttons.append(action_button)
        window.add(actions)
        self.screen_status = label("La pantalla se abre en una ventana que podés mover y redimensionar.",
                                   "secondary", wrap=True, lines=3)
        window.add(self.screen_status)
        body.add(window)

        self.device_combo.connect("changed", lambda _: self._update_controls())
        self.connect("destroy", self._destroyed)
        self.update_source = GLib.timeout_add(500, self._track_screen)
        self._update_controls()
        self.refresh_devices()

    def _selected(self):
        return self.devices.get(self.device_combo.get_active_id())

    def _update_controls(self):
        device = self._selected()
        ready = device is not None and device.ready
        connection_text = f"{device.transport} conectado" if ready else "Sin conexión"
        self.connection_badge.set_text(connection_text)
        context = self.connection_badge.get_style_context()
        if ready:
            context.add_class("connected")
            message = f"{device.model or 'Android'} listo. Podés iniciar la transmisión o explorar archivos."
        else:
            context.remove_class("connected")
            message = {
                "unauthorized": "Desbloqueá el teléfono y aceptá la autorización de depuración.",
                "offline": "El teléfono está fuera de línea. Revisá la conexión y pulsá Actualizar.",
                "no permissions": "Falta permiso USB. Revisá las reglas de Android en Linux.",
            }.get(device.state if device else "", "Conectá por Wi-Fi o enchufá un cable USB de datos.")
        feedback(self.connection_status, message)
        active = self.process is not None
        self.start_button.set_label("Detener transmisión" if active else "Iniciar transmisión")
        icon = self.start_button.get_image()
        icon.set_from_icon_name("media-playback-stop-symbolic" if active else "media-playback-start-symbolic",
                                Gtk.IconSize.BUTTON)
        self.start_button.set_sensitive((active or ready) and self.stopping_at is None)
        self.files_button.set_sensitive(ready)
        self.device_combo.set_sensitive(not active and bool(self.devices))
        self.quality.set_sensitive(not active)
        self.allow_control.set_sensitive(not active)
        for control in self.window_buttons:
            control.set_sensitive(self.window_id is not None and self.stopping_at is None)

    def refresh_devices(self, preferred=None):
        if self.refreshing:
            self.pending_preferred = preferred or self.pending_preferred
            return
        self.refreshing = True
        self.refresh_button.set_sensitive(False)
        previous = self.device_combo.get_active_id()

        def refreshed(devices):
            if not self.alive:
                return
            self.refreshing = False
            order = sorted(devices, key=lambda d: (not d.ready, d.transport != "Wi-Fi", d.label))
            self.devices = {device.serial: device for device in order}
            self.device_combo.remove_all()
            for device in order:
                self.device_combo.append(device.serial, device.label)
            if not order:
                self.device_combo.append("", "Ningún teléfono conectado")
            chosen = self.screen_serial or preferred or previous
            if (not chosen or not self.device_combo.set_active_id(chosen)) and not self.screen_serial:
                self.device_combo.set_active(0)
            self.refresh_button.set_sensitive(True)
            self._update_controls()
            if self.pending_preferred:
                pending, self.pending_preferred = self.pending_preferred, None
                self.refresh_devices(pending)

        def failed(message):
            refreshed([])
            if self.alive:
                feedback(self.connection_status, message, error=True)

        background(self.backend.devices, refreshed, failed)

    def _open_wifi(self, *_):
        WifiDialog(self).show_all()

    def _open_files(self, *_):
        device = self._selected()
        if device and device.ready:
            FilesDialog(self, device).show_all()

    def _toggle_screen(self, *_):
        if self.process is not None:
            self.stopping_at = time.monotonic()
            self.process.terminate()
            feedback(self.screen_status, "Deteniendo la transmisión…")
        else:
            device = self._selected()
            if not device or not device.ready:
                return
            try:
                self.log = tempfile.TemporaryFile(mode="w+b")
                self.process = self.backend.start_screen(
                    device.serial, QUALITIES[self.quality.get_active()], self.allow_control.get_active(), self.log,
                )
            except OSError as error:
                if self.log is not None:
                    self.log.close()
                    self.log = None
                feedback(self.screen_status, f"No se pudo iniciar scrcpy. {error}", error=True)
                return
            self.screen_serial = device.serial
            self.start_time = time.monotonic()
            self.window_error = False
            feedback(self.screen_status, "Iniciando la transmisión…")
        self._update_controls()

    def _track_screen(self):
        if self.process is None:
            return GLib.SOURCE_CONTINUE
        code = self.process.poll()
        if code is not None:
            self._screen_finished(code)
        elif self.stopping_at is not None:
            if time.monotonic() - self.stopping_at > 2:
                self.process.kill()
        elif self.window_id is None and not self.window_error:
            try:
                self.window_id = screen_window(self.process.pid)
            except (AppError, OSError) as error:
                self.window_error = True
                feedback(self.screen_status, f"No se pudo buscar la ventana en X11. {error}", error=True)
            if self.window_id:
                self._update_controls()
                feedback(self.screen_status, "Transmitiendo · Arrastrá la barra de la ventana para moverla.")
            elif time.monotonic() - self.start_time > 18 and not self.window_error:
                feedback(self.screen_status, "La ventana todavía no apareció. Revisá el teléfono y la conexión.")
        return GLib.SOURCE_CONTINUE

    def _screen_finished(self, code):
        requested = self.stopping_at is not None
        self.log.seek(max(0, self.log.seek(0, 2) - 8192))
        lines = self.log.read().decode("utf-8", "replace").splitlines()
        self.log.close()
        self.process = self.log = self.window_id = self.stopping_at = self.screen_serial = None
        self._update_controls()
        if requested or code == 0:
            feedback(self.screen_status, "Transmisión detenida.")
        else:
            errors = [line for line in lines if "ERROR:" in line or "WARN:" in line]
            detail = "\n".join((errors or lines)[-3:])
            feedback(self.screen_status, f"Se interrumpió la transmisión.\n{detail}".strip(), error=True)
            self.refresh_devices()

    def _window_action(self, action):
        if self.window_id is None:
            return
        try:
            act_on_window(self.window_id, action)
        except (AppError, OSError) as error:
            feedback(self.screen_status, str(error), error=True)
        else:
            messages = {
                "show": "Ventana visible · La transmisión sigue activa.",
                "hide": "Ventana oculta · Pulsá Mostrar para recuperarla.",
                "fullscreen": "Pantalla completa alternada · Alt+Tab vuelve al panel.",
                "above": "Opción Siempre visible alternada.",
            }
            feedback(self.screen_status, messages[action])

    def _destroyed(self, *_):
        self.alive = False
        GLib.source_remove(self.update_source)
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.log.close()


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="ar.telefonebrowser.Desktop")

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            css = Gtk.CssProvider()
            css.load_from_path(str(Path(__file__).with_name("style.css")))
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Gtk.Window.set_default_icon_name("phone")
            window = MainWindow(self)
            window.show_all()
        window.present()


def run():
    return Application().run(sys.argv)
