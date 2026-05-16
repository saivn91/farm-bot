"""
ADB Controller - xu ly moi tuong tac voi Android Debug Bridge.
"""
import subprocess
import os
import re
import time
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# LDPlayer ADB TCP ports (index 0-5)
LD_PORTS = [5554, 5556, 5558, 5560, 5562, 5564]


class AdbController:
    def __init__(self, adb_path: str = "adb", serial: str = ""):
        self.adb_path  = adb_path
        self.serial    = serial
        self._touch_dev: Optional[tuple[str, int, int]] = None  # (device, max_x, max_y)
        self._screen_wh: Optional[tuple[int, int]]      = None  # (width, height)

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

    def _screen_size(self) -> tuple[int, int]:
        """Lay kich thuoc man hinh (co cache)."""
        if self._screen_wh:
            return self._screen_wh
        _, out, _ = self.run(["shell", "wm size"])
        for line in out.splitlines():
            if "size:" in line.lower():
                try:
                    part = line.split(":")[-1].strip()
                    w, h = part.split("x")
                    self._screen_wh = (int(w), int(h))
                    return self._screen_wh
                except Exception:
                    pass
        self._screen_wh = (1280, 720)
        return self._screen_wh

    def _detect_touch_device(self) -> tuple[str, int, int]:
        """
        Tu dong tim thiet bi cam ung (co cache).
        Tra ve (device_path, max_touch_x, max_touch_y).
        Ho tro ca output co ten symbolic (-pl) va chi co hex code (-p).
        """
        if self._touch_dev:
            return self._touch_dev

        # Thu -pl truoc (co ten symbolic), fallback -p (chi hex)
        _, out, _ = self.run(["shell", "getevent -pl"], timeout=10)
        if not out or "add device" not in out:
            _, out, _ = self.run(["shell", "getevent -p"], timeout=10)

        logger.info(f"getevent output ({len(out)} chars):\n{out[:1500]}")

        # Regex khop ca "ABS_MT_POSITION_X" lan hex "0035"
        # 0035 = ABS_MT_POSITION_X, 0036 = ABS_MT_POSITION_Y
        re_mt_x = re.compile(r'(?:ABS_MT_POSITION_X|\b0035\b)')
        re_mt_y = re.compile(r'(?:ABS_MT_POSITION_Y|\b0036\b)')
        re_max  = re.compile(r'max\s+(\d+)')

        candidates: list[tuple[str, int, int]] = []
        cur_dev:   Optional[str] = None
        cur_name   = ""
        cur_has_x  = cur_has_y = False
        cur_max_x: Optional[int] = None
        cur_max_y: Optional[int] = None

        for raw in out.splitlines():
            line = raw.strip()

            if line.startswith("add device"):
                if cur_has_x and cur_has_y and cur_dev:
                    candidates.append(
                        (cur_dev, cur_max_x or 32767, cur_max_y or 32767)
                    )
                    logger.info(
                        f"  touch candidate: {cur_dev} ({cur_name}) "
                        f"max_x={cur_max_x} max_y={cur_max_y}"
                    )
                parts = line.split(": ", 1)
                cur_dev   = parts[1].strip() if len(parts) > 1 else None
                cur_name  = ""
                cur_has_x = cur_has_y = False
                cur_max_x = cur_max_y = None
                continue

            if line.startswith("name:"):
                cur_name = line.split(":", 1)[1].strip().strip('"')
                continue

            if re_mt_x.search(line):
                cur_has_x = True
                m = re_max.search(line)
                if m:
                    cur_max_x = int(m.group(1))

            if re_mt_y.search(line):
                cur_has_y = True
                m = re_max.search(line)
                if m:
                    cur_max_y = int(m.group(1))

        # device cuoi cung
        if cur_has_x and cur_has_y and cur_dev:
            candidates.append(
                (cur_dev, cur_max_x or 32767, cur_max_y or 32767)
            )
            logger.info(
                f"  touch candidate: {cur_dev} ({cur_name}) "
                f"max_x={cur_max_x} max_y={cur_max_y}"
            )

        if candidates:
            self._touch_dev = candidates[0]
        else:
            logger.warning("Khong tim thay touch device! Dung fallback /dev/input/event1")
            self._touch_dev = ("/dev/input/event1", 32767, 32767)

        logger.info(f"Selected touch device: {self._touch_dev}")
        return self._touch_dev

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

    def _sendevent_test(self, dev: str) -> bool:
        """Kiem tra nhanh xem sendevent co ghi duoc vao device hay khong."""
        code, out, err = self.run(
            ["shell", f"sendevent {dev} 0 0 0 && echo __OK__"],
            timeout=5,
        )
        ok = "__OK__" in out
        if not ok:
            logger.warning(
                f"sendevent test FAIL cho {dev}: "
                f"rc={code} out={out[:100]!r} err={err[:100]!r}"
            )
        return ok

    def _do_sendevent_gesture(
        self,
        hold_pt:  tuple[int, int],
        path_pts: list[tuple[int, int]],
        hold_ms:  int = 800,
        step_ms:  int = 80,
        delays:   Optional[list[float]] = None,
    ) -> bool:
        """
        Gesture nhan giu + keo 1 mach LIEN TUC bang sendevent.
        Tra ve True neu chay thanh cong, False neu loi.

        delays: danh sach delay (giay) cho tung diem trong path_pts.
                Neu None, dung step_ms cho tat ca.
        """
        try:
            dev, max_tx, max_ty = self._detect_touch_device()
            sw, sh = self._screen_size()

            if not self._sendevent_test(dev):
                return False

            sx = max_tx / max(sw - 1, 1)
            sy = max_ty / max(sh - 1, 1)

            def cvt_x(x: int) -> int:
                return max(0, min(max_tx, round(x * sx)))

            def cvt_y(y: int) -> int:
                return max(0, min(max_ty, round(y * sy)))

            hx, hy = hold_pt
            hold_s = f"{hold_ms / 1000:.3f}"
            default_s = step_ms / 1000.0

            se = f"sendevent {dev}"

            lines: list[str] = [
                "echo __GESTURE_START__",
                f"{se} 3 47 0",            # ABS_MT_SLOT = 0
                f"{se} 3 57 0",            # ABS_MT_TRACKING_ID = 0
                f"{se} 3 48 5",            # ABS_MT_TOUCH_MAJOR = 5
                f"{se} 3 58 50",           # ABS_MT_PRESSURE = 50
                f"{se} 3 53 {cvt_x(hx)}", # ABS_MT_POSITION_X
                f"{se} 3 54 {cvt_y(hy)}", # ABS_MT_POSITION_Y
                f"{se} 1 330 1",           # BTN_TOUCH = 1 (down)
                f"{se} 0 0 0",             # SYN_REPORT
                f"sleep {hold_s}",
            ]

            total_delay = hold_ms / 1000.0
            for i, (x, y) in enumerate(path_pts):
                d = delays[i] if delays else default_s
                lines += [
                    f"{se} 3 53 {cvt_x(x)}",
                    f"{se} 3 54 {cvt_y(y)}",
                    f"{se} 0 0 0",         # SYN_REPORT
                ]
                if d > 0:
                    lines.append(f"sleep {d:.3f}")
                    total_delay += d

            lines += [
                f"{se} 3 57 -1",           # ABS_MT_TRACKING_ID = -1 (finger up)
                f"{se} 1 330 0",           # BTN_TOUCH = 0 (up)
                f"{se} 0 0 0",             # SYN_REPORT
                "echo __GESTURE_DONE__",
            ]

            script      = "\n".join(lines) + "\n"
            est_timeout = round(total_delay) + 25

            logger.info(
                f"sendevent gesture: dev={dev} hold=({hx},{hy})->"
                f"({cvt_x(hx)},{cvt_y(hy)}) points={len(path_pts)} "
                f"hold_ms={hold_ms} total_delay={total_delay:.1f}s"
            )

            proc = subprocess.Popen(
                self._base() + ["shell", "sh"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=self._no_win(),
            )
            stdout, stderr = proc.communicate(
                input=script.encode(), timeout=est_timeout,
            )

            out_text = stdout.decode(errors="replace").strip()
            err_text = stderr.decode(errors="replace").strip()

            if err_text:
                logger.warning(f"sendevent stderr: {err_text[:500]}")
            if "__GESTURE_DONE__" not in out_text:
                logger.warning(
                    f"sendevent script khong hoan thanh! "
                    f"rc={proc.returncode} out={out_text[:300]!r}"
                )
                return False

            logger.info("sendevent gesture OK")
            return True

        except subprocess.TimeoutExpired:
            try:
                proc.kill()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            logger.warning("sendevent gesture timeout")
            return False
        except Exception as e:
            logger.error(f"sendevent gesture loi: {e}")
            return False

    def hold_and_drag_path(
        self,
        hold_pt:  tuple[int, int],
        path_pts: list[tuple[int, int]],
        hold_ms:  int = 900,
        step_ms:  int = 150,
        delays:   Optional[list[float]] = None,
        max_len:  int = 6000,
    ) -> None:
        """
        Nhan giu tai hold_pt roi keo lien tuc qua path_pts.
        delays: danh sach delay (giay) cho tung diem. Neu None, dung step_ms.
        Method 1: sendevent (gesture lien tuc)
        Method 2: input swipe chain (fallback)
        """
        if not path_pts:
            self.long_press(hold_pt[0], hold_pt[1], hold_ms)
            return

        if self._do_sendevent_gesture(
            hold_pt, path_pts, hold_ms, step_ms, delays=delays
        ):
            return

        logger.info("sendevent FAIL -> fallback input swipe chain")
        self._hold_and_drag_legacy(hold_pt, path_pts, hold_ms, step_ms, max_len)

    def _hold_and_drag_legacy(
        self,
        hold_pt:  tuple[int, int],
        path_pts: list[tuple[int, int]],
        hold_ms:  int = 900,
        step_ms:  int = 150,
        max_len:  int = 6000,
    ) -> None:
        """
        Fallback: gom cac lenh 'input swipe' bang &&.
        Moi 'input swipe' la 1 gesture doc lap (co nhac tay o cuoi).
        """
        if not path_pts:
            self.long_press(hold_pt[0], hold_pt[1], hold_ms)
            return

        hx, hy = hold_pt
        all_cmds: list[str] = [f"input swipe {hx} {hy} {hx} {hy} {hold_ms}"]
        px, py = hx, hy
        for x, y in path_pts:
            all_cmds.append(f"input swipe {px} {py} {x} {y} {step_ms}")
            px, py = x, y

        batches: list[list[str]] = []
        cur:     list[str] = []
        cur_len: int = 0
        for cmd in all_cmds:
            clen = len(cmd) + 4
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
