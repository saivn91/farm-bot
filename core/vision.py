"""
Vision module - nhan dien template, o dat, cay trong.
Tich hop AI Đa Tỷ Lệ (Multi-Scale) + Thuật toán Isometric + Cắt viền.
"""
import cv2
import numpy as np
import os
import logging
from typing import Optional

from core.models import MatchResult, TemplateThresholds

logger = logging.getLogger(__name__)

TMPL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

SOIL_TEMPLATES = ["dat_ngang.png", "dat_doc.png"]

# Threshold mac dinh toan cuc
_DEFAULT = TemplateThresholds()


# ── Helpers ───────────────────────────────────────────────────────────────────

def apply_margins(screen: np.ndarray, margin_pct: float = 0.0) -> tuple[np.ndarray, int, int]:
    """Cat vien anh de tranh nhan dien nham UI o cac mep man hinh."""
    if margin_pct <= 0:
        return screen, 0, 0
    h, w = screen.shape[:2]
    mx, my = int(w * margin_pct), int(h * margin_pct)
    return screen[my:h - my, mx:w - mx], mx, my


# ── Template loading ──────────────────────────────────────────────────────────

def _load(name: str) -> Optional[np.ndarray]:
    path = os.path.join(TMPL_DIR, name)
    if not os.path.exists(path):
        fallback_path = path.replace('.png', '.jpg')
        if os.path.exists(fallback_path):
            path = fallback_path
        else:
            logger.warning(f"Template khong ton tai: {path}")
            return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        logger.warning(f"Khong doc duoc template: {path}")
    return img


# ── Core matching ─────────────────────────────────────────────────────────────

def find_one(
    screen: np.ndarray,
    name:   str,
    thresh: Optional[float] = None,
    th:     TemplateThresholds = _DEFAULT,
) -> MatchResult:
    """
    Tim 1 ket qua khop tot nhat.
    - thresh: neu truyen vao thi dung gia tri nay
    - neu khong, lay tu th.get(name)
    """
    threshold = thresh if thresh is not None else th.get(name)
    tmpl = _load(name)
    if tmpl is None or screen is None:
        return MatchResult()

    th_h, tw = tmpl.shape[:2]
    sh, sw = screen.shape[:2]
    if th_h > sh or tw > sw:
        return MatchResult()

    result = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
    _, val, _, loc = cv2.minMaxLoc(result)

    if val >= threshold:
        return MatchResult(
            found=True,
            x=loc[0] + tw // 2,
            y=loc[1] + th_h // 2,
            score=float(val),
        )
    return MatchResult(score=float(val))


def find_all(
    screen:   np.ndarray,
    name:     str,
    thresh:   Optional[float] = None,
    th:       TemplateThresholds = _DEFAULT,
    min_dist: int = 30,
    margin_pct: float = 0.0,
) -> list[MatchResult]:
    """Dò tìm tất cả kết quả cho các item tĩnh (không bị zoom) như liềm, hạt, UI."""
    threshold = thresh if thresh is not None else th.get(name)
    tmpl = _load(name)
    if tmpl is None or screen is None:
        return []

    src, ox, oy = apply_margins(screen, margin_pct)
    th_h, tw = tmpl.shape[:2]
    if th_h > src.shape[0] or tw > src.shape[1]:
        return []

    gray_s = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    gray_t = cv2.cvtColor(tmpl,   cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(gray_s, gray_t, cv2.TM_CCOEFF_NORMED)

    locs = np.where(result >= threshold)
    all_matches = []
    
    for px, py in zip(*locs[::-1]):
        all_matches.append(MatchResult(
            found=True,
            x=int(px) + tw // 2 + ox,
            y=int(py) + th_h // 2 + oy,
            score=float(result[py, px]),
        ))
        
    all_matches.sort(key=lambda m: m.score, reverse=True)

    matches: list[MatchResult] = []
    for match in all_matches:
        if not any(abs(match.x - v.x) < min_dist and abs(match.y - v.y) < min_dist for v in matches):
            matches.append(match)

    return matches


# ── Farm-specific detection (Multi-Scale) ─────────────────────────────────────

def find_soil_cells(
    screen: np.ndarray,
    th:     TemplateThresholds = _DEFAULT,
    margin_pct: float = 0.05,
) -> list[MatchResult]:
    """
    Nhan dien o dat bang AI Da Ty Le (Multi-Scale Template Matching).
    Bat chap camera bi zoom to hay thu nho.
    """
    if screen is None: return []
    src, ox, oy = apply_margins(screen, margin_pct)
    src_gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    
    all_matches = []
    
    # Quet da ty le tu 60% den 140%
    scales = np.linspace(0.6, 1.4, 15)
    
    for tmpl_name in SOIL_TEMPLATES:
        threshold = th.get(tmpl_name)
        tmpl = _load(tmpl_name)
        if tmpl is None: continue
        
        tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
        
        for scale in scales:
            width = int(tmpl_gray.shape[1] * scale)
            height = int(tmpl_gray.shape[0] * scale)
            if width < 10 or height < 10:
                continue
                
            resized_template = cv2.resize(tmpl_gray, (width, height))
            if resized_template.shape[0] > src_gray.shape[0] or resized_template.shape[1] > src_gray.shape[1]:
                continue
                
            result = cv2.matchTemplate(src_gray, resized_template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            
            for px, py in zip(*locations[::-1]):
                all_matches.append(MatchResult(
                    found=True,
                    x=int(px) + width // 2 + ox,   # Tinh tam o dat theo template da resize
                    y=int(py) + height // 2 + oy,
                    score=float(result[py, px])
                ))
            
    # Sap xep diem tin cay tu cao xuong thap
    all_matches.sort(key=lambda m: m.score, reverse=True)
    
    # Khu trung lap (Non-Maximum Suppression)
    valid_matches: list[MatchResult] = []
    min_dist_sq = 30 ** 2 
    
    for match in all_matches:
        overlap = False
        for v in valid_matches:
            dist_sq = (match.x - v.x)**2 + (match.y - v.y)**2
            if dist_sq < min_dist_sq:
                overlap = True
                break
        if not overlap:
            valid_matches.append(match)
            
    return valid_matches


def find_grown_crops(
    screen:    np.ndarray,
    tmpl_name: str,
    th:        TemplateThresholds = _DEFAULT,
) -> list[MatchResult]:
    """Nhan dien cay da chin co ap dung margin 5%."""
    # Co the nang cap ham nay thanh Multi-scale neu cay chin cung bi zoom
    return find_all(screen, tmpl_name, th=th, min_dist=30, margin_pct=0.05)


# ── Sweep path builders (Isometric) ───────────────────────────────────────────

def build_sweep_path(cells: list[MatchResult], row_tol: int = 25) -> list[tuple[int, int]]:
    """Ham fallback sap xep co ban."""
    if not cells:
        return []

    pts = sorted([(c.x, c.y) for c in cells], key=lambda p: p[1])
    rows: list[list[tuple[int, int]]] = []
    row: list[tuple[int, int]] = [pts[0]]
    for pt in pts[1:]:
        if abs(pt[1] - row[0][1]) <= row_tol:
            row.append(pt)
        else:
            rows.append(row)
            row = [pt]
    rows.append(row)

    path: list[tuple[int, int]] = []
    for i, r in enumerate(rows):
        path.extend(sorted(r, key=lambda p: p[0], reverse=(i % 2 == 1)))
    return path


def build_row_waypoints(
    sweep_path: list[tuple[int, int]],
    row_tol:    int = 25,
) -> list[tuple[int, int]]:
    """Lay diem dau va cuoi moi hang (fallback)."""
    if not sweep_path:
        return []

    pts = sorted(sweep_path, key=lambda p: p[1])
    rows: list[list[tuple[int, int]]] = []
    row: list[tuple[int, int]] = [pts[0]]
    for pt in pts[1:]:
        if abs(pt[1] - row[0][1]) <= row_tol:
            row.append(pt)
        else:
            rows.append(row)
            row = [pt]
    rows.append(row)

    waypoints: list[tuple[int, int]] = []
    for i, r in enumerate(rows):
        sr = sorted(r, key=lambda p: p[0], reverse=(i % 2 == 1))
        waypoints.append(sr[0])
        if len(sr) > 1:
            waypoints.append(sr[-1])
    return waypoints


def build_farm_sweep(
    cells: list[MatchResult],
    row_tol: int = 25,
    pt_spacing: int = 35,
) -> list[tuple[int, int]]:
    """
    Tao lo trinh quet theo truc Isometric cua farm.
    Chuyen doi toa do man hinh sang khong gian phang, chia dong deu tap 
    sau do chuyen nguoc lai de dam bao luon song song voi cac o dat.
    """
    if not cells:
        return []

    # 1. Tìm tâm của toàn bộ vùng nhận diện
    xs = [c.x for c in cells]
    ys = [c.y for c in cells]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    # 2. Chuyển đổi tọa độ màn hình sang tọa độ Isometric
    iso_pts = []
    for c in cells:
        px = c.x - cx
        py = c.y - cy
        iso_x = px / 2.0 + py
        iso_y = -px / 2.0 + py
        iso_pts.append((iso_x, iso_y))

    # 3. Lấy bounding box trong không gian Isometric (tạo thành hình chữ nhật bao quanh farm)
    min_ix = min(p[0] for p in iso_pts)
    max_ix = max(p[0] for p in iso_pts)
    min_iy = min(p[1] for p in iso_pts)
    max_iy = max(p[1] for p in iso_pts)

    # 4. Gom nhóm tính toán số lượng hàng thực tế
    sorted_ix = sorted([p[0] for p in iso_pts])
    row_centers = [sorted_ix[0]]
    for ix in sorted_ix[1:]:
        if ix - row_centers[-1] > 30:
            row_centers.append(ix)

    num_rows = max(3, len(row_centers))
    path: list[tuple[int, int]] = []

    # --- ĐÃ CHỈNH SỬA: Đưa padding về 0 để không bị thu hẹp lộ trình ---
    pad_y = 0
    start_iy = min_iy + pad_y
    end_iy = max_iy - pad_y

    for i in range(num_rows):
        # Tọa độ X (iso_x) của hàng hiện tại
        t = i / max(num_rows - 1, 1)
        ix = min_ix + t * (max_ix - min_ix)

        # Hàm nội suy tọa độ màn hình từ Isometric
        def to_scr(ix_val, iy_val):
            px = ix_val - iy_val
            py = (ix_val + iy_val) / 2.0
            return (int(cx + px), int(cy + py))

        # Sinh các điểm liền kề dọc theo hàng để ADB vuốt mượt mà
        row_pts = []
        width_iso = max(10, end_iy - start_iy)
        n_cols = max(2, int(width_iso / pt_spacing) + 1)

        for j in range(n_cols):
            f = j / max(n_cols - 1, 1)
            iy = start_iy + f * (end_iy - start_iy)
            row_pts.append(to_scr(ix, iy))

        # Nối zigzag: Hàng chẵn quét thuận, hàng lẻ quét ngược
        if i % 2 == 0:
            path.extend(row_pts)
        else:
            path.extend(reversed(row_pts))

    return path


# ── Polygon / BBox ────────────────────────────────────────────────────────────

def compute_polygon(cells: list[MatchResult], pad: int = 40) -> list[tuple[int, int]]:
    if not cells: return []
    xs = [c.x for c in cells]
    ys = [c.y for c in cells]
    lx, rx = min(xs), max(xs)
    ty, by = min(ys), max(ys)
    cx = (lx + rx) // 2
    cy = (ty + by) // 2
    return [
        (cx,       ty - pad),
        (rx + pad, cy),
        (cx,       by + pad),
        (lx - pad, cy),
    ]


def compute_bbox(
    cells: list[MatchResult],
    pad: int = 50,
) -> tuple[int, int, int, int]:
    if not cells: return (0, 0, 0, 0)
    xs = [c.x for c in cells]
    ys = [c.y for c in cells]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


# ── Debug drawing ─────────────────────────────────────────────────────────────

def draw_debug(
    screen:   np.ndarray,
    polygon:  Optional[list]         = None,
    anchor:   Optional[tuple]        = None,
    cells:    Optional[list]         = None,
    grown:    Optional[list]         = None,
    tool_pt:  Optional[tuple]        = None,
    path:     Optional[list]         = None,
    label:    str                    = "",
) -> np.ndarray:
    out = screen.copy()

    if polygon and len(polygon) == 4:
        pts = np.array(polygon, np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [pts], isClosed=True, color=(0, 0, 255), thickness=2)

    if cells:
        for c in cells:
            cv2.rectangle(out, (c.x - 15, c.y - 15), (c.x + 15, c.y + 15),
                          (0, 220, 220), 1)

    if grown:
        for g in grown:
            cv2.circle(out, (g.x, g.y), 12, (0, 200, 0), 2)

    if anchor:
        cv2.circle(out, anchor, 8, (0, 140, 255), -1)
        cv2.putText(out, "Anchor", (anchor[0] + 10, anchor[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)

    if tool_pt:
        cv2.rectangle(out,
                      (tool_pt[0] - 28, tool_pt[1] - 28),
                      (tool_pt[0] + 28, tool_pt[1] + 28),
                      (0, 255, 80), 2)
        cv2.putText(out, "Tool", (tool_pt[0] - 18, tool_pt[1] - 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 80), 1)

    if path and len(path) > 1:
        for i in range(len(path) - 1):
            cv2.line(out, path[i], path[i + 1], (0, 230, 230), 2)
        cv2.circle(out, path[0],  6, (0, 230, 230), -1)
        cv2.circle(out, path[-1], 6, (0,   80, 255), -1)

    if label:
        cv2.putText(out, label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    return out


def save_debug(img: np.ndarray, step_name: str, inst_id: int = 0) -> str:
    import time as _time
    folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug_images")
    os.makedirs(folder, exist_ok=True)
    ts   = int(_time.time() * 1000)
    path = os.path.join(folder, f"bot{inst_id}_{step_name}_{ts}.png")
    cv2.imwrite(path, img)
    return path