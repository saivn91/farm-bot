"""
ADB Controller - xử lý mọi tương tác với Android Debug Bridge.
"""
import subprocess
import os
import re
import time
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

class AdbController:
    def __init__(self, adb_path: str = "adb", serial: str = ""):
        self.adb_path  = adb_path
        self.serial    = serial
        self._touch_dev: Optional[tuple[str, int, int]] = None
        self._screen_wh: Optional[tuple[int, int]]      = None
        self._is_native_portrait: bool                  = False

    def _base(self) -> list:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        return cmd

    def _no_win(self) -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def _exec(self, cmd: list, timeout: int = 15) -> tuple[int, str, str]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=self._no_win())
            return r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except FileNotFoundError:
            return -1, "", "not_found"
        except Exception as e:
            return -1, "", str(e)

    def run(self, args: list, timeout: int = 15) -> tuple[int, str, str]:
        return self._exec(self._base() + args, timeout)

    def _run_bare(self, args: list, timeout: int = 15) -> tuple[int, str, str]:
        return self._exec([self.adb_path] + args, timeout)

    def start_server(self):
        self._run_bare(["start-server"], timeout=15)

    def connect(self) -> bool:
        if ":" not in self.serial:
            return True
        _, out, _ = self._run_bare(["connect", self.serial], timeout=10)
        return "connected" in out.lower()

    def devices(self) -> list[str]:
        _, out, _ = self._run_bare(["devices"])
        result = []
        for line in out.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                result.append(parts[0])
        return result

    def devices_raw(self) -> str:
        _, out, _ = self._run_bare(["devices", "-l"])
        return out.strip()

    def is_connected(self) -> bool:
        devs = self.devices()
        if not self.serial: return len(devs) > 0
        return self.serial in devs

    def full_connect(self) -> tuple[bool, str]:
        self.start_server()
        time.sleep(0.4)

        if self.serial and self.serial.isdigit():
            port_num = int(self.serial)
            if port_num >= 5554 and port_num % 2 == 0 and port_num <= 5584:
                self.serial = f"emulator-{self.serial}"
            else:
                self.serial = f"127.0.0.1:{self.serial}"

        if self.serial and ":" in self.serial:
            self.connect()
            time.sleep(0.8)

        devs = self.devices()

        if self.serial in devs:
            return True, f"Đã kết nối thành công: {self.serial}"

        if self.serial and self.serial.startswith("127.0.0.1:"):
            port = self.serial.split(":")[1]
            if f"emulator-{port}" in devs:
                self.serial = f"emulator-{port}"
                return True, f"Đã kết nối thành công: {self.serial}"

        if self.serial and self.serial.startswith("emulator-"):
            port = self.serial.split("-")[1]
            if f"127.0.0.1:{port}" in devs:
                self.serial = f"127.0.0.1:{port}"
                return True, f"Đã kết nối thành công: {self.serial}"

        if self.serial:
            return False, (
                f"LỖI: Không tìm thấy giả lập nào tại cổng '{self.serial}'.\n\n"
                f"Danh sách hiện có: {devs}\n\n"
                f"Hãy kiểm tra lại số cổng và đảm bảo giả lập đã được bật lên nhé!"
            )

        if not self.serial:
            if devs:
                self.serial = devs[0]
                return True, f"Tự động nhận diện thiết bị đang mở: {self.serial}"
            else:
                return False, "Lỗi: Không tìm thấy bất kỳ giả lập nào đang chạy!"

        return False, "Lỗi không xác định."

    def screenshot(self) -> Optional[np.ndarray]:
        import cv2
        try:
            proc = subprocess.run(
                self._base() + ["exec-out", "screencap", "-p"],
                capture_output=True, timeout=20, creationflags=self._no_win(),
            )
            if proc.returncode == 0 and proc.stdout:
                data = np.frombuffer(proc.stdout, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if img is not None: return img
        except Exception:
            pass
        return None

    def _screen_size(self) -> tuple[int, int]:
        if self._screen_wh: return self._screen_wh
        _, out, _ = self.run(["shell", "wm size"])
        for line in out.splitlines():
            if "size:" in line.lower():
                try:
                    part = line.split(":")[-1].strip()
                    w, h = part.split("x")
                    side1, side2 = int(w), int(h)
                    
                    # [TỐI ƯU CỐT LÕI]: Phát hiện lõi phần cứng là dọc (Portrait)
                    self._is_native_portrait = (side1 < side2)
                    
                    self._screen_wh = (max(side1, side2), min(side1, side2))
                    return self._screen_wh
                except Exception: pass
        self._is_native_portrait = False
        self._screen_wh = (1280, 720)
        return self._screen_wh

    def _detect_touch_device(self) -> tuple[str, int, int]:
        if self._touch_dev: return self._touch_dev
        _, out, _ = self.run(["shell", "getevent -pl"], timeout=10)
        if not out or "add device" not in out:
            _, out, _ = self.run(["shell", "getevent -p"], timeout=10)

        re_mt_x = re.compile(r'(?:ABS_MT_POSITION_X|\b0035\b)')
        re_mt_y = re.compile(r'(?:ABS_MT_POSITION_Y|\b0036\b)')
        re_max  = re.compile(r'max\s+(\d+)')

        candidates, cur_dev, cur_has_x, cur_has_y, cur_max_x, cur_max_y = [], None, False, False, None, None

        for raw in out.splitlines():
            line = raw.strip()
            if line.startswith("add device"):
                if cur_has_x and cur_has_y and cur_dev:
                    candidates.append((cur_dev, cur_max_x or 32767, cur_max_y or 32767))
                parts = line.split(": ", 1)
                cur_dev = parts[1].strip() if len(parts) > 1 else None
                cur_has_x = cur_has_y = False
                cur_max_x = cur_max_y = None
                continue

            if re_mt_x.search(line):
                cur_has_x = True
                m = re_max.search(line)
                if m: cur_max_x = int(m.group(1))

            if re_mt_y.search(line):
                cur_has_y = True
                m = re_max.search(line)
                if m: cur_max_y = int(m.group(1))

        if cur_has_x and cur_has_y and cur_dev:
            candidates.append((cur_dev, cur_max_x or 32767, cur_max_y or 32767))

        if candidates: self._touch_dev = candidates[0]
        else: self._touch_dev = ("/dev/input/event1", 32767, 32767)
        return self._touch_dev

    def tap(self, x: int, y: int, delay_ms: int = 150):
        self.run(["shell", "input", "tap", str(x), str(y)])
        time.sleep(delay_ms / 1000.0)

    def long_press(self, x: int, y: int, ms: int = 900):
        self.run(["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(ms)])

    def _sendevent_test(self, dev: str) -> bool:
        code, out, err = self.run(["shell", f"sendevent {dev} 0 0 0 && echo __OK__"], timeout=5)
        return "__OK__" in out

    def _do_sendevent_gesture(self, hold_pt: tuple[int, int], path_pts: list[tuple[int, int]], hold_ms: int = 800, step_ms: int = 80, delays: Optional[list[float]] = None) -> bool:
        try:
            dev, max_tx, max_ty = self._detect_touch_device()
            sw, sh = self._screen_size()
            if not self._sendevent_test(dev): return False

            # [SỬA LỖI MUMU/NOX]: Đã loại bỏ lệnh chặn sendevent.
            # Thay vào đó, áp dụng thuật toán xoay trục tọa độ 90 độ ngược chiều kim đồng hồ
            # cho các giả lập lõi dọc (Native Portrait) nhưng hiển thị ngang (Landscape).
            if self._is_native_portrait:
                def cvt_x(x: int, y: int) -> int: 
                    return max(0, min(max_tx, round((1.0 - y / sh) * max_tx)))
                def cvt_y(x: int, y: int) -> int: 
                    return max(0, min(max_ty, round((x / sw) * max_ty)))
            else:
                sx = max_tx / max(sw - 1, 1)
                sy = max_ty / max(sh - 1, 1)
                def cvt_x(x: int, y: int) -> int: return max(0, min(max_tx, round(x * sx)))
                def cvt_y(x: int, y: int) -> int: return max(0, min(max_ty, round(y * sy)))

            hx, hy = hold_pt
            hold_s = f"{hold_ms / 1000:.3f}"
            default_s = step_ms / 1000.0
            se = f"sendevent {dev}"

            # [SỬA LỖI MUMU 12 - ANDROID 11+]: 
            # Sửa mã ABS_MT_TRACKING_ID (57) từ 0 thành 123 để Android ghi nhận Touch Down hợp lệ.
            lines = [
                "echo __GESTURE_START__",
                f"{se} 3 47 0", f"{se} 3 57 123", f"{se} 3 48 5", f"{se} 3 58 50",
                f"{se} 3 53 {cvt_x(hx, hy)}", f"{se} 3 54 {cvt_y(hx, hy)}",
                f"{se} 1 330 1", f"{se} 0 0 0", f"sleep {hold_s}",
            ]

            total_delay = hold_ms / 1000.0
            for i, (x, y) in enumerate(path_pts):
                d = delays[i] if delays else default_s
                lines += [f"{se} 3 53 {cvt_x(x, y)}", f"{se} 3 54 {cvt_y(x, y)}", f"{se} 0 0 0"]
                if d > 0: lines.append(f"sleep {d:.3f}"); total_delay += d

            lines += [f"{se} 3 57 -1", f"{se} 1 330 0", f"{se} 0 0 0", "echo __GESTURE_DONE__"]
            script = "\n".join(lines) + "\n"
            est_timeout = round(total_delay) + 25

            proc = subprocess.Popen(self._base() + ["shell", "sh"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=self._no_win())
            stdout, stderr = proc.communicate(input=script.encode(), timeout=est_timeout)
            
            return "__GESTURE_DONE__" in stdout.decode(errors="replace").strip()
        except Exception:
            return False

    # [TỐI ƯU TỐC ĐỘ FALLBACK]: Ép step_ms = 50 để input swipe quẹt siêu nhanh trên MuMu
    def hold_and_drag_path(self, hold_pt: tuple[int, int], path_pts: list[tuple[int, int]], hold_ms: int = 900, step_ms: int = 50, delays: Optional[list[float]] = None, max_len: int = 6000) -> None:
        if not path_pts: 
            return self.long_press(hold_pt[0], hold_pt[1], hold_ms)
            
        if self._do_sendevent_gesture(hold_pt, path_pts, hold_ms, step_ms, delays=delays): 
            return
        
        hx, hy = hold_pt
        all_cmds = [f"input swipe {hx} {hy} {hx} {hy} {hold_ms}"]
        px, py = hx, hy
        for x, y in path_pts:
            all_cmds.append(f"input swipe {px} {py} {x} {y} {step_ms}")
            px, py = x, y

        batches, cur, cur_len = [], [], 0
        for cmd in all_cmds:
            clen = len(cmd) + 4
            if cur_len + clen > max_len and cur:
                batches.append(cur)
                cur, cur_len = [], 0
            cur.append(cmd)
            cur_len += clen
        if cur: batches.append(cur)

        for b in batches:
            est_timeout = int((hold_ms + len(b) * step_ms) / 1000) + 15
            self.run(["shell", " && ".join(b)], timeout=est_timeout)