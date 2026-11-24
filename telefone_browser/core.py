"""Integración con ADB, scrcpy y las ventanas de Cinnamon en X11."""

import errno
import ipaddress
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


APP_NAME = "Telefone Browser"
SCREEN_TITLE = f"{APP_NAME} · Pantalla del teléfono"
PHONE_ROOT = PurePosixPath("/sdcard")


class AppError(Exception):
    pass


@dataclass(frozen=True)
class Quality:
    label: str
    size: int
    fps: int
    bitrate: str


QUALITIES = (
    Quality("Ahorro · 540 px / 15 FPS", 540, 15, "1M"),
    Quality("Fluido · 720 px / 24 FPS", 720, 24, "2M"),
    Quality("Detalle · 1080 px / 30 FPS", 1080, 30, "4M"),
)


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str
    transport: str

    @property
    def ready(self):
        return self.state == "device"

    @property
    def label(self):
        suffix = {
            "unauthorized": " · Sin autorizar",
            "offline": " · Fuera de línea",
            "no permissions": " · Sin permiso USB",
        }.get(self.state, "" if self.ready else f" · {self.state}")
        return f"{self.model or self.serial} · {self.transport}{suffix}"


@dataclass(frozen=True)
class PhoneEntry:
    name: str
    directory: bool


@dataclass(frozen=True)
class Downloads:
    saved: tuple[Path, ...]
    error: str = ""


def wireless_address(value):
    try:
        host, port = value.strip().rsplit(":", 1)
        ip = ipaddress.IPv4Address(host)
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
            raise ValueError
    except ValueError:
        raise AppError("Ingresá la dirección IPv4 y el puerto que muestra Android.") from None
    return f"{ip}:{int(port)}"


def pairing_code(value):
    code = value.strip()
    if not re.fullmatch(r"[0-9]{6}", code):
        raise AppError("Ingresá el código de vinculación de seis dígitos.")
    return code


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        serial, separator, detail = line.partition("\t")
        if not separator:
            # adb devices -l uses spaces in some releases.
            fields = line.split(maxsplit=1)
            if len(fields) != 2 or fields[1].startswith("of devices"):
                continue
            serial, detail = fields
        fields = detail.split()
        if not serial or not fields:
            continue
        state = "no permissions" if fields[:2] == ["no", "permissions"] else fields[0]
        model = next((word[6:].replace("_", " ") for word in fields if word.startswith("model:")), "")
        wireless = ":" in serial or serial.rstrip(".").endswith("._adb-tls-connect._tcp")
        transport = "Wi-Fi" if wireless else "USB"
        devices.append(Device(serial, state, model, transport))
    return devices


def check_phone_path(path):
    if not path.is_relative_to(PHONE_ROOT) or ".." in path.parts:
        raise AppError("Elegí una carpeta dentro del almacenamiento compartido.")


def phone_entries(data):
    entries = []
    for record in data.split(b"\x00"):
        if record[:1] not in (b"d", b"f"):
            continue
        try:
            name = record[1:].decode("utf-8")
        except UnicodeDecodeError:
            continue
        if name and name not in (".", "..") and "/" not in name:
            entries.append(PhoneEntry(name, record[:1] == b"d"))
    return sorted(entries, key=lambda item: (not item.directory, item.name.casefold()))


def command(argv, *, timeout=12, env=None, input_data=None, cancel=None):
    try:
        if cancel is None:
            result = subprocess.run(
                argv, input=input_data, capture_output=True, timeout=timeout, env=env,
            )
        else:
            result = interruptible_command(argv, timeout, env, cancel)
    except FileNotFoundError:
        raise AppError(f"No se encontró {Path(argv[0]).name}. Ejecutá instalar.sh.") from None
    except subprocess.TimeoutExpired:
        raise AppError(f"{Path(argv[0]).name} tardó demasiado en responder.") from None
    if result.returncode:
        message = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise AppError(message or f"{Path(argv[0]).name} terminó con código {result.returncode}.")
    return result.stdout


def interruptible_command(argv, timeout, env, cancel):
    if cancel.is_set():
        raise AppError("Descarga cancelada.")
    deadline = time.monotonic() + timeout
    with subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env) as process:
        try:
            while not cancel.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                except subprocess.TimeoutExpired:
                    continue
                return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
            raise AppError("Descarga cancelada.")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


class Backend:
    def __init__(self):
        engine = Path(__file__).resolve().parent.parent / "motor"
        self.adb = str(engine / "adb") if (engine / "adb").is_file() else "adb"
        self.scrcpy = str(engine / "scrcpy") if (engine / "scrcpy").is_file() else "scrcpy"
        self.environment = os.environ.copy()
        self.environment["ADB"] = self.adb
        if (engine / "scrcpy-server").is_file():
            self.environment["SCRCPY_SERVER_PATH"] = str(engine / "scrcpy-server")
        if (engine / "icon.png").is_file():
            self.environment["SCRCPY_ICON_PATH"] = str(engine / "icon.png")

    def adb_command(self, *args, serial=None, timeout=12, input_data=None, cancel=None):
        selection = ["-s", serial] if serial else []
        return command([self.adb, *selection, *args], timeout=timeout,
                       env=self.environment, input_data=input_data, cancel=cancel)

    def devices(self):
        data = self.adb_command("devices", "-l")
        return parse_devices(data.decode("utf-8", "replace"))

    def pair(self, address, code):
        output = self.adb_command("pair", address, timeout=35, input_data=f"{code}\n".encode())
        detail = output.decode("utf-8", "replace").strip()
        if "Successfully paired to " not in detail:
            raise AppError(detail or "Android no confirmó la vinculación.")

    def connect(self, address):
        detail = self.adb_command("connect", address, timeout=20).decode("utf-8", "replace").strip()
        if not detail.startswith(("connected to ", "already connected to ")):
            raise AppError(detail or "Android no confirmó la conexión.")
        state = self.adb_command("get-state", serial=address).strip()
        if state != b"device":
            raise AppError("El teléfono todavía no está listo. Revisá Depuración inalámbrica.")

    def start_screen(self, serial, quality, allow_control, log):
        args = [
            self.scrcpy, "--serial", serial, "--window-title", SCREEN_TITLE,
            "--window-height=530", "--video-codec=h264",
            f"--max-size={quality.size}", f"--max-fps={quality.fps}",
            f"--video-bit-rate={quality.bitrate}", "--no-audio", "--no-clipboard-autosync",
        ]
        if not allow_control:
            args.append("--no-control")
        return subprocess.Popen(args, env={**self.environment, "SDL_VIDEODRIVER": "x11"},
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)

    def list_folder(self, serial, folder):
        check_phone_path(folder)
        # One remote shell, no PTY and NUL separators keep spaces and newlines in names intact.
        script = "folder=" + shlex.quote(str(folder)) + r"""
if [ ! -d "$folder" ] || [ ! -r "$folder" ] || [ ! -x "$folder" ]; then
    printf '%s\n' 'La carpeta no existe o Android restringe el acceso.' >&2
    exit 1
fi
for item in "$folder"/* "$folder"/.[!.]* "$folder"/..?*; do
    case "${item##*/}" in .|..) continue ;; esac
    if [ -d "$item" ]; then
        printf 'd%s\000' "${item##*/}"
    elif [ -f "$item" ]; then
        printf 'f%s\000' "${item##*/}"
    fi
done
"""
        return phone_entries(self.adb_command("shell", "-T", script, serial=serial, timeout=25))

    def download(self, serial, files, destination, progress, cancel):
        saved = []
        with tempfile.TemporaryDirectory(prefix=".telefone-", dir=destination) as staging:
            for index, remote in enumerate(files, 1):
                check_phone_path(remote)
                progress(index, len(files), remote.name)
                stage = Path(staging) / "archivo"
                try:
                    self.adb_command("pull", str(remote), str(stage), serial=serial,
                                     timeout=1800, cancel=cancel)
                    saved.append(publish_download(stage, destination, remote.name))
                    stage.unlink()
                except (AppError, OSError) as error:
                    return Downloads(tuple(saved), f"{remote.name}\n{error}")
        return Downloads(tuple(saved))


def publish_download(source, destination, filename):
    stem, suffix = os.path.splitext(filename)
    attempt = 0
    hard_links = True
    while True:
        candidate = destination / (filename if attempt == 0 else f"{stem} ({attempt}){suffix}")
        try:
            if hard_links:
                os.link(source, candidate)
            else:
                output = candidate.open("xb")
                try:
                    with output, source.open("rb") as original:
                        shutil.copyfileobj(original, output)
                except OSError:
                    candidate.unlink()
                    raise
            return candidate
        except FileExistsError:
            attempt += 1
        except OSError as error:
            if not hard_links or error.errno not in (errno.EOPNOTSUPP, errno.EPERM, errno.EXDEV):
                raise
            hard_links = False


def screen_window(pid):
    output = command(["wmctrl", "-u", "-lp"], timeout=3).decode("utf-8", "replace")
    for row in output.splitlines():
        fields = row.split(maxsplit=4)
        if len(fields) == 5 and fields[2] == str(pid) and fields[4] == SCREEN_TITLE:
            return fields[0]
    return None


def act_on_window(window_id, action):
    if action == "show":
        command(["wmctrl", "-i", "-a", window_id], timeout=3)
    elif action == "hide":
        command(["xdotool", "windowminimize", window_id], timeout=3)
    else:
        state = {"fullscreen": "toggle,fullscreen", "above": "toggle,above"}[action]
        command(["wmctrl", "-i", "-r", window_id, "-b", state], timeout=3)
        if action == "fullscreen":
            command(["wmctrl", "-i", "-a", window_id], timeout=3)
