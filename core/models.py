"""
Models: data classes va enums cho Farm Bot.
"""
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional
import time


# ── Crop types ────────────────────────────────────────────────────────────────

class CropType(IntEnum):
    LUA = 0
    # Them cac loai cay khac sau khi co template:
    # NGO       = 1   # ~5 phut
    # CA_ROT    = 2   # ~10 phut
    # DAU_TUONG = 3   # ~20 phut
    # MIA       = 4   # ~30 phut

    def label(self) -> str:
        _labels = {
            CropType.LUA: "Lua (2 phut)",
        }
        return _labels.get(self, self.name)

    def grow_seconds(self) -> int:
        _times = {
            CropType.LUA: 120,
        }
        return _times.get(self, 120)

    def seed_template(self) -> str:
        """Ten file template icon hat giong trong menu phu."""
        _seeds = {
            CropType.LUA: "lua.png",
        }
        return _seeds.get(self, "lua.png")

    def grown_template(self) -> str:
        """Ten file template cay da chin."""
        _grown = {
            CropType.LUA: "lua_chin.png",
        }
        return _grown.get(self, "lua_chin.png")


# ── Bot status ────────────────────────────────────────────────────────────────

class BotStatus:
    IDLE       = "IDLE"
    RUNNING    = "RUNNING"
    SCANNING   = "SCANNING"
    HARVESTING = "HARVESTING"
    PLANTING   = "PLANTING"
    SELLING    = "SELLING"
    WAITING    = "WAITING"
    ERROR      = "ERROR"
    STOPPED    = "STOPPED"


# ── Match result ──────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    found: bool  = False
    x:     int   = 0
    y:     int   = 0
    score: float = 0.0


# ── Farm region ───────────────────────────────────────────────────────────────

@dataclass
class FarmRegion:
    """Vung farm duoc dinh vi theo camera hien tai."""
    polygon:    list              # 4 dinh hinh thoi bao quanh vung farm [(x,y), ...]
    sweep_path: list              # tat ca o dat theo thu tu quet hang song song
    anchor:     tuple             # o dat giua farm - dung de tap mo menu phu
    cell_count: int               # so o dat detect duoc
    bbox:       tuple = (0, 0, 0, 0)   # (left, top, right, bottom) bounding box
    last_scan:  float = field(default_factory=time.time)


# ── Template thresholds ───────────────────────────────────────────────────────

@dataclass
class TemplateThresholds:
    """
    Nguong nhan dien (0.0 - 1.0) cho tung template.
    Gia tri nho = de match hon (dung cho anh kho detect nhu lua_chin).
    Gia tri lon = nghiem ngat hon (it nham hon).
    """
    dat_ngang:   float = 0.75
    dat_doc:     float = 0.75
    liem:        float = 0.75
    lua:         float = 0.75
    lua_chin:    float = 0.55   # lua chin kho detect hon, dung nguong thap hon
    kho_day:     float = 0.75
    dong_x:      float = 0.80
    cho:         float = 0.75
    thung_hang:  float = 0.75
    thung_ban:   float = 0.75
    tao_rao_ban: float = 0.80

    def get(self, tmpl_name: str) -> float:
        """Lay nguong theo ten file template (bo .png).
        Tra ve 0.75 neu khong co cai dat rieng."""
        key = tmpl_name.replace(".png", "").replace(".jpg", "")
        return getattr(self, key, 0.75)


# ── Stats ─────────────────────────────────────────────────────────────────────

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


# ── Bot instance ──────────────────────────────────────────────────────────────

@dataclass
class BotInstance:
    id:          int
    emu_index:   int       = 0
    adb_serial:  str       = ""
    adb_path:    str       = "adb"
    crop_mode:   CropType  = CropType.LUA
    enable_shop: bool      = True
    debug_mode:  bool      = True   # Luu anh debug khi True

    thresholds: TemplateThresholds = field(default_factory=TemplateThresholds)

    # Runtime state (khong luu config)
    farm_region:     Optional[FarmRegion] = None
    status:          str   = BotStatus.IDLE
    is_running:      bool  = False
    last_plant_time: float = 0.0
    pct_grown:       float = 0.0
    pct_empty:       float = 0.0

    stats: FarmStats = field(default_factory=FarmStats)
    logs:  list      = field(default_factory=list)

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
