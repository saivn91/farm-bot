# Templates - Huong dan chup anh

Cac file template duoc chup tu game chay tren LDPlayer **1280x720** (landscape, DPI 240).
Dat file vao thu muc nay (`templates/`) va dat ten dung nhu bang duoi.

---

## Danh sach template can chup

| Ten file | Mo ta | Ghi chu |
|---|---|---|
| `dat_ngang.png` | O dat trong - co duong ke ngang | Chup 1 o dat rieng le |
| `dat_doc.png` | O dat trong - co duong ke doc | Chup 1 o dat rieng le |
| `liem.png` | Icon luoi liem trong menu phu | Xuat hien khi tap vao o lua chin |
| `lua.png` | Icon hat lua trong menu phu | Xuat hien khi tap vao o dat trong |
| `lua_chin.png` | Lua da chin (tren cay) | Template nhan dien lua san sang gat |
| `kho_day.png` | Popup thong bao kho day | |
| `dong_x.png` | Nut X dong popup / cua so | Nut X nho goc tren phai |
| `cho.png` | Icon cua hang / cho | Tren thanh menu chinh |
| `thung_hang.png` | Thung hang chua ban trong cho | |
| `thung_ban.png` | Thung hang da ban xong | |
| `tao_rao_ban.png` | Nut "Tao rao ban" trong cua hang | |

---

## Huong dan chup template

1. Mo game tren LDPlayer o do phan giai **1280x720**
2. Chup anh man hinh (PrtSc hoac adb screencap)
3. Dung Paint / Snipping Tool cat chinh xac phan can lay
4. Luu vao thu muc `templates/` voi ten dung nhu bang tren
5. **Khong can resize** - chup o kich thuoc thuc tren man hinh 1280x720

## Them loai cay moi

Khi muon them cay (ngo, ca rot, ...):
1. Chup `ten_cay.png` (icon hat trong menu phu)
2. Chup `ten_cay_chin.png` (cay da chin)
3. Them vao `CropType` trong `core/models.py`
4. Bo sung `seed_template()` va `grown_template()` trong CropType
