"""
Farm Engine - Vòng lặp chính của bot.
Chu trình: Bắt buộc quét đất trống lần đầu (Lưu Offset) -> Quét theo Dynamic Path Mask -> Bù trừ Pan Camera -> Thu hoạch / Gieo hạt.
"""
import threading
import time
import random
import logging
from typing import Optional, Callable
import cv2
import numpy as np

from core.models import BotInstance, BotStatus, FarmRegion
from core.adb import AdbController
from core.vision import (
    find_one,
    find_all,
    find_soil_cells,
    build_farm_sweep,
    compute_polygon,
    compute_bbox,
    draw_debug,
    save_debug,
)

logger = logging.getLogger(__name__)

class StopException(Exception):
    """Ngoại lệ dùng để ép luồng bot dừng ngay lập tức."""
    pass

class FarmEngine:
    def __init__(
        self,
        inst:   BotInstance,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        self.inst   = inst
        self.on_log = on_log
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.adb:     Optional[AdbController]    = None
        self.debug_counter = 0
        
        self.can_sell_crops = True 
        self.cached_mui_ten = None
        self.cached_tao_ban = None
        self.shop_offset = None 

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
            
        self.inst.last_plant_time = 0
        self.inst.farm_region = None
        self.inst.pct_grown = 0.0
        self.inst.pct_empty = 0.0
        self.shop_offset = None
        
        self._stop.clear()
        self.inst.is_running = True
        self.inst.status     = BotStatus.RUNNING
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"Bot-{self.inst.id}",
        )
        self._thread.start()
        self._log(f"Khởi động | Cây: {self.inst.crop_mode.label()}")

    def stop(self):
        self._stop.set()
        self.inst.is_running = False
        self.inst.status     = BotStatus.STOPPED
        self.inst.farm_region = None
        self.inst.max_cells = 0 
        self.inst.last_plant_time = 0
        self.inst.pct_grown = 0.0
        self.inst.pct_empty = 0.0
        self.cached_mui_ten = None
        self.cached_tao_ban = None
        self.shop_offset = None
        self._log("Hệ thống đã phát lệnh dừng khẩn cấp.")

    def force_scan(self):
        self.inst.farm_region = None
        self.inst.max_cells = 0 
        self.shop_offset = None
        self._log("Yêu cầu quét lại vùng farm...")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_stop(self):
        if self._stop.is_set():
            raise StopException()

    def _log(self, msg: str):
        logger.info(f"[Bot-{self.inst.id}] {msg}")
        self.inst.add_log(msg)
        if self.on_log:
            self.on_log(msg)

    def _sleep(self, ms: int):
        end = time.time() + ms / 1000.0
        while time.time() < end:
            self._check_stop()
            time.sleep(0.05)

    def _shot(self) -> Optional[np.ndarray]:
        self._check_stop()
        return self.adb.screenshot()

    def _tap(self, x: int, y: int, delay_ms: int = 100):
        self._check_stop()
        self.adb.tap(x, y, delay_ms)

    def _debug_save(self, screen: np.ndarray, step: str, text: str = "", **kw) -> None:
        if not self.inst.debug_mode or screen is None:
            return
        self.debug_counter += 1
        step_with_counter = f"{self.debug_counter}_{step}"
        annotated = draw_debug(screen, label=text if text else step_with_counter, **kw)
        path = save_debug(annotated, step_with_counter, inst_id=self.inst.id)
        self._log(f"[DEBUG] Lưu ảnh chi tiết: {path}")

    def _interp(self, p1: tuple[int, int], p2: tuple[int, int], steps: int = 8) -> list[tuple[int, int]]:
        return [
            (
                int(p1[0] + (p2[0] - p1[0]) * i / steps),
                int(p1[1] + (p2[1] - p1[1]) * i / steps),
            )
            for i in range(1, steps + 1)
        ]

    def _close_x(self, screen: Optional[np.ndarray] = None) -> bool:
        if screen is None:
            screen = self._shot()
        if screen is None:
            return False

        x_btn = find_one(screen, "dong_x.png", th=self.inst.thresholds)
        if not x_btn.found:
            x_btn = find_one(screen, "dong_x_2.png", th=self.inst.thresholds)
            if not x_btn.found:
                x_btn = find_one(screen, "dong_x_3.png", th=self.inst.thresholds)

        if x_btn.found:
            self._debug_save(screen, "phat_hien_nut_x_de_dong", tool_pt=(x_btn.x, x_btn.y))
            self._tap(x_btn.x, x_btn.y)
            return True
        return False
        
    # ── Init & Reset Cam ──────────────────────────────────────────────

    def _close_all_popups(self):
        closed_any = True
        close_count = 0
        while closed_any and close_count < 5:
            self._check_stop()
            closed_any = self._close_x()
            if closed_any:
                close_count += 1
                self._sleep(200)

    def _zoom_out(self):
        self._log("Thực hiện thu nhỏ màn hình (Zoom Out)")
        try:
            import ctypes
            import time
            
            user32 = ctypes.windll.user32
            emu_index = self.inst.emu_index 
            display_name = self.inst.get_display_name() 
            
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            
            titles = [display_name]
            if self.inst.name.strip():
                titles.append(self.inst.name.strip())
                
            if emu_index == 0:
                titles += ["LDPlayer", "LDPlayer(64)", "LDPlayer-0", "MuMu Player", "MuMuPlayer", "MuMu Player 12"]
            else:
                titles += [f"LDPlayer-{emu_index}", f"LDPlayer({emu_index})", f"LDPlayer-{emu_index}(64)"]
                titles += [f"MuMu Player-{emu_index}", f"MuMuPlayer-{emu_index}", f"MuMu Player 12-{emu_index}"]
            
            titles = list(set([t for t in titles if t]))
            
            hwnd = 0
            for title in titles:
                hwnd = user32.FindWindowW(None, title)
                if hwnd: break
                
            if not hwnd:
                inner_hwnd = [0]
                def enum_windows_proc(h, lParam):
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(h, buf, 256)
                    text = buf.value
                    
                    custom_name = self.inst.name.strip()
                    
                    # 1. Nhận diện tuyệt đối theo tên người dùng tự đặt
                    if custom_name and custom_name in text:
                        inner_hwnd[0] = h
                        return False
                        
                    # 2. Tự động tìm kiếm nếu người dùng không đặt tên
                    if "MuMu" in text or "LDPlayer" in text:
                        if emu_index == 0 and ("-" not in text and "(" not in text or "(64)" in text):
                            inner_hwnd[0] = h
                            return False
                        elif f"-{emu_index}" in text or f"({emu_index})" in text:
                            inner_hwnd[0] = h
                            return False
                    return True
                
                user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
                hwnd = inner_hwnd[0]
                
            if hwnd:
                WM_KEYDOWN = 0x0100
                WM_KEYUP = 0x0101
                VK_F5 = 0x74  
                
                # --- NÂNG CẤP THUẬT TOÁN NHẬN DIỆN GIẢ LẬP ĐA LỚP ---
                title_buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title_buf, 256)
                
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buf, 256)
                
                title_str = title_buf.value.lower()
                class_str = class_buf.value.lower()
                custom_str = self.inst.name.strip().lower()
                serial_str = self.inst.adb_serial.lower()
                
                is_mumu = (
                    "mumu" in title_str or 
                    "mumu" in custom_str or 
                    "nemu" in class_str or 
                    "qt5" in class_str or 
                    "7555" in serial_str or 
                    "1638" in serial_str
                )
                # ---------------------------------------------------
                
                if is_mumu:
                    self._log("Phát hiện giả lập MuMu, thực hiện Zoom Out 1 lần bằng phím cơ học.")
                    try:
                        user32.ShowWindow(hwnd, 9) # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(0.3)
                    except Exception:
                        pass
                    
                    # Bắn phím F5 phần cứng 1 lần duy nhất cho MuMu
                    user32.keybd_event(VK_F5, 0x3F, 0, 0)
                    time.sleep(0.05)
                    user32.keybd_event(VK_F5, 0x3F, 2, 0)
                    time.sleep(0.15)
                    
                else:
                    self._log("Phát hiện giả lập LDPlayer, thực hiện Zoom Out nhồi lệnh nhiều lần.")
                    def send_f5_to_target(target_hwnd):
                        for _ in range(6):
                            self._check_stop()
                            user32.PostMessageW(target_hwnd, WM_KEYDOWN, VK_F5, 0)
                            time.sleep(0.03)
                            user32.PostMessageW(target_hwnd, WM_KEYUP, VK_F5, 0)
                            time.sleep(0.03)
                    
                    for _ in range(5):
                        send_f5_to_target(hwnd)
                        self._sleep(100)
                    
                    def enum_child_proc(h, lParam):
                        for _ in range(5):
                            send_f5_to_target(h)
                            self._check_stop()
                            time.sleep(0.1)
                        return True
                    user32.EnumChildWindows(hwnd, WNDENUMPROC(enum_child_proc), 0)
                
                self._sleep(500)
            else:
                self._log(f"[CẢNH BÁO] Không tìm thấy cửa sổ giả lập ứng với tên '{display_name}'.")
        except StopException:
            raise
        except Exception as e:
            self._log(f"Lỗi khi gửi lệnh thu nhỏ màn hình: {e}")
            
        self._close_all_popups()

    def _reset_camera_and_find_shop(self, allow_restart: bool = True) -> bool:
        self._log("Gọi hàm Khôi phục vị trí Camera...")
        self._close_all_popups()
        self._zoom_out()
        
        screen = self._shot()
        if screen is None: return False
        cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
        if cua_hang.found:
            self._log("Đã tìm thấy Cửa hàng sau khi reset vị trí Camera.")
            return True
        
        sw, sh = self.adb._screen_size()
        self._log("Đang đẩy camera kịch góc Trên-Trái...")
        for _ in range(10):
            self.adb.run(["shell", "input", "swipe", str(int(sw*0.2)), str(int(sh*0.2)), str(int(sw*0.8)), str(int(sh*0.8)), "300"])
            self._sleep(100)
            
        self._log("Đang dịch camera xuống giữa để định vị Cửa hàng...")
        self.adb.run(["shell", "input", "swipe", str(sw//2), str(int(sh*0.8)), str(sw//2), str(int(sh*0.3)), "600"])
        self._sleep(1000)
        
        screen = self._shot()
        if screen is None: return False
        cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
        
        if cua_hang.found:
            self._log("Đã tìm thấy Cửa hàng sau khi reset vị trí Camera.")
            return True
        
        # Nếu không thấy cửa hàng và được phép restart thì gọi _check_and_restart_game
        if allow_restart:
            self._log("Reset Camera thất bại: Không thấy Cửa hàng (Có thể do dis game). Đang tiến hành khôi phục lại ứng dụng...")
            return self._check_and_restart_game()
        
        return False

    def _align_shop_to_bottom_left(self):
        for attempt in range(4):
            screen = self._shot()
            if screen is None: continue
            
            cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
            
            if cua_hang.found:
                sw, sh = self.adb._screen_size()
                target_x = int(sw * 0.3) 
                target_y = int(sh * 0.7) 
                
                dx = cua_hang.x - target_x
                dy = cua_hang.y - target_y
                
                if abs(dx) < 20 and abs(dy) < 20:
                    return
                
                cx, cy = sw // 2, sh // 2
                self.adb.run(["shell", "input", "swipe", str(cx), str(cy), str(cx - dx), str(cy - dy), "600"])
                self._sleep(1000)
                self._log(f"Đã kéo Cửa hàng về góc trái dưới (X: {target_x}, Y: {target_y}).")
                self._debug_save(self._shot(), "shop_sau_khi_keo_goc_trai_duoi")
                return
            else:
                self._log(f"Đang tìm Cửa hàng để neo Camera (lần {attempt+1})...")
                found = self._reset_camera_and_find_shop()
                if not found:
                    self._sleep(1000)

    def _init_shop_and_cache(self) -> bool:
        if not self.inst.enable_shop:
            return True
            
        # Bỏ qua lấy mẫu UI nếu đã có sẵn trong bộ nhớ ---
        if self.cached_mui_ten and self.cached_tao_ban:
            self._log("Đã có tọa độ UI shop trong bộ nhớ. Tiến hành neo lại Camera...")
            # Chỉ cần đẩy góc nhìn về chuẩn và kéo Cửa hàng về góc trái dưới
            found = self._reset_camera_and_find_shop(allow_restart=False)
            if found:
                self._align_shop_to_bottom_left()
                return True
            return False
        
        self._log("Bắt đầu quy trình khởi tạo Cửa hàng và lấy tọa độ UI...")
        
        for attempt in range(3):
            screen = self._shot()
            if screen is None: continue
            
            cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
            if not cua_hang.found:
                self._log(f"Lần {attempt+1}/3: Không tìm thấy Cửa hàng. Gọi hàm Reset Camera...")
                found = self._reset_camera_and_find_shop(allow_restart=False)
                if not found:
                    continue
                screen = self._shot()
                cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
                
            if not cua_hang.found: continue

            self._log("Đã thấy Cửa hàng, tiến hành mở để lấy mẫu UI...")
            self._tap(cua_hang.x, cua_hang.y)
            self._sleep(1000)
            
            sc2 = self._shot()
            
            thung_trong = find_one(sc2, "thung_trong.png", th=self.inst.thresholds)
            if not thung_trong.found:
                thung_da_ban = find_one(sc2, "thung_da_ban.png", th=self.inst.thresholds)
                if thung_da_ban.found:
                    self._log("Không có thùng trống. Tap thu tiền thùng đã bán để lấy không gian...")
                    self._tap(thung_da_ban.x, thung_da_ban.y)
                    self._sleep(500)
                    sc2 = self._shot() 
                    thung_trong = find_one(sc2, "thung_trong.png", th=self.inst.thresholds)
            
            if not thung_trong.found:
                self._close_x(sc2)
                self._log(f"Lần {attempt+1}/3: Vẫn không có thùng trống để lấy mẫu UI.")
                self._sleep(1000)
                continue
                
            self._tap(thung_trong.x, thung_trong.y)
            self._sleep(500)
                
            sc_menu = self._shot()
            self._debug_save(sc_menu, "quet_mau_ui_shop")
            mui_ten = find_one(sc_menu, "mui_ten_phai.png", th=self.inst.thresholds)
            tao_ban = find_one(sc_menu, "tao_rao_ban.png", th=self.inst.thresholds)
            
            if mui_ten.found and tao_ban.found:
                self.cached_mui_ten = (mui_ten.x, mui_ten.y)
                self.cached_tao_ban = (tao_ban.x, tao_ban.y)
                self._log(f"THÀNH CÔNG: Đã lưu tọa độ Mũi Tên ({mui_ten.x}, {mui_ten.y}) và Tạo Bán ({tao_ban.x}, {tao_ban.y})")
                
                self._close_x(sc_menu)
                self._sleep(500)
                self._close_x()
                self._sleep(500)
                
                self._align_shop_to_bottom_left()
                return True
            else:
                self._close_x(sc_menu)
                self._close_x()
                self._log(f"Lần {attempt+1}/3: Không tìm thấy đủ 2 nút Mũi tên và Tạo bán.")
                self._sleep(1000)
                
        self._log("CẢNH BÁO: Thất bại sau 3 lần khởi tạo Cửa hàng! Yêu cầu dừng hệ thống.")
        return False

    def _check_and_restart_game(self) -> bool:
        self._log("Kiểm tra thông báo mất kết nối / đăng nhập nơi khác...")
        
        # 1. Chụp màn hình hiện tại trước khi thoát ra Home
        screen = self._shot()
        reloaded = False
        
        if screen is not None:
            # Tìm nút Tải lại trò chơi
            tai_lai = find_one(screen, "tai_lai_tro_choi.png", th=self.inst.thresholds)
            
            if tai_lai.found:
                self._log("Phát hiện nút 'Tải lại trò chơi'. Đang tiến hành kết nối lại...")
                self.inst.status = "KHỞI ĐỘNG LẠI GAME"
                self._tap(tai_lai.x, tai_lai.y)
                reloaded = True
        
        # 2. Nếu không có nút tải lại, mới tiến hành thoát ra màn hình chính tìm icon game
        if not reloaded:
            self._log("Không thấy nút Tải lại, thử tìm biểu tượng game ngoài màn hình chính...")
            self.adb.run(["shell", "input", "keyevent", "3"])
            self._sleep(800)
            self.adb.run(["shell", "input", "keyevent", "3"])
            self._sleep(1000)
            
            screen = self._shot()
            if screen is None: return False

            self._debug_save(screen, "man_hinh_chinh")    
            icon = find_one(screen, "icon_game.png", th=self.inst.thresholds)
            if not icon.found:
                icon = find_one(screen, "icon_game_1.png", th=self.inst.thresholds)
                if not icon.found:
                    icon = find_one(screen, "icon_game_2.png", th=self.inst.thresholds)

            if not icon.found:
                self._log("LỖI HỆ THỐNG: Không tìm thấy biểu tượng game. Vui lòng kiểm tra lại cấu hình!")
                self.inst.status = BotStatus.ERROR
                self._stop.set()
                raise StopException()
                
            self._log("Phát hiện biểu tượng, tiến hành khôi phục ứng dụng...")
            self.inst.status = "KHỞI ĐỘNG LẠI GAME"
            self._tap(icon.x, icon.y)
            
        # 3. Chờ 30 giây để game nạp dữ liệu (Dùng chung cho cả 2 trường hợp)
        self._log("Chờ 30 giây để nạp dữ liệu...")
        for _ in range(30):
            self._sleep(1000)
            
        self._log("Ứng dụng đã khôi phục. Thực hiện thiết lập lại...")
        self._close_all_popups()
        self._zoom_out()
        
        if self._init_shop_and_cache():
            self._log("Khôi phục thành công! Camera đã neo về góc cũ, tái sử dụng tọa độ nông trại.")
            return True
            
        self.inst.status = BotStatus.ERROR
        self._stop.set()
        raise StopException()

    # ── Đọc số lượng Pytesseract ──────────────────────────────────────────────

    def _read_quantity(self, screen: np.ndarray, match_res) -> int:
        try:
            import pytesseract
            
            pytesseract.pytesseract.tesseract_cmd = self.inst.tesseract_path
            x, y = match_res.x, match_res.y
            
            x_start = max(0, x - 60)
            x_end = min(x + 85, screen.shape[1])
            y_start = max(0, y - 10)
            y_end = min(screen.shape[0], y + 75)
            
            roi = screen[y_start:y_end, x_start:x_end]
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            
            lower_white = np.array([0, 0, 180])
            upper_white = np.array([180, 30, 255])
            mask = cv2.inRange(hsv, lower_white, upper_white)
            
            kernel = np.ones((2, 2), np.uint8)
            eroded = cv2.erode(mask, kernel, iterations=1)
            
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(eroded, connectivity=8)
            clean_mask = np.zeros_like(eroded)
            
            for i in range(1, num_labels): 
                h = stats[i, cv2.CC_STAT_HEIGHT]
                area = stats[i, cv2.CC_STAT_AREA]
                if h > 8 and area > 10:
                    clean_mask[labels == i] = 255
                    
            clean_mask = cv2.dilate(clean_mask, kernel, iterations=2)
            thresh = cv2.bitwise_not(clean_mask)
            
            self._debug_save(thresh, "ocr_roi_kiem_tra", text="Vung_kiem_tra_so_luong")
            
            config = '--psm 7 -c tessedit_char_whitelist=0123456789'
            text = pytesseract.image_to_string(thresh, config=config)
            
            num_str = text.strip()
            if not num_str:
                return 0
                
            return int(num_str)
        except StopException:
            raise
        except Exception as e:
            self._log(f"Lỗi khi đọc OCR: {e}")
            return 0

    # ── Farm region ───────────────────────────────────────────────────────────

    def _update_region(self, cells: list, screen: Optional[np.ndarray] = None) -> None:
        if not cells: return

        if self.inst.farm_region is None or len(cells) >= self.inst.max_cells:
            if len(cells) > self.inst.max_cells:
                self.inst.max_cells = len(cells)
                self._log(f"Cập nhật giới hạn đất tối đa: {self.inst.max_cells} ô")

            sweep = build_farm_sweep(cells)
            poly  = compute_polygon(cells)
            bbox  = compute_bbox(cells)

            # Tính tọa độ trọng tâm nguyên bản
            cx = sum(c.x for c in cells) / len(cells)
            cy = sum(c.y for c in cells) / len(cells)
            
            # Giữ nguyên logic lấy ô đất gần tâm nhất làm mốc chuẩn
            anchor_cell = min(cells, key=lambda c: (c.x - cx) ** 2 + (c.y - cy) ** 2)

            # --- SỬA LỖI: Dịch điểm Tap xuống 5px để luôn ấn vào nửa dưới của ô đất ---
            safe_anchor_x = anchor_cell.x + 5
            safe_anchor_y = anchor_cell.y + 5

            self.inst.farm_region = FarmRegion(
                polygon    = poly,
                sweep_path = sweep,
                anchor     = (safe_anchor_x, safe_anchor_y),
                cell_count = len(cells),
                bbox       = bbox,
                last_scan  = time.time(),
            )
            
            if screen is not None:
                cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
                if cua_hang.found:
                    sx, sy = cua_hang.x, cua_hang.y
                    self.shop_offset = {
                        'bbox': (bbox[0] - sx, bbox[1] - sy, bbox[2] - sx, bbox[3] - sy),
                        'anchor': (safe_anchor_x - sx, safe_anchor_y - sy),
                        'sweep': [(p[0] - sx, p[1] - sy) for p in sweep],
                        'poly': [(p[0] - sx, p[1] - sy) for p in poly]
                    }
                    self._log("Đã neo tọa độ Khu vực Nông trại an toàn với Cửa hàng.")
                else:
                    self.shop_offset = None

                self._debug_save(
                    screen, "scan_vung_dat",
                    text=f"Tong so dat: {len(cells)}",
                    polygon=poly,
                    cells=cells,
                    anchor=(safe_anchor_x, safe_anchor_y),
                    path=sweep if sweep else None,
                )

    def _build_tool_path(
        self,
        tool_pt: tuple[int, int],
        anchor:  tuple[int, int],
        sweep:   list[tuple[int, int]],
    ) -> tuple[list[tuple[int, int]], list[float]]:
        seg_fast = self._interp(tool_pt, anchor, steps=3)
        path: list[tuple[int, int]] = []
        delays: list[float] = []

        for pt in seg_fast:
            path.append(pt)
            delays.append(0.010)

        path.append(anchor)
        delays.append(0.300)

        for pt in sweep:
            path.append(pt)
            delays.append(0.001)

        return path, delays

    def _align_camera(self) -> bool:
        r = self.inst.farm_region
        if not r:
            return False

        self._log("Thực hiện định tâm camera...")
        self._tap(r.anchor[0], r.anchor[1])
        self._sleep(500)

        self._tap(10, 10)
        self._sleep(100)

        screen_check = self._shot()
        if screen_check is not None:
            self._close_x(screen_check)

        screen = self._shot()
        if screen is None: return False

        cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
        if cua_hang.found and self.shop_offset:
            sx, sy = cua_hang.x, cua_hang.y
            off = self.shop_offset
            r.bbox = (sx + off['bbox'][0], sy + off['bbox'][1], sx + off['bbox'][2], sy + off['bbox'][3])
            r.anchor = (sx + off['anchor'][0], sy + off['anchor'][1])
            r.sweep_path = [(sx + p[0], sy + p[1]) for p in off['sweep']]
            r.polygon = [(sx + p[0], sy + p[1]) for p in off['poly']]
            
            self._log("Đã cập nhật Lưới và Mask chuẩn theo Cửa hàng sau khi định tâm.")
            return True

        cells = find_soil_cells(screen, th=self.inst.thresholds)
        if cells:
            self._update_region(cells, screen)
            return True

        self._log("Lỗi: Không tìm thấy Cửa hàng hoặc Đất trống để neo camera!")
        return False

    # ── Harvest cycle ─────────────────────────────────────────────────────────

    def _harvest_cycle(self) -> None:
        self.inst.status = BotStatus.HARVESTING
        self._log("Kích hoạt quy trình Thu Hoạch...")

        if not self._align_camera(): 
            self._log("Lỗi định vị khu vực canh tác. Hủy thu hoạch.")
            return
            
        r = self.inst.farm_region
        if not r: return

        harvest_anchor = None
        harvest_sweep = None
        valid_area_found = False
        
        expected_area = (self.inst.max_cells if self.inst.max_cells > 0 else r.cell_count) * 800
        min_required_area = expected_area * 0.4 

        for attempt in range(5):
            screen = self._shot()
            if screen is None:
                self._sleep(1000)
                continue

            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            lower_yellow = np.array([18, 120, 150])
            upper_yellow = np.array([33, 255, 255])
            mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
            
            # --- MẶT NẠ ĐỘNG BẰNG LỘ TRÌNH SWEEP PATH ---
            # Thay vì dùng r.polygon dễ bị văng khuyết góc, ta vẽ mặt nạ xung quanh các điểm quét (sweep_path)
            farm_mask = np.zeros(screen.shape[:2], dtype=np.uint8)
            for p in r.sweep_path:
                cv2.circle(farm_mask, (int(p[0]), int(p[1])), 75, 255, -1)
            
            # Áp mặt nạ ôm khít này vào ảnh HSV
            mask = cv2.bitwise_and(mask, farm_mask)
            
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.dilate(mask, kernel, iterations=9)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                valid_contours = [cnt for cnt in contours if cv2.contourArea(cnt) > 200]
                
                if valid_contours:
                    total_area = sum(cv2.contourArea(cnt) for cnt in valid_contours)
                    
                    if total_area >= min_required_area:
                        valid_area_found = True
                        
                        all_pts = np.vstack(valid_contours)
                        x, y, w, h = cv2.boundingRect(all_pts)
                        
                        cx, cy = x + w//2, y + h//2
                        harvest_anchor = (cx, cy)
                        
                        mock_cells = []
                        class MockCell:
                            def __init__(self, px, py): self.x, self.y = px, py
                        
                        for py in range(y + 15, y + h, 35):
                            for px in range(x + 15, x + w, 35):
                                if any(cv2.pointPolygonTest(cnt, (px, py), False) >= 0 for cnt in valid_contours):
                                    mock_cells.append(MockCell(px, py))
                                    
                        if not mock_cells:
                            mock_cells.append(MockCell(cx, cy))
                            
                        harvest_sweep = build_farm_sweep(mock_cells)
                        
                        self._log(f"Phân tích HSV (Mask Động): Đã gộp {len(valid_contours)} vùng lúa chín, tổng {total_area:.0f}px (Kỳ vọng ~{expected_area}px).")
                        
                        if self.inst.debug_mode:
                            out_img = screen.copy()
                            cv2.drawContours(out_img, valid_contours, -1, (0, 255, 0), 2)
                            cv2.circle(out_img, harvest_anchor, 8, (0, 140, 255), -1)
                            for c in mock_cells: 
                                cv2.circle(out_img, (c.x, c.y), 4, (0, 255, 255), -1)
                            self._debug_save(out_img, "harvest_hsv_vung_lua", text="Phat_hien_lua_chin_MASK_DONG")
                            
                        break
                    else:
                        self._log(f"Lần {attempt+1}/5: Diện tích lúa ({total_area:.0f}px) chưa đạt tối thiểu ({min_required_area:.0f}px).")
                else:
                    self._log(f"Lần {attempt+1}/5: Các khối lượng lúa quá nhỏ (nhiễu).")
            self._sleep(1000)

        if not valid_area_found:
            self._log("Không thể thực hiện thu hoạch tại thời điểm này.")
            return

        self._tap(harvest_anchor[0], harvest_anchor[1])
        self._sleep(500)

        sc_menu = self._shot()
        if sc_menu is None: return

        cua_hang = find_one(sc_menu, "cua_hang.png", th=self.inst.thresholds)
        if cua_hang.found and self.shop_offset:
            sx, sy = cua_hang.x, cua_hang.y
            off = self.shop_offset
            harvest_anchor = (sx + off['anchor'][0], sy + off['anchor'][1])
            harvest_sweep = [(sx + p[0], sy + p[1]) for p in off['sweep']]
            self._log("Đã bù trừ tọa độ Camera bị lệch khi mở Liềm.")

        liem = find_one(sc_menu, "liem.png", th=self.inst.thresholds)

        if not liem.found:
            self._debug_save(sc_menu, "harvest_khong_thay_liem", text="Loi_cong_cu")
            self._log("Trạng thái bất thường: Không tìm thấy công cụ (Liềm).")
            self._close_x(sc_menu)
            return

        # Tính toán đường vuốt (full_path) trước
        full_path, delays = self._build_tool_path((liem.x, liem.y), harvest_anchor, harvest_sweep)

        self._debug_save(
            sc_menu, "harvest_thay_liem",
            text="Gat_lua",
            tool_pt=(liem.x, liem.y),
            anchor=harvest_anchor,
            path=full_path
        )

        full_path, delays = self._build_tool_path((liem.x, liem.y), harvest_anchor, harvest_sweep)

        self.adb.hold_and_drag_path(
            hold_pt  = (liem.x, liem.y),
            path_pts = full_path,
            hold_ms  = 200,
            delays   = delays,
        )
        self._sleep(2500)

        sc2 = self._shot()
        if sc2 is not None:
            kho = find_one(sc2, "kho_day.png", th=self.inst.thresholds)
            if kho.found:
                self._log("Dung lượng kho đã đạt tối đa! Đang tiến hành giải phóng...")
                self._debug_save(sc2, "harvest_kho_day", text="Kho_day")
                self._close_x(sc2)
                self._sleep(1000)
                
                self.can_sell_crops = True
                if self.inst.enable_shop:
                    self._sales_cycle(keep_seeds=True)

        self.inst.stats.total_harvest += self.inst.max_cells if self.inst.max_cells > 0 else (r.cell_count if r else 0)
        self.inst.stats.total_cycles  += 1
        self.can_sell_crops = True
        
        self._log("Hoàn tất thu hoạch.")
        self.inst.last_plant_time = 0  

    # ── Plant cycle ───────────────────────────────────────────────────────────

    def _plant_cycle(self) -> None:
        self.inst.status = BotStatus.PLANTING
        self._log("Kích hoạt quy trình Gieo Hạt...")

        if not self._align_camera():
            self._log("Lỗi định vị khu vực canh tác. Hủy gieo hạt.")
            return
            
        r = self.inst.farm_region
        if not r: return

        self._tap(r.anchor[0], r.anchor[1])
        self._sleep(500)

        screen_after = self._shot()
        if screen_after is None: return

        current_anchor = r.anchor
        current_sweep_path = r.sweep_path

        cua_hang = find_one(screen_after, "cua_hang.png", th=self.inst.thresholds)
        if cua_hang.found and self.shop_offset:
            sx, sy = cua_hang.x, cua_hang.y
            off = self.shop_offset
            current_anchor = (sx + off['anchor'][0], sy + off['anchor'][1])
            current_sweep_path = [(sx + p[0], sy + p[1]) for p in off['sweep']]
            self._log("Đã bù trừ tọa độ Camera bị lệch khi mở Hạt giống.")

        seed_name = self.inst.crop_mode.seed_template()
        seed      = find_one(screen_after, seed_name, th=self.inst.thresholds)

        if not seed.found:
            self._debug_save(screen_after, "plant_khong_thay_hat", text="Loi_hat_giong")
            self._close_x(screen_after)
            return

        # Tính đường kéo hạt giống trước
        full_path, delays = self._build_tool_path((seed.x, seed.y), current_anchor, current_sweep_path)

        self._debug_save(
            screen_after, "plant_thay_hat",
            text="Tien_hanh_gieo_hat",
            tool_pt=(seed.x, seed.y),
            anchor=current_anchor,
            path=full_path
        )

        full_path, delays = self._build_tool_path((seed.x, seed.y), current_anchor, current_sweep_path)

        self.adb.hold_and_drag_path(
            hold_pt  = (seed.x, seed.y),
            path_pts = full_path,
            hold_ms  = 200,
            delays   = delays,
        )
        self._sleep(2000)

        self.inst.last_plant_time = time.time()
        self._log("Hoàn tất gieo hạt.")

        if self.inst.enable_shop:
            self._sales_cycle(keep_seeds=False)

    # ── Sales cycle ───────────────────────────────────────────────────────────

    def _sales_cycle(self, keep_seeds: bool = False) -> None:
        self.inst.status = BotStatus.SELLING
        self._log("Kiểm tra và thực hiện đăng bán nông sản...")
        
        screen = self._shot()
        if screen is None: return

        cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
        
        if not cua_hang.found:
            self._debug_save(screen, "shop_khong_thay_cua_hang", text="Loi_tim_cua_hang")
            self._log("Không tìm thấy Cửa hàng, hủy tiến trình bán.")
            return

        self._tap(cua_hang.x, cua_hang.y)
        self._sleep(1000)

        max_swipes = 10 
        swipes = 0
        luot_ban_toi_da = -1 

        while swipes < max_swipes:
            sc2 = self._shot()
            if sc2 is None: break

            self._debug_save(sc2, "ban_hang_trong_cua_hang", text=f"Trang_thai_shop_{swipes}")

            thung_da_ban_list = find_all(sc2, "thung_da_ban.png", th=self.inst.thresholds)
            thung_trong_list = find_all(sc2, "thung_trong.png", th=self.inst.thresholds)
            danh_sach_thung_co_the_ban = []

            # Nếu là màn hình đầu tiên (swipes == 0) mà KHÔNG CÓ thùng trống/đã bán
            if swipes == 0 and not thung_da_ban_list and not thung_trong_list:
                tien_vang = find_one(sc2, "tien_vang.png", th=self.inst.thresholds)
                if tien_vang.found:
                    self._log("Trang đầu tiên đang đầy hàng. Thử kiểm tra đăng báo quảng cáo...")
                    self._tap(tien_vang.x, tien_vang.y)
                    self._sleep(300)
                    
                    sc_adv = self._shot()
                    if sc_adv is not None:
                        # Tìm nút "Tạo tin quảng cáo" hoặc "Quảng cáo ngay"
                        quang_cao_ngay = find_one(sc_adv, "quang_cao_ngay.png", th=self.inst.thresholds)
                        self._debug_save(sc_adv, "trang_thai_thung_hang")

                        if quang_cao_ngay.found:
                            # 1. Tick vào nút quảng cáo trước
                            tick_qc = find_one(sc_adv, "nut_tick_dang_bao_2.png", th=self.inst.thresholds)
                            if not tick_qc.found:
                                tick_qc = find_one(sc_adv, "nut_tick_dang_bao_3.png", th=self.inst.thresholds)

                            self._debug_save(sc_adv, "tim_thay_nut_tick_quang_cao", tool_pt=(tick_qc.x, tick_qc.y))

                            if tick_qc.found:
                                self._tap(tick_qc.x, tick_qc.y, 1)
                                self._sleep(100)

                                # 2. Tap vào nút đăng báo
                                tao_tin = find_one(sc_adv, "tao_tin_quang_cao.png", th=self.inst.thresholds)
                                if tao_tin.found:
                                    self._tap(tao_tin.x, tao_tin.y)
                                    self._log("Đã đăng báo thành công cho thùng hàng hiện tại.")
                            else:
                                self._log("Không tìm thấy nút tick quảng cáo.")
                                self._close_x(sc_adv)
                                                            
                        else:
                            self._log("Thùng hàng này chưa thể đăng báo (chưa hồi thời gian).")
                            self._close_x(sc_adv)

            if thung_da_ban_list:
                self._log(f"Phát hiện {len(thung_da_ban_list)} đơn hàng đã bán. Đang thu thập...")
                for sold in thung_da_ban_list:
                    self._tap(sold.x, sold.y, 1)
                    danh_sach_thung_co_the_ban.append((sold.x, sold.y))

            for trong in thung_trong_list:
                danh_sach_thung_co_the_ban.append((trong.x, trong.y))

            if self.can_sell_crops and danh_sach_thung_co_the_ban:
                for tx, ty in danh_sach_thung_co_the_ban:
                    if not self.can_sell_crops: break

                    self._tap(tx, ty)
                    self._sleep(200)
                    
                    sc_menu = self._shot()
                    if sc_menu is not None:
                        lua_kho = find_one(sc_menu, "lua_kho.png", th=self.inst.thresholds)
                        
                        if lua_kho.found:
                            if luot_ban_toi_da == -1:
                                so_luong = self._read_quantity(sc_menu, lua_kho)
                                
                                if keep_seeds:
                                    an_toan = self.inst.max_cells + 10
                                    self._log(f"Trạng thái Kho đầy: Tối thiểu cần giữ {an_toan} lúa. Hiện có: {so_luong}")
                                else:
                                    an_toan = 10
                                    self._log(f"Trạng thái Chờ: Tối thiểu cần giữ {an_toan} lúa. Hiện có: {so_luong}")
                                
                                if so_luong > an_toan:
                                    luot_ban_toi_da = (so_luong - an_toan) // 10
                                    if luot_ban_toi_da < 1: luot_ban_toi_da = 1
                                    self._log(f"=> Cho phép thiết lập {luot_ban_toi_da} lượt bán.")
                                else:
                                    luot_ban_toi_da = 0

                            if luot_ban_toi_da > 0:
                                self._tap(lua_kho.x, lua_kho.y, 1)

                                if self.cached_mui_ten:
                                    self._tap(self.cached_mui_ten[0], self.cached_mui_ten[1], 1)
                                
                                qc = find_one(sc_menu, "nut_tick_dang_bao.png", th=self.inst.thresholds)
                                if qc.found:
                                    self._tap(qc.x, qc.y, 1)
                                
                                if self.cached_tao_ban:
                                    self._tap(self.cached_tao_ban[0], self.cached_tao_ban[1])
                                else:
                                    self._log("Cảnh báo: Dữ liệu nút UI không tồn tại trong bộ nhớ.")
                                    
                                luot_ban_toi_da -= 1
                                self._sleep(10)
                            else:
                                self.can_sell_crops = False 
                                self._log(f"Ngừng quá trình do không đáp ứng mức an toàn dự trữ.")
                                self._close_x(sc_menu)
                                self._sleep(100)
                                break 
                        else:
                            self.can_sell_crops = False 
                            self._log("Không tìm thấy hàng hóa tương thích trong kho.")
                            self._close_x(sc_menu)
                            self._sleep(100)
                            break 

            het_hom = find_one(sc2, "het_hom_do.png", th=self.inst.thresholds)
            if het_hom.found:
                self._log("Đã duyệt hết danh sách hòm đồ.")
                break 

            sw, sh = self.adb._screen_size()
            self.adb.run([
                "shell", "input", "swipe", 
                str(int(sw*0.75)), str(int(sh*0.5)), 
                str(int(sw*0.35)), str(int(sh*0.5)), 
                "500"
            ])
            self._sleep(500)
            swipes += 1

        self._log("Kết thúc phiên làm việc tại Cửa hàng.")
        self._close_x()

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        try:
            serial_to_use = self.inst.adb_serial
            if serial_to_use and serial_to_use.isdigit():
                serial_to_use = f"127.0.0.1:{serial_to_use}"

            self.adb = AdbController(adb_path=self.inst.adb_path, serial=serial_to_use)

            ok, msg = self.adb.full_connect()
            if not ok:
                self.inst.status = BotStatus.ERROR
                self._log(f"Lỗi hệ thống ADB: {msg}")
                return

            self.inst.adb_serial = self.adb.serial
            self._log(f"Kết nối ADB thành công: {msg}")

            # self._close_all_popups()
            # self._zoom_out()

            if self.inst.enable_shop:
                success = self._init_shop_and_cache()
                if not success:
                    self._log("Hệ thống tự động dừng vì không thể thiết lập Cửa hàng theo yêu cầu.")
                    self.inst.status = BotStatus.STOPPED
                    self.inst.is_running = False
                    return

            while True:
                self._check_stop()
                try:
                    screen = self._shot()
                    if screen is None:
                        self._sleep(3000)
                        continue
                    
                    if self.inst.farm_region and getattr(self, 'shop_offset', None):
                        cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
                        if cua_hang.found:
                            sx, sy = cua_hang.x, cua_hang.y
                            off = self.shop_offset
                            r = self.inst.farm_region
                            r.bbox = (sx + off['bbox'][0], sy + off['bbox'][1], sx + off['bbox'][2], sy + off['bbox'][3])
                            r.anchor = (sx + off['anchor'][0], sy + off['anchor'][1])
                            r.sweep_path = [(sx + p[0], sy + p[1]) for p in off['sweep']]
                            r.polygon = [(sx + p[0], sy + p[1]) for p in off['poly']]
                        else:
                            self._log("Cảnh báo: Camera bị lệch quá xa, không thấy Cửa hàng để neo tọa độ. Đang kéo lại camera...")
                            self._align_shop_to_bottom_left()
                            continue

                    cells = find_soil_cells(screen, th=self.inst.thresholds)

                    if not self.inst.farm_region:
                        if cells:
                            self._update_region(cells, screen)
                            self._log(f"Đã nhận diện thành công khu vực nông trại và neo tọa độ vào Cửa hàng.")
                        else:
                            self.inst.status = BotStatus.SCANNING
                            self._debug_save(screen, "cho_dat_trong_de_khoi_tao", text="Yeu_cau_dat_trong")
                            self._log("Vui lòng để lộ ít nhất 1 ô đất trống (hoặc tự gặt 1 ô) để bot lưu tọa độ...")
                            
                            self.scan_fail_count = getattr(self, 'scan_fail_count', 0) + 1
                            if self.scan_fail_count >= 6: 
                                self._log("Quá thời gian chờ, tiến hành khôi phục lại ứng dụng...")
                                self._check_and_restart_game()
                                self.scan_fail_count = 0
                                
                            self._sleep(5000)
                            continue
                    
                    self.scan_fail_count = 0 
                    
                    r = self.inst.farm_region

                    # if cells:
                    #     self._update_region(cells, screen)

                    hsv_img = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
                    lower_yellow = np.array([18, 120, 150])
                    upper_yellow = np.array([33, 255, 255])
                    mask = cv2.inRange(hsv_img, lower_yellow, upper_yellow)
                    
                    # --- SỬ DỤNG MẶT NẠ ĐỘNG (DYNAMIC MASK) ĐỂ TÍNH PHẦN TRĂM ---
                    farm_mask = np.zeros(screen.shape[:2], dtype=np.uint8)
                    for p in r.sweep_path:
                        cv2.circle(farm_mask, (int(p[0]), int(p[1])), 75, 255, -1)
                    
                    farm_roi_mask = cv2.bitwise_and(mask, farm_mask)
                    yellow_pixels = cv2.countNonZero(farm_roi_mask)
                    est_grown_cells = yellow_pixels / 1200.0  
                    
                    total_cells = self.inst.max_cells if self.inst.max_cells > 0 else (r.cell_count or 1)
                    self.inst.pct_grown = (est_grown_cells / total_cells) * 100
                    self.inst.pct_grown = min(100.0, self.inst.pct_grown)

                    valid_empty = []
                    for c in (cells or []):
                        # Cập nhật thuật toán đếm đất trống để khớp hoàn toàn với Mặt nạ
                        if 0 <= c.y < farm_mask.shape[0] and 0 <= c.x < farm_mask.shape[1]:
                            if farm_mask[int(c.y), int(c.x)] > 0:
                                valid_empty.append(c)
                    empty_count = len(valid_empty)
                    self.inst.pct_empty = (empty_count / total_cells) * 100

                    if self.inst.debug_mode:
                        debug_img = screen.copy()
                        # Vẽ chính xác đường viền ngoài cùng của mặt nạ để debug
                        mask_contours, _ = cv2.findContours(farm_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        cv2.drawContours(debug_img, mask_contours, -1, (0, 0, 255), 2)
                        
                        self._debug_save(
                            debug_img, 
                            "trang_thai_canh_tac", 
                            text=f"Dat trong: {empty_count} | Lua chin: {est_grown_cells:.1f}",
                            cells=valid_empty
                        )
                    
                    sec = self.inst.seconds_until_ready()
                    is_time_up = (self.inst.last_plant_time > 0 and sec == 0)

                    if is_time_up:
                        self._harvest_cycle()
                    elif self.inst.pct_empty >= 40:
                        self._plant_cycle()
                    elif self.inst.last_plant_time == 0 and est_grown_cells >= 2 and est_grown_cells >= empty_count:
                        self._harvest_cycle()
                    elif self.inst.last_plant_time == 0 and self.inst.pct_grown >= 30:
                        self._harvest_cycle()
                    else:
                        self.inst.status = BotStatus.WAITING
                        
                        if sec > 0:
                            if self.inst.enable_shop:
                                self._log(f"Đang chờ... Còn {sec}s. Tranh thủ vào shop thu tiền/bán hàng.")
                                self._sales_cycle(keep_seeds=False)
                                self._sleep(5000) 
                            else:
                                wait_ms = min(sec * 1000, 15_000)
                                self._log(f"Đang chờ... Còn {sec}s.")
                                self._sleep(wait_ms)
                        else:
                            self._log("Ruộng đang trong giai đoạn phát triển. Đang theo dõi thêm...")
                            self._sleep(5000)

                except StopException:
                    raise
                except Exception as e:
                    self._log(f"Phát sinh lỗi trong quy trình chính: {e}")
                    logger.exception(f"[Bot-{self.inst.id}] Lỗi hệ thống:")
                    self._sleep(5000)

        except StopException:
            self._log("Tiến trình đã được dừng an toàn.")
        except Exception as e:
            self._log(f"Tiến trình bị gián đoạn do lỗi: {e}")
        finally:
            self.inst.status = BotStatus.STOPPED
            self.inst.is_running = False