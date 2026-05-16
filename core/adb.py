"""
ADB Controller - xu ly moi tuong tac voi Android Debug Bridge.
"""
import subprocess
import os
import time
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# LDPlayer ADB TCP ports (index 0-5)
LD_PORTS = [5554, 5556, 5558, 5560, 5562, 5564]


class AdbController:
    def __init__(self, adb_path: str = "adb", serial: str = ""):
        self.adb_path = adb_path
        self.serial   = serial

    # ── Internal ──────────────────────────────────────────────────────────────

    def _base(self) -> list:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def _no_win(self) -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def _exec(self, cmd: list, timeout: int = 15) -> tuple[int, str, str]:
        """Chay lenh ADB bat ky (dung noi bo)."""
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=self._no_win(),
            )
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            logger.warning(f"ADB timeout: {cmd}")
            return -1, "", "timeout"
        except FileNotFoundError:
            logger.error(
                f"Khong tim thay ADB: '{self.adb_path}'\n"
                "  -> Tai ADB: https://developer.android.com/tools/releases/platform-tools\n"
                "  -> Nhap duong dan day du vao Settings."
            )
            return -1, "", "not_found"
        except Exception as e:
            return -1, "", str(e)

    def run(self, args: list, timeout: int = 15) -> tuple[int, str, str]:
        """Chay lenh ADB co -s serial (de tuong tac voi thiet bi cu the)."""
        return self._exec(self._base() + args, timeout)

    def _run_bare(self, args: list, timeout: int = 15) -> tuple[int, str, str]:
        """
        Chay lenh ADB server-level KHONG co -s flag.
        Dung cho: start-server, connect, devices.
        """
        return self._exec([self.adb_path] + args, timeout)

    # ── Connection ────────────────────────────────────────────────────────────

    def start_server(self):
        self._run_bare(["start-server"], timeout=15)

    def connect(self) -> bool:
        """
        'adb connect HOST:PORT' — lenh ADB server, phai chay KHONG co -s.
        Neu dung self.run() se them -s truoc khi device duoc connect,
        ADB se bao 'no devices found' va connect khong duoc thuc hien.
        """
        if ":" not in self.serial:
            return True
        _, out, _ = self._run_bare(["connect", self.serial], timeout=10)
        out_l = out.lower()
        return "connected" in out_l

    def devices(self) -> list[str]:
        """
        Lay danh sach serial cac thiet bi dang ket noi.
        Chay 'adb devices' KHONG co -s (day la lenh server-level).
        """
        _, out, _ = self._run_bare(["devices"])
        result = []
        for line in out.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                result.append(parts[0])
        return result

    def devices_raw(self) -> str:
        """Tra ve output thu cua 'adb devices -l' de debug."""
        _, out, _ = self._run_bare(["devices", "-l"])
        return out.strip()

    def is_connected(self) -> bool:
        devs = self.devices()
        if not self.serial:
            return len(devs) > 0
        return self.serial in devs

    def full_connect(self) -> tuple[bool, str]:
        """
        Ket noi day du theo 4 buoc:
          1. start-server
          2. connect serial chi dinh (neu co)
          3. kiem tra devices() — lay thiet bi dau tien neu co
          4. quet tung port LDPlayer bang 'adb connect' de tim thiet bi
        """
        self.start_server()
        time.sleep(0.4)

        # Buoc 2: thu ket noi serial cu the
        if self.serial and ":" in self.serial:
            self.connect()
            time.sleep(0.8)

        # Buoc 3: kiem tra devices hien tai
        if self.is_connected():
            return True, f"Da ket noi: {self.serial}"

        devs = self.devices()
        if devs:
            if self.serial not in devs:
                logger.info(f"Tu nhan thiet bi co san: {devs[0]}")
                self.serial = devs[0]
            return True, f"Da ket noi: {self.serial}"

        # Buoc 4: quet tung port LDPlayer (adb connect chu dong)
        # Can thiet khi LDPlayer dang chay nhung chua duoc connect vao ADB server
        logger.info("Khong thay thiet bi, bat dau quet port LDPlayer...")
        for port in LD_PORTS:
            candidate = f"127.0.0.1:{port}"
            old_serial = self.serial
            self.serial = candidate
            if self.connect():
                time.sleep(0.5)
                if self.is_connected():
                    logger.info(f"Tim thay LDPlayer tai {candidate}")
                    return True, f"Tu dong phat hien: {candidate}"
            self.serial = old_serial

        # Khong tim thay gi ca — hien thi output adb devices de debug
        raw = self.devices_raw()
        return False, (
            f"Khong tim thay thiet bi nao.\n\n"
            f"Output 'adb devices':\n{raw or '(rong)'}\n\n"
            f"Kiem tra:\n"
            f"  1. LDPlayer da mo va bat 'USB Debugging'\n"
            f"  2. Duong dan ADB trong Settings: {self.adb_path}\n"
            f"  3. Thu chay tay: {self.adb_path} connect 127.0.0.1:5554"
        )

    # ── Screen capture ────────────────────────────────────────────────────────

    def screenshot(self) -> Optional[np.ndarray]:
        """Chup man hinh, tra ve numpy BGR array."""
        import cv2
        try:
            proc = subprocess.run(
                self._base() + ["exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=20,
                creationflags=self._no_win(),
            )
            if proc.returncode == 0 and proc.stdout:
                data = np.frombuffer(proc.stdout, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if img is not None:
                    return img
            logger.warning("Screenshot tra ve du lieu rong.")
        except subprocess.TimeoutExpired:
            logger.warning("Screenshot timeout.")
        except Exception as e:
            logger.error(f"Screenshot loi: {e}")
        return None

    # ── Touch actions ─────────────────────────────────────────────────────────

    def tap(self, x: int, y: int, delay_ms: int = 150):
        """Nhan thuong tai (x, y)."""
        self.run(["shell", "input", "tap", str(x), str(y)])
        time.sleep(delay_ms / 1000.0)

    def long_press(self, x: int, y: int, ms: int = 900):
        """
        Nhan giu tai (x, y).
        ADB khong co lenh rieng cho long press —
        dung swipe tai cung diem voi duration dai.
        """
        self.run(["shell", "input", "swipe",
                  str(x), str(y), str(x), str(y), str(ms)])

    def hold_and_drag_path(
        self,
        hold_pt:  tuple[int, int],
        path_pts: list[tuple[int, int]],
        hold_ms:  int = 900,
        step_ms:  int = 150,
        max_len:  int = 6000,
    ) -> None:
        """
        Nhan giu tai hold_pt roi keo lien tuc qua path_pts ma khong nhac tay len.

        Thuc hien bang cach gom long press + toan bo drag thanh cac batch lenh
        adb shell duoc noi voi '&&'. Moi batch la 1 ket noi ADB duy nhat ->
        khong co khoang ho giua cac gesture.
        Long press luon nam trong batch dau tien.
        """
        if not path_pts:
            self.long_press(hold_pt[0], hold_pt[1], hold_ms)
            return

        hx, hy = hold_pt

        # Xay danh sach tat ca lenh: long press truoc, sau do tung doan drag
        all_cmds: list[str] = [f"input swipe {hx} {hy} {hx} {hy} {hold_ms}"]
        px, py = hx, hy
        for x, y in path_pts:
            all_cmds.append(f"input swipe {px} {py} {x} {y} {step_ms}")
            px, py = x, y

        # Gom thanh batch sao cho do dai moi batch <= max_len ky tu
        batches: list[list[str]] = []
        cur:     list[str] = []
        cur_len: int = 0
        for cmd in all_cmds:
            clen = len(cmd) + 4  # " && "
            if cur_len + clen > max_len and cur:
                batches.append(cur)
                cur, cur_len = [], 0
            cur.append(cmd)
            cur_len += clen
        if cur:
            batches.append(cur)

        for b in batches:
            est_timeout = int((hold_ms + len(b) * step_ms) / 1000) + 15
            self.run(["shell", " && ".join(b)], timeout=est_timeout)


# ── Factory ───────────────────────────────────────────────────────────────────

def make_adb(adb_path: str, emu_index: int) -> AdbController:
    """Tao AdbController voi serial LDPlayer tuong ung theo emu_index."""
    idx  = max(0, emu_index)
    port = LD_PORTS[idx] if idx < len(LD_PORTS) else 5554 + idx * 2
    return AdbController(adb_path=adb_path, serial=f"127.0.0.1:{port}")
