"""
Farm Engine - vong lap chinh cua bot, chay trong thread rieng cho moi instance.
Chu trinh: quet vung farm -> danh gia tinh trang -> thu hoach / gieo hat.
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
    build_sweep_path,
    build_row_waypoints,
    compute_polygon,
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
        self._log(f"Khoi dong | Cay: {self.inst.crop_mode.label()}")

    def stop(self):
        self._stop.set()
        self.inst.is_running = False
        self.inst.status     = BotStatus.STOPPED
        self._log("Da dung bot.")

    def force_scan(self):
        """
        Xoa farm_region hien tai.
        Vong lap chinh se quet lai o dat ngay vong tiep theo.
        Dung khi camera bi lech hay muon refresh toa do vung farm.
        """
        self.inst.farm_region = None
        self._log("Yeu cau quet lai vung farm...")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        logger.info(f"[Bot-{self.inst.id}] {msg}")
        self.inst.add_log(msg)
        if self.on_log:
            self.on_log(msg)

    def _sleep(self, ms: int):
        """Sleep co the bi ngat khi stop duoc goi."""
        end = time.time() + ms / 1000.0
        while time.time() < end:
            if self._stop.is_set():
                return
            time.sleep(0.05)

    def _shot(self) -> Optional[np.ndarray]:
        return self.adb.screenshot()

    def _tap(self, x: int, y: int, delay_ms: int = 200):
        self.adb.tap(x, y, delay_ms)

    def _th(self, tmpl_name: str) -> float:
        """Lay nguong nhan dien cua template tu config instance."""
        return self.inst.thresholds.get(tmpl_name)

    def _debug_save(self, screen: np.ndarray, step: str, **kw) -> None:
        """Luu anh debug neu debug_mode dang bat."""
        if not self.inst.debug_mode or screen is None:
            return
        annotated = draw_debug(screen, label=step, **kw)
        path = save_debug(annotated, step, inst_id=self.inst.id)
        self._log(f"[DEBUG] Luu anh: {path}")

    def _interp(
        self,
        p1:    tuple[int, int],
        p2:    tuple[int, int],
        steps: int = 8,
    ) -> list[tuple[int, int]]:
        """Tao cac diem trung gian giua p1 va p2 (khong bao gom p1, co p2)."""
        return [
            (
                int(p1[0] + (p2[0] - p1[0]) * i / steps),
                int(p1[1] + (p2[1] - p1[1]) * i / steps),
            )
            for i in range(1, steps + 1)
        ]

    def _jiggle(
        self,
        pts: list[tuple[int, int]],
        amp: int = 8,
    ) -> list[tuple[int, int]]:
        """Them nhieu ngau nhien nho vao tung diem de tranh bot bi nhan dien."""
        return [
            (x + random.randint(-amp, amp), y + random.randint(-amp, amp))
            for x, y in pts
        ]

    # ── Farm region ───────────────────────────────────────────────────────────

    def _update_region(self, cells: list, screen: Optional[np.ndarray] = None) -> None:
        """Cap nhat FarmRegion tu danh sach o dat moi detect duoc."""
        sweep = build_sweep_path(cells)
        wpts  = build_row_waypoints(sweep)
        poly  = compute_polygon(cells)

        cx = sum(c.x for c in cells) / len(cells)
        cy = sum(c.y for c in cells) / len(cells)
        anchor_cell = min(cells, key=lambda c: (c.x - cx) ** 2 + (c.y - cy) ** 2)

        self.inst.farm_region = FarmRegion(
            polygon    = poly,
            sweep_path = wpts,
            anchor     = (anchor_cell.x, anchor_cell.y),
            cell_count = len(cells),
            last_scan  = time.time(),
        )

        if screen is not None:
            self._debug_save(
                screen, "scan_vung_dat",
                polygon=poly,
                cells=cells,
                anchor=(anchor_cell.x, anchor_cell.y),
                path=wpts if wpts else None,
            )

    # ── Harvest cycle ─────────────────────────────────────────────────────────

    def _harvest_cycle(self) -> None:
        self.inst.status = BotStatus.HARVESTING
        self._log("Bat dau gat lua...")
        r = self.inst.farm_region

        # Buoc 1: tap vao o dat giua de mo menu phu
        self._tap(r.anchor[0], r.anchor[1])
        self._sleep(1500)
        if self._stop.is_set():
            return

        # Buoc 2: tim icon luoi liem trong menu phu
        screen = self._shot()
        if screen is None:
            self._log("Khong chup duoc man hinh!")
            return

        liem = find_one(screen, "liem.png", th=self.inst.thresholds)
        self._log(
            f"Tim liem.png: {'THAY' if liem.found else 'KHONG THAY'} "
            f"| score={liem.score:.3f} | nguong={self._th('liem.png'):.2f}"
        )

        if not liem.found:
            self._debug_save(screen, "harvest_khong_thay_liem")
            self._tap(10, 10)
            return

        self._debug_save(
            screen, "harvest_thay_liem",
            tool_pt=(liem.x, liem.y),
            anchor=r.anchor,
        )

        # Buoc 3: xay lo trinh keo
        #   liem -> anchor  : keo ve o vua tap (tat menu + gat o do)
        #   anchor -> farm  : keo qua toan bo vung farm
        row_wpts  = self._jiggle(r.sweep_path, amp=8)
        seg1      = self._interp((liem.x, liem.y), r.anchor, steps=12)
        seg2      = self._interp(r.anchor, row_wpts[0], steps=6)
        full_path = seg1 + seg2 + row_wpts

        self._debug_save(
            screen, "harvest_lo_trinh",
            tool_pt=(liem.x, liem.y),
            anchor=r.anchor,
            polygon=r.polygon,
            path=[(liem.x, liem.y)] + full_path,
        )
        self._log(
            f"Lo trinh gat: {len(full_path)} diem | "
            f"bat dau ({liem.x},{liem.y}) -> anchor ({r.anchor[0]},{r.anchor[1]}) "
            f"-> {len(row_wpts)} waypoints"
        )

        # Buoc 4: nhan giu liem + keo 1 mach khong nhac tay
        self.adb.hold_and_drag_path(
            hold_pt  = (liem.x, liem.y),
            path_pts = full_path,
            hold_ms  = 1000,
            step_ms  = 160,
        )
        self._sleep(2500)
        if self._stop.is_set():
            return

        # Xu ly popup kho day
        sc2 = self._shot()
        if sc2 is not None:
            kho = find_one(sc2, "kho_day.png", th=self.inst.thresholds)
            if kho.found:
                self._log("Kho day! Dong popup.")
                self._debug_save(sc2, "harvest_kho_day")
                self._tap(kho.x, kho.y)
                self._sleep(500)

        self.inst.stats.total_harvest += r.cell_count
        self.inst.stats.total_cycles  += 1
        self._log("Gat xong. Chuyen sang gieo hat...")
        self._plant_cycle()

    # ── Plant cycle ───────────────────────────────────────────────────────────

    def _plant_cycle(self) -> None:
        self.inst.status = BotStatus.PLANTING
        r = self.inst.farm_region

        # Buoc 1: tap vao o dat giua de mo menu phu
        self._tap(r.anchor[0], r.anchor[1])
        self._sleep(1500)
        if self._stop.is_set():
            return

        # Buoc 2: tim icon hat giong trong menu phu
        screen    = self._shot()
        if screen is None:
            self._log("Khong chup duoc man hinh!")
            return

        seed_name = self.inst.crop_mode.seed_template()
        seed      = find_one(screen, seed_name, th=self.inst.thresholds)
        self._log(
            f"Tim {seed_name}: {'THAY' if seed.found else 'KHONG THAY'} "
            f"| score={seed.score:.3f} | nguong={self._th(seed_name):.2f}"
        )

        if not seed.found:
            self._debug_save(screen, "plant_khong_thay_hat")
            self._tap(10, 10)
            return

        self._debug_save(
            screen, "plant_thay_hat",
            tool_pt=(seed.x, seed.y),
            anchor=r.anchor,
        )

        # Buoc 3: xay lo trinh keo
        row_wpts  = self._jiggle(r.sweep_path, amp=8)
        seg1      = self._interp((seed.x, seed.y), r.anchor, steps=12)
        seg2      = self._interp(r.anchor, row_wpts[0], steps=6)
        full_path = seg1 + seg2 + row_wpts

        self._debug_save(
            screen, "plant_lo_trinh",
            tool_pt=(seed.x, seed.y),
            anchor=r.anchor,
            polygon=r.polygon,
            path=[(seed.x, seed.y)] + full_path,
        )
        self._log(
            f"Lo trinh gieo: {len(full_path)} diem | "
            f"bat dau ({seed.x},{seed.y}) -> anchor ({r.anchor[0]},{r.anchor[1]}) "
            f"-> {len(row_wpts)} waypoints"
        )

        # Buoc 4: nhan giu hat giong + keo 1 mach khong nhac tay
        self.adb.hold_and_drag_path(
            hold_pt  = (seed.x, seed.y),
            path_pts = full_path,
            hold_ms  = 1000,
            step_ms  = 160,
        )
        self._sleep(2000)
        self.inst.last_plant_time = time.time()
        self._log("Gieo hat xong.")

        if self.inst.enable_shop and not self._stop.is_set():
            self._sales_cycle()

    # ── Sales cycle ───────────────────────────────────────────────────────────

    def _sales_cycle(self) -> None:
        self.inst.status = BotStatus.SELLING
        screen = self._shot()
        if screen is None:
            return

        cho = find_one(screen, "cho.png", th=self.inst.thresholds)
        if not cho.found:
            return

        self._tap(cho.x, cho.y)
        self._sleep(2000)
        if self._stop.is_set():
            return

        sc2 = self._shot()
        if sc2 is None:
            return

        self._debug_save(sc2, "ban_hang_cho")

        for sold in find_all(sc2, "thung_ban.png", th=self.inst.thresholds):
            self._tap(sold.x, sold.y)
            self._sleep(500)
            if self._stop.is_set():
                return

        for crate in find_all(sc2, "thung_hang.png", th=self.inst.thresholds)[:2]:
            if self._stop.is_set():
                return
            self._tap(crate.x, crate.y)
            self._sleep(900)
            sc3 = self._shot()
            if sc3 is not None:
                btn = find_one(sc3, "tao_rao_ban.png", th=self.inst.thresholds)
                if btn.found:
                    self._tap(btn.x, btn.y)
            self._sleep(700)

        sc4 = self._shot()
        if sc4 is not None:
            x_btn = find_one(sc4, "dong_x.png", th=self.inst.thresholds)
            if x_btn.found:
                self._tap(x_btn.x, x_btn.y)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        self.adb = make_adb(self.inst.adb_path, self.inst.emu_index)
        if self.inst.adb_serial:
            self.adb.serial = self.inst.adb_serial

        ok, msg = self.adb.full_connect()
        if not ok:
            self.inst.status = BotStatus.ERROR
            self._log(f"Loi ADB: {msg}")
            return

        self.inst.adb_serial = self.adb.serial
        self._log(f"ADB: {msg}")

        while not self._stop.is_set():
            try:
                screen = self._shot()
                if screen is None:
                    self._sleep(3000)
                    continue

                # Quet lai vung farm theo camera hien tai
                cells    = find_soil_cells(screen, th=self.inst.thresholds)
                was_init = self.inst.farm_region is not None

                if cells:
                    self._update_region(cells, screen if not was_init else None)
                    if not was_init:
                        self._log(f"Da dinh vi vung farm ({len(cells)} o dat).")

                if not self.inst.farm_region:
                    self.inst.status = BotStatus.SCANNING
                    self._debug_save(screen, "scanning_chua_thay_dat")
                    self._log("Chua thay dat trong. Thu lai sau 5s...")
                    self._sleep(5000)
                    continue

                r        = self.inst.farm_region
                poly_arr = np.array(r.polygon, np.int32)
                grown    = find_grown_crops(
                    screen,
                    self.inst.crop_mode.grown_template(),
                    th=self.inst.thresholds,
                )

                def in_poly(c) -> bool:
                    return cv2.pointPolygonTest(
                        poly_arr, (float(c.x), float(c.y)), False
                    ) >= 0

                valid_grown = [c for c in grown if in_poly(c)]
                valid_empty = [c for c in (cells or []) if in_poly(c)]

                total = r.cell_count or 1
                self.inst.pct_grown = len(valid_grown) / total * 100
                self.inst.pct_empty = len(valid_empty) / total * 100

                self._log(
                    f"Chin {self.inst.pct_grown:.0f}% "
                    f"({len(valid_grown)}/{total}) | "
                    f"Trong {self.inst.pct_empty:.0f}%"
                )

                if self.inst.pct_grown >= 50:
                    self._harvest_cycle()
                elif self.inst.pct_empty >= 50:
                    self._plant_cycle()
                else:
                    self.inst.status = BotStatus.WAITING
                    sec     = self.inst.seconds_until_ready()
                    wait_ms = min(sec * 1000, 15_000) if sec > 0 else 10_000
                    self._log(f"Dang cho... Con {sec}s.")
                    self._sleep(wait_ms)

            except Exception as e:
                self._log(f"Loi vong lap: {e}")
                logger.exception(f"[Bot-{self.inst.id}] Loi:")
                self._sleep(5000)

        self.inst.status = BotStatus.STOPPED
