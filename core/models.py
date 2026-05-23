"""
Models: data classes và enums cho Farm Bot.
"""
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
import time

class CropType(IntEnum):
    LUA = 0
    # Them cac loai cay khac sau khi co template:
    # NGO       = 1   # ~5 phut
    # CA_ROT    = 2   # ~10 phut
    # DAU_TUONG = 3   # ~20 phut
    # MIA       = 4   # ~30 phut

    def label(self) -> str:
        _labels = {CropType.LUA: "Lúa (2 phút)"}
        return _labels.get(self, self.name)

    def grow_seconds(self) -> int:
        _times = {CropType.LUA: 120}
        return _times.get(self, 120)

    def seed_template(self) -> str:
        _seeds = {CropType.LUA: "lua_hat_giong.png"}
        return _seeds.get(self, "lua_hat_giong.png")

    def grown_template(self) -> str:
        _grown = {CropType.LUA: "lua_thu_hoach.png"}
        return _grown.get(self, "lua_thu_hoach.png")

    def storage_template(self) -> str:
        _storage = {CropType.LUA: "lua_kho.png"}
        return _storage.get(self, "lua_kho.png")

class BotStatus:
    IDLE       = "ĐANG NGHỈ"
    RUNNING    = "ĐANG CHẠY"
    SCANNING   = "ĐANG QUÉT MÀN HÌNH"
    HARVESTING = "ĐANG THU HOẠCH"
    PLANTING   = "ĐANG GIEO HẠT"
    SELLING    = "ĐANG BÁN HÀNG"
    WAITING    = "ĐANG CHỜ CÂY CHÍN"
    ERROR      = "LỖI HỆ THỐNG"
    STOPPED    = "ĐÃ DỪNG"

@dataclass
class MatchResult:
    found: bool  = False
    x:     int   = 0
    y:     int   = 0
    score: float = 0.0

@dataclass
class FarmRegion:
    polygon:    list              
    sweep_path: list              
    anchor:     tuple             
    cell_count: int               
    bbox:       tuple = (0, 0, 0, 0)   
    last_scan:  float = field(default_factory=time.time)

@dataclass
class TemplateThresholds:
    dat_ngang:     float = 0.75
    dat_doc:       float = 0.75
    liem:          float = 0.75
    lua_hat_giong: float = 0.75
    lua_thu_hoach: float = 0.55   
    kho_day:       float = 0.65
    
    # --- Su dung 2 nut dong_x va ha nguong xuong 0.6 ---
    dong_x:        float = 0.60
    dong_x_2:      float = 0.60
    dong_x_3:      float = 0.60
    
    cua_hang:      float = 0.75
    thung_trong:   float = 0.75
    thung_da_ban:  float = 0.75
    tao_rao_ban:   float = 0.60
    # --- Cac nguong cho viec ban hang ---
    kho_nong_san_shop: float = 0.70
    lua_kho:           float = 0.70
    mui_ten_phai:      float = 0.70
    quang_cao_ngay:    float = 0.65
    nut_tick_dang_bao: float = 0.65
    het_hom_do:        float = 0.75
    icon_game:         float = 0.70

    def get(self, tmpl_name: str) -> float:
        key = tmpl_name.replace(".png", "").replace(".jpg", "")
        return getattr(self, key, 0.75)

@dataclass
class FarmStats:
    total_harvest: int   = 0
    total_cycles:  int   = 0
    session_start: float = field(default_factory=time.time)

    def session_duration(self) -> str:
        elapsed = time.time() - self.session_start
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

@dataclass
class BotInstance:
    id:          int
    emu_index:   int       = 0
    name:        str       = ""
    adb_serial:  str       = ""
    adb_path:    str       = "adb"
    tesseract_path: str    = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    
    crop_mode:   CropType  = CropType.LUA
    enable_shop: bool      = True
    debug_mode:  bool      = False

    thresholds: TemplateThresholds = field(default_factory=TemplateThresholds)

    farm_region:     Optional[FarmRegion] = None
    status:          str   = BotStatus.IDLE
    is_running:      bool  = False
    max_cells:       int   = 0 
    
    last_plant_time: float = 0.0
    pct_grown:       float = 0.0
    pct_empty:       float = 0.0

    stats: FarmStats = field(default_factory=FarmStats)
    logs:  list      = field(default_factory=list)

    def get_display_name(self) -> str:
        if self.name.strip():
            return self.name.strip()
        return f"LDPlayer-{self.emu_index}" if self.emu_index > 0 else "LDPlayer"

    def seconds_until_ready(self) -> int:
        if self.last_plant_time == 0:
            return 0
        remaining = self.crop_mode.grow_seconds() - (time.time() - self.last_plant_time)
        return max(0, int(remaining))

    def crop_ready(self) -> bool:
        if self.last_plant_time == 0:
            return False
        return (time.time() - self.last_plant_time) >= self.crop_mode.grow_seconds()

    def add_log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] {msg}")
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]