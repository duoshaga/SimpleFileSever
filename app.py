import html
import ctypes
import io
import os
import socket
import sys
import threading
import time
import urllib.parse
import zipfile
from ctypes import wintypes
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def app_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SETTINGS_FILE = app_directory() / "settings.ini"


class SingleInstance:
    def __init__(self, name):
        self.handle = None
        self.acquired = True

        if os.name != "nt":
            return

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = kernel32.CreateMutexW(None, False, name)
        self.acquired = bool(self.handle) and kernel32.GetLastError() != 183

    def close(self):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def load_last_folder():
    try:
        folder = SETTINGS_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return Path.home()

    if folder and os.path.isdir(folder):
        return Path(folder)
    return Path.home()


def save_last_folder(folder):
    try:
        SETTINGS_FILE.write_text(str(Path(folder).resolve()), encoding="utf-8")
    except OSError:
        pass


class DownloadRateLimiter:
    def __init__(self, kb_per_second=0):
        self.lock = threading.Lock()
        self.bytes_per_second = 0
        self.tokens = 0.0
        self.updated_at = time.monotonic()
        self.set_limit(kb_per_second)

    def set_limit(self, kb_per_second):
        with self.lock:
            self.bytes_per_second = max(0, int(kb_per_second)) * 1024
            self.tokens = 0.0
            self.updated_at = time.monotonic()

    def chunk_size(self):
        rate = self.bytes_per_second
        if rate <= 0:
            return 64 * 1024
        return max(1024, min(64 * 1024, rate // 10 or 1024))

    def wait_for(self, byte_count):
        if byte_count <= 0:
            return

        while True:
            with self.lock:
                rate = self.bytes_per_second
                if rate <= 0:
                    return

                now = time.monotonic()
                elapsed = now - self.updated_at
                capacity = max(rate, byte_count)
                self.tokens = min(capacity, self.tokens + elapsed * rate)
                self.updated_at = now

                if self.tokens >= byte_count:
                    self.tokens -= byte_count
                    return

                delay = (byte_count - self.tokens) / rate

            time.sleep(min(delay, 0.25))


class FileRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, rate_limiter=None, **kwargs):
        self.rate_limiter = rate_limiter or DownloadRateLimiter()
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        target = Path(self.translate_path(parsed.path)).resolve()

        if query.get("download") == ["1"] and target.is_dir():
            self.send_directory_zip(target)
            return

        super().do_GET()

    def list_directory(self, path):
        try:
            entries = sorted(os.listdir(path), key=lambda name: name.lower())
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None

        parsed = urllib.parse.urlsplit(self.path)
        current_path = parsed.path
        display_path = html.escape(urllib.parse.unquote(current_path), quote=False)
        rows = []

        if current_path.rstrip("/") != "":
            parent = urllib.parse.urljoin(current_path, "../")
            rows.append(f'<li><a href="{html.escape(parent)}">../</a></li>')

        for name in entries:
            full_path = Path(path, name)
            quoted_name = urllib.parse.quote(name)
            escaped_name = html.escape(name, quote=False)

            if full_path.is_dir():
                folder_href = quoted_name + "/"
                download_href = folder_href + "?download=1"
                rows.append(
                    "<li>"
                    f'<a class="name" href="{folder_href}">{escaped_name}/</a>'
                    f'<a class="download" href="{download_href}">下载文件夹</a>'
                    "</li>"
                )
            else:
                rows.append(f'<li><a class="name" href="{quoted_name}">{escaped_name}</a></li>')

        html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>文件列表 {display_path}</title>
<style>
body {{
    margin: 0;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    background: #f6f8fb;
    color: #1f2937;
}}
main {{
    max-width: 920px;
    margin: 0 auto;
    padding: 28px 18px;
}}
h1 {{
    margin: 0 0 18px;
    font-size: 24px;
}}
ul {{
    list-style: none;
    margin: 0;
    padding: 0;
    background: #fff;
    border: 1px solid #d8dde6;
    border-radius: 8px;
    overflow: hidden;
}}
li {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border-bottom: 1px solid #edf0f4;
}}
li:last-child {{
    border-bottom: none;
}}
a {{
    color: #1d4ed8;
    text-decoration: none;
}}
a:hover {{
    text-decoration: underline;
}}
.name {{
    flex: 1;
    overflow-wrap: anywhere;
}}
.download {{
    flex: none;
    color: #166534;
    font-size: 13px;
}}
</style>
</head>
<body>
<main>
<h1>文件列表 {display_path}</h1>
<ul>
{''.join(rows)}
</ul>
</main>
</body>
</html>
"""
        encoded = html_text.encode("utf-8", "surrogateescape")
        response = io.BytesIO()
        response.write(encoded)
        response.seek(0)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        return response

    def copyfile(self, source, outputfile):
        chunk_size = self.rate_limiter.chunk_size()
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            self.rate_limiter.wait_for(len(chunk))
            outputfile.write(chunk)

    def write_limited(self, data):
        chunk_size = self.rate_limiter.chunk_size()
        for index in range(0, len(data), chunk_size):
            chunk = data[index : index + chunk_size]
            self.rate_limiter.wait_for(len(chunk))
            self.wfile.write(chunk)

    def send_directory_zip(self, folder):
        base_folder = Path(self.directory).resolve()
        folder = folder.resolve()

        try:
            folder.relative_to(base_folder)
        except ValueError:
            self.send_error(403, "Directory is outside shared folder")
            return

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for root, dirs, files in os.walk(folder):
                dirs[:] = [name for name in dirs if not Path(root, name).is_symlink()]
                root_path = Path(root)

                if not files and not dirs:
                    arcname = root_path.relative_to(folder.parent).as_posix() + "/"
                    archive.writestr(arcname, "")

                for file_name in files:
                    file_path = root_path / file_name
                    if file_path.is_symlink():
                        continue
                    arcname = file_path.relative_to(folder.parent).as_posix()
                    archive.write(file_path, arcname)

        zip_data = zip_buffer.getvalue()
        filename = f"{folder.name or 'download'}.zip"
        quoted_filename = urllib.parse.quote(filename)

        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(zip_data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted_filename}")
        self.end_headers()
        self.write_limited(zip_data)


class FileServer:
    def __init__(self):
        self.httpd = None
        self.thread = None
        self.folder = None
        self.port = None
        self.rate_limiter = DownloadRateLimiter()

    @property
    def running(self):
        return self.httpd is not None

    def start(self, folder, port, speed_limit_kb):
        if self.running:
            return

        folder_path = Path(folder).resolve()
        self.rate_limiter.set_limit(speed_limit_kb)
        handler = partial(FileRequestHandler, directory=str(folder_path), rate_limiter=self.rate_limiter)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
        self.folder = folder_path
        self.port = port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if not self.running:
            return

        httpd = self.httpd
        self.httpd = None
        httpd.shutdown()
        httpd.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
        self.thread = None


def local_ip_addresses():
    addresses = {"127.0.0.1"}
    hostname = socket.gethostname()

    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("169.254."):
                addresses.add(ip)
    except socket.gaierror:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        addresses.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass

    return sorted(addresses, key=lambda value: (value.startswith("127."), value))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.server = FileServer()
        self.force_quit = False

        self.setWindowTitle("文件服务器")
        self.resize(680, 460)

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirLinkIcon)
        self.setWindowIcon(icon)
        self.build_ui()
        self.build_tray(icon)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.update_urls)

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("文件服务器")
        title.setObjectName("title")
        subtitle = QLabel("选择一个文件夹，启动后同一网络内的设备可以通过下方地址访问。")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        settings = QGroupBox("共享设置")
        settings_layout = QGridLayout(settings)
        settings_layout.setHorizontalSpacing(10)
        settings_layout.setVerticalSpacing(12)

        self.folder_input = QLineEdit(str(load_last_folder()))
        self.folder_input.setReadOnly(True)
        choose_button = QPushButton("选择文件夹")
        choose_button.clicked.connect(self.choose_folder)

        self.port_input = QSpinBox()
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(8000)

        self.speed_input = QSpinBox()
        self.speed_input.setRange(0, 1024 * 1024)
        self.speed_input.setValue(0)
        self.speed_input.setSpecialValueText("不限速")

        self.speed_unit_input = QComboBox()
        self.speed_unit_input.addItems(["KB/s", "MB/s"])

        settings_layout.addWidget(QLabel("开放文件夹"), 0, 0)
        settings_layout.addWidget(self.folder_input, 0, 1)
        settings_layout.addWidget(choose_button, 0, 2)
        settings_layout.addWidget(QLabel("端口"), 1, 0)
        settings_layout.addWidget(self.port_input, 1, 1)
        settings_layout.addWidget(QLabel("下载限速"), 2, 0)
        settings_layout.addWidget(self.speed_input, 2, 1)
        settings_layout.addWidget(self.speed_unit_input, 2, 2)

        layout.addWidget(settings)

        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(14, 12, 14, 12)
        self.status_label = QLabel("未启动")
        self.status_label.setObjectName("statusStopped")
        status_layout.addWidget(QLabel("状态："))
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addWidget(status_frame)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("启动")
        self.start_button.clicked.connect(self.start_server)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        urls_box = QGroupBox("当前可访问地址")
        urls_layout = QVBoxLayout(urls_box)
        self.urls_text = QTextEdit()
        self.urls_text.setReadOnly(True)
        self.urls_text.setPlaceholderText("启动后会显示访问地址")
        urls_layout.addWidget(self.urls_text)
        layout.addWidget(urls_box, stretch=1)

        self.setCentralWidget(root)
        self.setStyleSheet(
            """
            QWidget { font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 14px; }
            #title { font-size: 24px; font-weight: 700; }
            #subtitle { color: #58606f; }
            QGroupBox { border: 1px solid #d8dde6; border-radius: 6px; margin-top: 10px; padding: 14px 10px 10px 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit, QSpinBox, QComboBox, QTextEdit { border: 1px solid #cbd3df; border-radius: 5px; padding: 7px; background: #ffffff; }
            QPushButton { border: 1px solid #b8c0cc; border-radius: 5px; padding: 8px 16px; background: #f8fafc; }
            QPushButton:hover { background: #eef3f8; }
            QPushButton:disabled { color: #99a1ad; background: #f2f4f7; }
            #statusFrame { border: 1px solid #d8dde6; border-radius: 6px; background: #fbfcfe; }
            #statusRunning { color: #167342; font-weight: 700; }
            #statusStopped { color: #9a3412; font-weight: 700; }
            """
        )

    def build_tray(self, icon):
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("文件服务器")

        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self.show_from_tray)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.exit_app)

        from PyQt6.QtWidgets import QMenu

        tray_menu = QMenu()
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(exit_action)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择开放的文件夹", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)
            save_last_folder(folder)

    def start_server(self):
        folder = self.folder_input.text().strip()
        port = self.port_input.value()
        speed_limit_kb = self.speed_limit_kb()

        if not os.path.isdir(folder):
            QMessageBox.warning(self, "无法启动", "请选择一个有效的文件夹。")
            return

        try:
            self.server.start(folder, port, speed_limit_kb)
        except OSError as exc:
            QMessageBox.critical(self, "启动失败", f"端口 {port} 无法使用：{exc}")
            return

        self.status_label.setText("运行中")
        self.status_label.setObjectName("statusRunning")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.folder_input.setEnabled(False)
        self.port_input.setEnabled(False)
        self.speed_input.setEnabled(False)
        self.speed_unit_input.setEnabled(False)
        self.refresh_timer.start(5000)
        self.update_urls()
        self.tray.showMessage("文件服务器已启动", "可通过主界面中的地址访问共享文件夹。")

    def stop_server(self):
        self.refresh_timer.stop()
        self.server.stop()
        self.status_label.setText("未启动")
        self.status_label.setObjectName("statusStopped")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.folder_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.speed_input.setEnabled(True)
        self.speed_unit_input.setEnabled(True)
        self.urls_text.clear()

    def speed_limit_kb(self):
        value = self.speed_input.value()
        if value == 0:
            return 0
        if self.speed_unit_input.currentText() == "MB/s":
            return value * 1024
        return value

    def update_urls(self):
        if not self.server.running:
            return

        port = self.server.port
        urls = [f"http://{ip}:{port}/" for ip in local_ip_addresses()]
        self.urls_text.setPlainText("\n".join(urls))

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_from_tray()

    def closeEvent(self, event):
        if self.force_quit:
            self.server.stop()
            event.accept()
            return

        event.ignore()
        self.hide()
        self.tray.showMessage("文件服务器仍在后台运行", "右键托盘图标可以退出。")

    def exit_app(self):
        self.force_quit = True
        self.server.stop()
        self.tray.hide()
        QApplication.quit()


def main():
    single_instance = SingleInstance("Local\\FileServerSingleInstance")
    app = QApplication(sys.argv)

    if not single_instance.acquired:
        QMessageBox.information(None, "文件服务器已运行", "文件服务器已经在运行中，请不要重复启动。")
        single_instance.close()
        sys.exit(0)

    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    exit_code = app.exec()
    single_instance.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
