"""
Farm Engine - vòng lặp chính của bot, chạy trong thread riêng cho mỗi instance.
Chu trình: quét vùng farm -> đánh giá tình trạng -> thu hoạch / gieo hạt.
"""
import threading
import time
import random
import logging
from typing import Optional, Callable
import cv2
import numpy as np

from core.models import BotInstance, BotStatus, FarmRegion
from core.adb import AdbController, make_adb
from core.vision import (
    find_one,
    find_all,
    find_soil_cells,
    find_grown_crops,
    build_farm_sweep,
    compute_polygon,
    compute_bbox,
    draw_debug,
    save_debug,
)

logger = logging.getLogger(__name__)


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
        
        # --- BIẾN TOÀN CỤC: Ghi nhớ trạng thái có đủ lúa để bán không ---
        self.can_sell_crops = True 

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
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
        self._log("Đã dừng bot.")

    def force_scan(self):
        self.inst.farm_region = None
        self.inst.max_cells = 0 
        self._log("Yêu cầu quét lại vùng farm...")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        logger.info(f"[Bot-{self.inst.id}] {msg}")
        self.inst.add_log(msg)
        if self.on_log:
            self.on_log(msg)

    def _sleep(self, ms: int):
        end = time.time() + ms / 1000.0
        while time.time() < end:
            if self._stop.is_set():
                return
            time.sleep(0.05)

    def _shot(self) -> Optional[np.ndarray]:
        return self.adb.screenshot()

    def _tap(self, x: int, y: int, delay_ms: int = 100):
        self.adb.tap(x, y, delay_ms)

    def _th(self, tmpl_name: str) -> float:
        return self.inst.thresholds.get(tmpl_name)

    def _debug_save(self, screen: np.ndarray, step: str, **kw) -> None:
        if not self.inst.debug_mode or screen is None:
            return
        self.debug_counter += 1
        step_with_counter = f"{self.debug_counter}_{step}"
        annotated = draw_debug(screen, label=step_with_counter, **kw)
        path = save_debug(annotated, step_with_counter, inst_id=self.inst.id)
        self._log(f"[DEBUG] Lưu ảnh: {path}")

    def _interp(self, p1: tuple[int, int], p2: tuple[int, int], steps: int = 8) -> list[tuple[int, int]]:
        return [
            (
                int(p1[0] + (p2[0] - p1[0]) * i / steps),
                int(p1[1] + (p2[1] - p1[1]) * i / steps),
            )
            for i in range(1, steps + 1)
        ]

    def _jiggle(self, pts: list[tuple[int, int]], amp: int = 8) -> list[tuple[int, int]]:
        return [(x + random.randint(-amp, amp), y + random.randint(-amp, amp)) for x, y in pts]

    def _close_x(self, screen: Optional[np.ndarray] = None) -> bool:
        if screen is None:
            screen = self._shot()
        if screen is None:
            self._tap(10, 10)
            return False

        x_btn = find_one(screen, "dong_x.png", th=self.inst.thresholds)
        if not x_btn.found:
            x_btn = find_one(screen, "dong_x_2.png", th=self.inst.thresholds)

        if x_btn.found:
            self._log(f"Tìm thấy nút X để đóng (score={x_btn.score:.3f}).")
            self._debug_save(screen, "phat_hien_nut_x_de_dong", tool_pt=(x_btn.x, x_btn.y))
            self._tap(x_btn.x, x_btn.y)
            return True
        else:
            self._log("Không thấy nút X, dùng tap (10, 10) để đóng tạm.")
            self._tap(10, 10)
            return False

    # ── Doc so luong Pytesseract ──────────────────────────────────────────────

    def _read_quantity(self, screen: np.ndarray, match_res) -> int:
        try:
            import pytesseract
            import cv2
            
            pytesseract.pytesseract.tesseract_cmd = self.inst.tesseract_path
            x, y = match_res.x, match_res.y
            
            x_start = max(0, x - 25)
            x_end = min(x + 85, screen.shape[1])
            y_start = max(0, y - 10)
            y_end = min(screen.shape[0], y + 60) 
            
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
            
            if self.inst.debug_mode:
                self.debug_counter += 1
                save_debug(thresh, f"{self.debug_counter}_ocr_roi_kiem_tra", inst_id=self.inst.id)
            
            config = '--psm 7 -c tessedit_char_whitelist=0123456789'
            text = pytesseract.image_to_string(thresh, config=config)
            
            num_str = text.strip()
            if not num_str:
                self._log("OCR không đọc được số nào (trả về rỗng). Tạm coi là 0.")
                return 0
                
            num = int(num_str)
            # self._log(f"Đọc được số lượng kho: {num}")
            return num
        except Exception as e:
            self._log(f"Lỗi đọc số OCR: {e}. Tạm coi là 0.")
            return 0

    # ── Farm region ───────────────────────────────────────────────────────────

    def _update_region(self, cells: list, screen: Optional[np.ndarray] = None) -> None:
        if not cells: return

        if self.inst.farm_region is None or len(cells) >= self.inst.max_cells:
            if len(cells) > self.inst.max_cells:
                self.inst.max_cells = len(cells)
                self._log(f"Đã cập nhật số lượng ô đất tối đa: {self.inst.max_cells} ô")

            sweep = build_farm_sweep(cells)
            poly  = compute_polygon(cells)
            bbox  = compute_bbox(cells)

            cx = sum(c.x for c in cells) / len(cells)
            cy = sum(c.y for c in cells) / len(cells)
            anchor_cell = min(cells, key=lambda c: (c.x - cx) ** 2 + (c.y - cy) ** 2)

            self.inst.farm_region = FarmRegion(
                polygon    = poly,
                sweep_path = sweep,
                anchor     = (anchor_cell.x, anchor_cell.y),
                cell_count = len(cells),
                bbox       = bbox,
                last_scan  = time.time(),
            )

            if screen is not None:
                self._debug_save(
                    screen, "scan_vung_dat",
                    polygon=poly,
                    cells=cells,
                    anchor=(anchor_cell.x, anchor_cell.y),
                    path=sweep if sweep else None,
                )

    # ── Build gesture path ────────────────────────────────────────────────────

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
            
        self._log("Căn giữa camera để lấy tọa độ chuẩn...")
        self._tap(r.anchor[0], r.anchor[1])
        self._sleep(1500)
        
        if self._stop.is_set():
            return False
            
        self._tap(15, 100) 
        self._sleep(1000)
        
        screen_check = self._shot()
        if screen_check is not None:
            x_btn = find_one(screen_check, "dong_x.png", th=self.inst.thresholds)
            if not x_btn.found:
                x_btn = find_one(screen_check, "dong_x_2.png", th=self.inst.thresholds)
                
            if x_btn.found:
                self._log("Phát hiện popup lạ, đang đóng...")
                self._tap(x_btn.x, x_btn.y)
                self._sleep(800) 
        
        screen = self._shot()
        if screen is None:
            return False
            
        cells = find_soil_cells(screen, th=self.inst.thresholds)
        if not cells:
            self._log("Không thấy đất sau khi căn giữa!")
            return False
            
        self.inst.farm_region = None 
        self._update_region(cells, screen)
        return True

    # ── Harvest cycle ─────────────────────────────────────────────────────────

    def _harvest_cycle(self) -> None:
        self.inst.status = BotStatus.HARVESTING
        self._log("Bắt đầu gặt lúa...")

        r = self.inst.farm_region
        
        if not r:
            self._log("Không tìm thấy dữ liệu vùng farm. Quét lại camera...")
            if not self._align_camera():
                return
            r = self.inst.farm_region

        harvest_anchor = None
        harvest_sweep = None
        valid_area_found = False
        
        expected_area = (self.inst.max_cells if self.inst.max_cells > 0 else r.cell_count) * 800
        min_required_area = expected_area * 0.4 

        for attempt in range(5):
            if self._stop.is_set():
                return
                
            screen = self._shot()
            if screen is None:
                self._sleep(1000)
                continue

            hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
            lower_yellow = np.array([18, 120, 150])
            upper_yellow = np.array([33, 255, 255])
            mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
            
            bx1, by1, bx2, by2 = map(int, r.bbox)
            
            bx1 = max(0, bx1 - 30)
            by1 = max(0, by1 - 30)
            bx2 = min(screen.shape[1], bx2 + 30)
            by2 = min(screen.shape[0], by2 + 30)
            
            farm_mask = np.zeros_like(mask)
            cv2.rectangle(farm_mask, (bx1, by1), (bx2, by2), 255, -1)
            mask = cv2.bitwise_and(mask, farm_mask)
            
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.dilate(mask, kernel, iterations=3)
            
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if contours:
                best_contour = max(contours, key=cv2.contourArea)
                area = cv2.contourArea(best_contour)
                
                if area >= min_required_area:
                    valid_area_found = True
                    
                    M = cv2.moments(best_contour)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                    else:
                        x, y, w, h = cv2.boundingRect(best_contour)
                        cx, cy = x + w//2, y + h//2
                        
                    harvest_anchor = (cx, cy)
                    
                    x, y, w, h = cv2.boundingRect(best_contour)
                    mock_cells = []
                    class MockCell:
                        def __init__(self, px, py):
                            self.x, self.y = px, py
                    
                    for py in range(y + 15, y + h, 35):
                        for px in range(x + 15, x + w, 35):
                            if cv2.pointPolygonTest(best_contour, (px, py), False) >= 0:
                                mock_cells.append(MockCell(px, py))
                                
                    if not mock_cells:
                        mock_cells.append(MockCell(cx, cy))
                        
                    harvest_sweep = build_farm_sweep(mock_cells)
                    
                    self._log(f"HSV: Đã quét thấy vùng lúa chín (diện tích {area:.0f}px, kỳ vọng ~{expected_area}px). Tâm: {harvest_anchor}")
                    
                    if self.inst.debug_mode:
                        out_img = screen.copy()
                        cv2.drawContours(out_img, [best_contour], -1, (0, 255, 0), 2)
                        cv2.circle(out_img, harvest_anchor, 8, (0, 140, 255), -1)
                        for c in mock_cells:
                            cv2.circle(out_img, (c.x, c.y), 4, (0, 255, 255), -1)
                        self.debug_counter += 1
                        save_debug(out_img, f"{self.debug_counter}_harvest_hsv_vung_lua", inst_id=self.inst.id)
                        
                    break
                else:
                    self._log(f"Lần {attempt+1}/5: Vùng lúa ({area:.0f}px) quá nhỏ so với dự kiến (~{expected_area}px). Thử lại...")
            else:
                self._log(f"Lần {attempt+1}/5: Không tìm thấy dải màu lúa chín. Thử lại...")
                
            self._sleep(1000)

        if not valid_area_found:
            self._log("LỖI: Đã thử 5 lần nhưng không quét được vùng lúa chín trùng khớp. Dừng Bot để bảo vệ.")
            self.inst.status = BotStatus.ERROR
            self.stop()
            return

        self._tap(harvest_anchor[0], harvest_anchor[1])
        self._sleep(1500)
        if self._stop.is_set():
            return

        sc_menu = self._shot()
        if sc_menu is None:
            return

        liem = find_one(sc_menu, "liem.png", th=self.inst.thresholds)

        if not liem.found:
            self._debug_save(sc_menu, "harvest_khong_thay_liem")
            self._log("Cảnh báo: Không thấy liềm! Có thể menu bị kẹt. Xóa đồng hồ đếm ngược.")
            self.inst.last_plant_time = 0 
            self._close_x(sc_menu)
            return

        self._debug_save(
            sc_menu, "harvest_thay_liem",
            tool_pt=(liem.x, liem.y),
            anchor=harvest_anchor,
        )

        full_path, delays = self._build_tool_path(
            (liem.x, liem.y), harvest_anchor, harvest_sweep,
        )

        self.adb.hold_and_drag_path(
            hold_pt  = (liem.x, liem.y),
            path_pts = full_path,
            hold_ms  = 200,
            delays   = delays,
        )
        self._sleep(2500)
        if self._stop.is_set():
            return

        sc2 = self._shot()
        if sc2 is not None:
            kho = find_one(sc2, "kho_day.png", th=self.inst.thresholds)
            if kho.found:
                self._log("Kho đầy! Đóng popup và đi bán bớt nông sản...")
                self._debug_save(sc2, "harvest_kho_day")
                self._close_x(sc2)
                self._sleep(1000)
                
                self.can_sell_crops = True
                
                if self.inst.enable_shop and not self._stop.is_set():
                    self._sales_cycle(keep_seeds=True)

        self.inst.stats.total_harvest += self.inst.max_cells if self.inst.max_cells > 0 else r.cell_count
        self.inst.stats.total_cycles  += 1
        
        self.can_sell_crops = True
        
        self._log("Gặt xong. Đợi vòng lặp chính quét lại mẫu đất mới để gieo hạt...")
        self.inst.farm_region = None
        self.inst.last_plant_time = 0  

    # ── Plant cycle ───────────────────────────────────────────────────────────

    def _plant_cycle(self) -> None:
        self.inst.status = BotStatus.PLANTING
        self._log("Chuẩn bị gieo hạt. Căn giữa camera và lấy mẫu đất...")

        if not self._align_camera():
            self._log("Lỗi căn giữa hoặc không thấy đất. Hủy gieo hạt.")
            return
            
        r = self.inst.farm_region
        if not r:
            return

        self._tap(r.anchor[0], r.anchor[1])
        self._sleep(1500)
        if self._stop.is_set():
            return

        screen = self._shot()
        if screen is None:
            self._log("Không chụp được màn hình!")
            return

        seed_name = self.inst.crop_mode.seed_template()
        seed      = find_one(screen, seed_name, th=self.inst.thresholds)

        if not seed.found:
            self._debug_save(screen, "plant_khong_thay_hat")
            self._close_x(screen)
            return

        self._debug_save(
            screen, "plant_thay_hat",
            tool_pt=(seed.x, seed.y),
            anchor=r.anchor,
        )

        full_path, delays = self._build_tool_path(
            (seed.x, seed.y), r.anchor, r.sweep_path,
        )

        self.adb.hold_and_drag_path(
            hold_pt  = (seed.x, seed.y),
            path_pts = full_path,
            hold_ms  = 200,
            delays   = delays,
        )
        self._sleep(2000)

        self.inst.last_plant_time = time.time()
        self._log("Gieo hạt xong. Bắt đầu đếm ngược...")

        if self.inst.enable_shop and not self._stop.is_set():
            self._sales_cycle(keep_seeds=False)

    # ── Sales cycle ───────────────────────────────────────────────────────────

    def _sales_cycle(self, keep_seeds: bool = False) -> None:
        self.inst.status = BotStatus.SELLING
        self._log("Bắt đầu quá trình vào cửa hàng bán hàng...")
        
        screen = self._shot()
        if screen is None:
            self._log("Lỗi: Không chụp được màn hình khi vào shop!")
            return

        cua_hang = find_one(screen, "cua_hang.png", th=self.inst.thresholds)
        
        if not cua_hang.found:
            self._debug_save(screen, "shop_khong_thay_cua_hang")
            self._log("Không tìm thấy cửa hàng, hủy quá trình bán hàng và quay lại chờ.")
            return

        self._log("Đã thấy cửa hàng, đang tap mở...")
        self._tap(cua_hang.x, cua_hang.y)
        self._sleep(2000)
        if self._stop.is_set():
            return

        max_swipes = 15 
        swipes = 0
        
        luot_ban_toi_da = -1 
        
        # [TỐI ƯU 4] Bộ nhớ đệm (Cache) tọa độ các nút cố định để không quét lại
        cached_mui_ten = None
        cached_tao_ban = None

        while not self._stop.is_set() and swipes < max_swipes:
            sc2 = self._shot()
            if sc2 is None:
                break

            self._debug_save(sc2, "ban_hang_trong_cua_hang")

            # [TỐI ƯU 3] Quét cả thùng đã bán và thùng trống trên CÙNG 1 ẢNH
            thung_da_ban_list = find_all(sc2, "thung_da_ban.png", th=self.inst.thresholds)
            thung_trong_list = find_all(sc2, "thung_trong.png", th=self.inst.thresholds)
            
            # Danh sách tọa độ tổng hợp để tap bán hàng
            danh_sach_thung_co_the_ban = []

            if thung_da_ban_list:
                self._log(f"Tìm thấy {len(thung_da_ban_list)} thùng đã bán, đang thu tiền...")
                for sold in thung_da_ban_list:
                    self._tap(sold.x, sold.y, 1)
                    # self._sleep(500)
                    if self._stop.is_set():
                        return
                    # Nhận tiền xong, thùng đó lập tức biến thành thùng trống -> Lưu ngay tọa độ
                    danh_sach_thung_co_the_ban.append((sold.x, sold.y))

            # Ghép thêm các thùng trống quét được từ đầu
            for trong in thung_trong_list:
                danh_sach_thung_co_the_ban.append((trong.x, trong.y))

            # Bắt đầu vòng lặp bán hàng theo danh sách tọa độ tổng hợp
            if self.can_sell_crops and danh_sach_thung_co_the_ban:
                for tx, ty in danh_sach_thung_co_the_ban:
                    if self._stop.is_set():
                        return
                    
                    if not self.can_sell_crops: 
                        break

                    self._log("Đang tap vào hòm đồ để bán hàng...")
                    self._tap(tx, ty)
                    self._sleep(200)
                    
                    sc_menu = self._shot()
                    if sc_menu is not None:
                        # Chỉ cần tìm vị trí hạt lúa và nút tick đăng báo
                        lua_kho = find_one(sc_menu, "lua_kho.png", th=self.inst.thresholds)
                        
                        if lua_kho.found:
                            # [TỐI ƯU 1 & 2] Tính toán số lượng cần giữ lại dựa theo hoàn cảnh
                            if luot_ban_toi_da == -1:
                                so_luong = self._read_quantity(sc_menu, lua_kho)
                                
                                if keep_seeds:
                                    an_toan = self.inst.max_cells + 10
                                    self._log(f"Kho đầy: Phải giữ {an_toan} lúa (Đất: {self.inst.max_cells} + 10). Đang có: {so_luong}")
                                else:
                                    an_toan = 10
                                    self._log(f"Chờ thu hoạch: Chỉ cần giữ {an_toan} lúa. Đang có: {so_luong}")
                                
                                if so_luong > an_toan:
                                    luot_ban_toi_da = (so_luong - an_toan) // 10
                                    if luot_ban_toi_da < 1:
                                        luot_ban_toi_da = 1
                                    self._log(f"=> Cho phép bán tối đa {luot_ban_toi_da} lượt.")
                                else:
                                    luot_ban_toi_da = 0

                            # Tiến hành bán nếu còn lượt
                            if luot_ban_toi_da > 0:
                                # Tap vào lúa
                                self._tap(lua_kho.x, lua_kho.y, 1)
                                # self._sleep(20)
                                
                                # [TỐI ƯU 4] Chỉ quét nút mờ 1 lần và nạp vào Cache
                                if not cached_mui_ten:
                                    mui_ten = find_one(sc_menu, "mui_ten_phai.png", th=self.inst.thresholds)
                                    if mui_ten.found:
                                        cached_mui_ten = (mui_ten.x, mui_ten.y)
                                
                                if not cached_tao_ban:
                                    tao_ban = find_one(sc_menu, "tao_rao_ban.png", th=self.inst.thresholds)
                                    if tao_ban.found:
                                        cached_tao_ban = (tao_ban.x, tao_ban.y)
                                        
                                # Dùng Cache để Tap nút Max giá
                                if cached_mui_ten:
                                    self._tap(cached_mui_ten[0], cached_mui_ten[1], 1)
                                    # self._sleep(300)
                                
                                # Quét nút Tick đăng báo (Vì đôi lúc bị cooldown không hiện)
                                qc = find_one(sc_menu, "nut_tick_dang_bao.png", th=self.inst.thresholds)
                                if qc.found:
                                    self._tap(qc.x, qc.y, 1)
                                    # self._sleep(300)
                                
                                # Dùng Cache để Tap nút Tạo rao bán
                                if cached_tao_ban:
                                    self._tap(cached_tao_ban[0], cached_tao_ban[1])
                                else:
                                    self._log("Không tìm thấy nút Tạo rao bán, có thể do UI chưa load kịp.")
                                    
                                luot_ban_toi_da -= 1
                                self._sleep(10)
                            else:
                                self.can_sell_crops = False 
                                self._log(f"Số lượng lúa không đủ (Hoặc đã hết lượt bán). Ngừng click hòm đồ.")
                                self._close_x(sc_menu)
                                self._sleep(100)
                                break 
                        else:
                            self.can_sell_crops = False 
                            self._log("Cảnh báo: Không tìm thấy lúa trong shop. Dừng bán.")
                            self._debug_save(sc_menu, "shop_khong_thay_lua")
                            self._close_x(sc_menu)
                            self._sleep(100)
                            break 

            het_hom = find_one(sc2, "het_hom_do.png", th=self.inst.thresholds)
            if het_hom.found:
                self._log("Đã cuộn đến hết hòm đồ, dừng bán.")
                break 

            self._log("Cuộn màn hình sang hòm đồ tiếp theo...")
            sw, sh = self.adb._screen_size()
            
            self.adb.run([
                "shell", "input", "swipe", 
                str(int(sw*0.75)), str(int(sh*0.5)), 
                str(int(sw*0.35)), str(int(sh*0.5)), 
                "500"
            ])
            self._sleep(500)
            swipes += 1

        self._log("Hoàn tất duyệt shop, đóng cửa hàng.")
        self._close_x()

    def _scan_and_tap_sequence(self, screen: np.ndarray, templates: list[str], delay_ms: int = 500) -> None:
        """
        [TỐI ƯU] Hàm quét nhiều template trên cùng 1 ảnh duy nhất và tap theo thứ tự.
        Truyền vào danh sách args (templates), tìm tọa độ của tất cả, sau đó mới tap.
        """
        coords_to_tap = []
        
        # 1. Quét toàn bộ args trên cùng 1 bức ảnh truyền vào
        for tmpl in templates:
            match = find_one(screen, tmpl, th=self.inst.thresholds)
            if match.found:
                coords_to_tap.append((tmpl, match.x, match.y))
            else:
                self._log(f"Chuỗi tap: Bỏ qua '{tmpl}' do không tìm thấy trên ảnh hiện tại.")
                
        # 2. Thực hiện tap lần lượt theo tọa độ đã lưu
        for tmpl, x, y in coords_to_tap:
            self._tap(x, y)
            self._sleep(delay_ms)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        self.adb = make_adb(self.inst.adb_path, self.inst.emu_index)
        if self.inst.adb_serial:
            self.adb.serial = self.inst.adb_serial

        ok, msg = self.adb.full_connect()
        if not ok:
            self.inst.status = BotStatus.ERROR
            self._log(f"Lỗi ADB: {msg}")
            return

        self.inst.adb_serial = self.adb.serial
        self._log(f"ADB: {msg}")

        try:
            sw, sh = self.adb._screen_size()
            dev, mx, my = self.adb._detect_touch_device()
            self._log(f"Màn hình: {sw}x{sh} | Touch device: {dev}")
        except Exception as e:
            self._log(f"[WARN] Không detect được touch device: {e}")

        while not self._stop.is_set():
            try:
                screen = self._shot()
                if screen is None:
                    self._sleep(3000)
                    continue

                cells    = find_soil_cells(screen, th=self.inst.thresholds)
                was_init = self.inst.farm_region is not None

                if cells:
                    self._update_region(cells, screen if not was_init else None)
                    if not was_init:
                        self._log(f"Đã định vị vùng farm ({len(cells)} ô đất).")

                if not self.inst.farm_region:
                    self.inst.status = BotStatus.SCANNING
                    self._debug_save(screen, "scanning_chua_thay_dat")
                    self._log("Chưa thấy đất trống. Thử lại sau 5s...")
                    self._sleep(5000)
                    continue

                r    = self.inst.farm_region
                bbox = r.bbox  

                hsv_img = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
                lower_yellow = np.array([18, 120, 150])
                upper_yellow = np.array([33, 255, 255])
                yellow_mask = cv2.inRange(hsv_img, lower_yellow, upper_yellow)
                
                bx1, by1, bx2, by2 = map(int, bbox)
                bx1, by1 = max(0, bx1), max(0, by1)
                bx2, by2 = min(screen.shape[1], bx2), min(screen.shape[0], by2)
                
                if bx2 > bx1 and by2 > by1:
                    farm_roi_mask = yellow_mask[by1:by2, bx1:bx2]
                    yellow_pixels = cv2.countNonZero(farm_roi_mask)
                    est_grown_cells = yellow_pixels / 800.0
                    total_cells = self.inst.max_cells if self.inst.max_cells > 0 else (r.cell_count or 1)
                    
                    self.inst.pct_grown = (est_grown_cells / total_cells) * 100
                    self.inst.pct_grown = min(100.0, self.inst.pct_grown)
                else:
                    self.inst.pct_grown = 0.0

                valid_empty = [c for c in (cells or []) if bbox[0] <= c.x <= bbox[2] and bbox[1] <= c.y <= bbox[3]]
                total = self.inst.max_cells if self.inst.max_cells > 0 else (r.cell_count or 1)
                self.inst.pct_empty = len(valid_empty) / total * 100

                sec = self.inst.seconds_until_ready()
                is_time_up = (self.inst.last_plant_time > 0 and sec == 0)

                if is_time_up:
                    self._harvest_cycle()
                
                elif self.inst.pct_empty >= 40:
                    self._plant_cycle()
                
                elif self.inst.last_plant_time == 0 and self.inst.pct_grown >= 50:
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
                        self._log("Ruộng đang trong giai đoạn phát triển (lúa xanh). Đang theo dõi thêm...")
                        self._sleep(5000)

            except Exception as e:
                self._log(f"Lỗi vòng lặp: {e}")
                logger.exception(f"[Bot-{self.inst.id}] Lỗi:")
                self._sleep(5000)

        self.inst.status = BotStatus.STOPPED