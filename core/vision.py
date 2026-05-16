"""
Vision module - nhan dien template, o dat, cay trong.
Tat ca template dung ten tieng Viet khong dau.
Do phan giai chuan: 1280x720 (landscape), DPI 240.
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

# Threshold mac dinh toan cuc (dung khi khong co TemplateThresholds cu the)
_DEFAULT = TemplateThresholds()


# ── Template loading ──────────────────────────────────────────────────────────

def _load(name: str) -> Optional[np.ndarray]:
    path = os.path.join(TMPL_DIR, name)
    if not os.path.exists(path):
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
        logger.warning(f"Template {name} ({tw}x{th_h}) lon hon man hinh ({sw}x{sh}).")
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
) -> list[MatchResult]:
    """
    Tim tat ca vi tri khop, loai tru cac diem qua gan nhau.
    - thresh: neu truyen vao thi dung gia tri nay
    - neu khong, lay tu th.get(name)
    """
    threshold = thresh if thresh is not None else th.get(name)
    tmpl = _load(name)
    if tmpl is None or screen is None:
        return []

    th_h, tw = tmpl.shape[:2]
    sh, sw = screen.shape[:2]
    if th_h > sh or tw > sw:
        return []

    gray_s = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    gray_t = cv2.cvtColor(tmpl,   cv2.COLOR_BGR2GRAY)
    result = cv2.matchTemplate(gray_s, gray_t, cv2.TM_CCOEFF_NORMED)

    locs = np.where(result >= threshold)
    matches: list[MatchResult] = []
    used:    list[tuple[int, int]] = []

    for px, py in zip(*locs[::-1]):
        if any(abs(px - ux) < min_dist and abs(py - uy) < min_dist for ux, uy in used):
            continue
        matches.append(MatchResult(
            found=True,
            x=int(px) + tw // 2,
            y=int(py) + th_h // 2,
            score=float(result[py, px]),
        ))
        used.append((int(px), int(py)))

    return matches


# ── Farm-specific detection ───────────────────────────────────────────────────

def find_soil_cells(
    screen: np.ndarray,
    th:     TemplateThresholds = _DEFAULT,
) -> list[MatchResult]:
    """
    Nhan dien cac o dat (dat_ngang + dat_doc).
    Loai tru trung lap giua 2 mau.
    """
    cells: list[MatchResult] = []
    for tmpl_name in SOIL_TEMPLATES:
        cells.extend(find_all(screen, tmpl_name, th=th, min_dist=30))

    deduped: list[MatchResult] = []
    for c in cells:
        if not any(abs(c.x - d.x) < 30 and abs(c.y - d.y) < 30 for d in deduped):
            deduped.append(c)
    return deduped


def find_grown_crops(
    screen:    np.ndarray,
    tmpl_name: str,
    th:        TemplateThresholds = _DEFAULT,
) -> list[MatchResult]:
    """Nhan dien cay da chin theo template tuong ung."""
    return find_all(screen, tmpl_name, th=th, min_dist=30)


# ── Sweep path builders ───────────────────────────────────────────────────────

def build_sweep_path(cells: list[MatchResult], row_tol: int = 25) -> list[tuple[int, int]]:
    """Sap xep cac o dat thanh lo trinh zigzag theo hang."""
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
    """
    Chi lay diem dau va cuoi moi hang.
    Giam so lenh ADB: 1 swipe = 1 hang thay vi 1 swipe = 1 o.
    """
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
    pt_spacing: int = 25,
) -> list[tuple[int, int]]:
    """
    Tao lo trinh quet theo truc Isometric cua farm.
    Chuyen doi toa do man hinh sang khong gian phẳng, chia dong deu tắp 
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
        if ix - row_centers[-1] > 30: # 30 là ngưỡng tách hàng an toàn
            row_centers.append(ix)

    num_rows = max(3, len(row_centers))

    path: list[tuple[int, int]] = []

    # Thu gọn 2 đầu một chút (padding) để không click ra ngoài phạm vi đất
    pad_y = 15
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
    """Tinh polygon hinh thoi bao quanh vung farm."""
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
    """Tinh bounding box HINH CHU NHAT bao quanh vung farm. (left, top, right, bottom)"""
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
    """Ve annotation debug len anh man hinh, tra ve ban copy."""
    out = screen.copy()

    # Vung farm (hinh thoi mau do)
    if polygon and len(polygon) == 4:
        pts = np.array(polygon, np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [pts], isClosed=True, color=(0, 0, 255), thickness=2)

    # Cac o dat (hinh vuong mau vang)
    if cells:
        for c in cells:
            cv2.rectangle(out, (c.x - 15, c.y - 15), (c.x + 15, c.y + 15),
                          (0, 220, 220), 1)

    # Cay chin (hinh tron mau xanh la)
    if grown:
        for g in grown:
            cv2.circle(out, (g.x, g.y), 12, (0, 200, 0), 2)

    # Diem anchor (mau cam)
    if anchor:
        cv2.circle(out, anchor, 8, (0, 140, 255), -1)
        cv2.putText(out, "Anchor", (anchor[0] + 10, anchor[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 140, 255), 1)

    # Icon tool (mau xanh la, khung vuong lon)
    if tool_pt:
        cv2.rectangle(out,
                      (tool_pt[0] - 28, tool_pt[1] - 28),
                      (tool_pt[0] + 28, tool_pt[1] + 28),
                      (0, 255, 80), 2)
        cv2.putText(out, "Tool", (tool_pt[0] - 18, tool_pt[1] - 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 80), 1)

    # Lo trinh keo (mau vang)
    if path and len(path) > 1:
        for i in range(len(path) - 1):
            cv2.line(out, path[i], path[i + 1], (0, 230, 230), 2)
        cv2.circle(out, path[0],  6, (0, 230, 230), -1)
        cv2.circle(out, path[-1], 6, (0,   80, 255), -1)

    # Label
    if label:
        cv2.putText(out, label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    return out


def save_debug(img: np.ndarray, step_name: str, inst_id: int = 0) -> str:
    """Luu anh debug vao thu muc debug_images/. Tra ve duong dan da luu."""
    import time as _time
    folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug_images")
    os.makedirs(folder, exist_ok=True)
    ts   = int(_time.time() * 1000)
    path = os.path.join(folder, f"bot{inst_id}_{step_name}_{ts}.png")
    cv2.imwrite(path, img)
    return path
