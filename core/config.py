"""
Config manager - luu va doc cai dat bot bang JSON.
"""
import os
import json
import logging
from dataclasses import asdict
from typing import List

from core.models import BotInstance, CropType, TemplateThresholds

logger = logging.getLogger(__name__)

CFG_DIR  = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FarmBot")
CFG_FILE = os.path.join(CFG_DIR, "config.json")

DEFAULT_SETTINGS = {
    "adb_path":       "adb",
    "tesseract_path": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "num_instances":  1,
    "theme":          "dark",
}

def _thresholds_to_dict(th: TemplateThresholds) -> dict:
    return asdict(th)

def _thresholds_from_dict(d: dict) -> TemplateThresholds:
    defaults = asdict(TemplateThresholds())
    merged   = {k: float(d.get(k, defaults[k])) for k in defaults}
    return TemplateThresholds(**merged)

def save(instances: List[BotInstance], settings: dict) -> None:
    os.makedirs(CFG_DIR, exist_ok=True)
    data = {
        "settings": {k: settings.get(k, v) for k, v in DEFAULT_SETTINGS.items()},
        "instances": [
            {
                "id":             inst.id,
                "name":           inst.name,
                "emu_index":      inst.emu_index,
                "adb_serial":     inst.adb_serial,
                "adb_path":       inst.adb_path,
                "tesseract_path": inst.tesseract_path,
                "crop_mode":      int(inst.crop_mode),
                "enable_shop":    inst.enable_shop,
                "debug_mode":     inst.debug_mode,
                "thresholds":     _thresholds_to_dict(inst.thresholds),
            }
            for inst in instances
        ],
    }
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Config da luu: {CFG_FILE}")
    except Exception as e:
        logger.error(f"Luu config that bai: {e}")

def load() -> tuple[List[BotInstance], dict]:
    settings = dict(DEFAULT_SETTINGS)

    if not os.path.exists(CFG_FILE):
        return [BotInstance(id=0)], settings

    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Doc config that bai: {e}")
        return [BotInstance(id=0)], settings

    settings.update(data.get("settings", {}))

    instances: List[BotInstance] = []
    for d in data.get("instances", []):
        try:
            th_dict = d.get("thresholds", {})
            inst = BotInstance(
                id             = int(d.get("id", 0)),
                name           = str(d.get("name", "")),
                emu_index      = int(d.get("emu_index", 0)),
                adb_serial     = str(d.get("adb_serial", "")),
                adb_path       = str(d.get("adb_path", settings["adb_path"])),
                tesseract_path = str(d.get("tesseract_path", settings.get("tesseract_path", r"C:\Program Files\Tesseract-OCR\tesseract.exe"))),
                crop_mode      = CropType(int(d.get("crop_mode", 0))),
                enable_shop    = bool(d.get("enable_shop", True)),
                debug_mode     = bool(d.get("debug_mode", True)),
                thresholds     = _thresholds_from_dict(th_dict),
            )
            instances.append(inst)
        except Exception as e:
            logger.warning(f"Bo qua instance loi: {e}")

    if not instances:
        instances = [BotInstance(id=0)]

    return instances, settings