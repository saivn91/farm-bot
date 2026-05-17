import cv2
import numpy as np
import os

from core.vision import build_farm_sweep

class CropDetectionTesterHSV:
    def check_lua_chin(self, image_path: str):
        print(f"\n{'='*50}")
        print(f" ĐANG KIỂM TRA ẢNH: {image_path}")
        print(f"{'='*50}")
        
        screen = cv2.imread(image_path)
        if screen is None:
            print("Lỗi: Không đọc được ảnh. Hãy kiểm tra lại tên file!")
            return

        # 1. Áp dụng hệ màu HSV với dải màu VÀNG ÓNG (loại bỏ xanh lá của cỏ)
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        
        # Đã bóp chặt dải màu: Hue từ 18-33 (Vàng nguyên bản), Saturation > 120, Value > 150
        lower_yellow = np.array([18, 120, 150])
        upper_yellow = np.array([33, 255, 255])
        
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        # 2. Xóa nhiễu và làm đặc nét
        kernel = np.ones((5,5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.dilate(mask, kernel, iterations=3)
        
        # 3. Tìm vùng màu
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            print(" -> KHÔNG TÌM THẤY VÙNG MÀU VÀNG NÀO!")
            # Lưu ảnh mask ra xem thử nó có lọc sạch quá không
            cv2.imwrite(f"TEST_MASK_{os.path.basename(image_path)}", mask)
            return

        # 4. Lọc lấy vùng Lớn Nhất (Ruộng lúa thật)
        best_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(best_contour)
        print(f"[1] Vùng lúa lớn nhất có diện tích: {area:.0f} pixel")
        
        if area < 400:
            print(" -> Vùng lúa quá nhỏ (nhiễu), bỏ qua.")
            return

        # 5. TÍNH TRUNG BÌNH MÀU (Tâm / Centroid) của khối hình học
        M = cv2.moments(best_contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            x, y, w, h = cv2.boundingRect(best_contour)
            cx, cy = x + w//2, y + h//2
            
        print(f"[2] Tính toán tâm thu hoạch (Anchor): ({cx}, {cy})")
        
        # 6. Tạo lưới lộ trình gặt kéo lưới bao trọn ruộng lúa
        x, y, w, h = cv2.boundingRect(best_contour)
        mock_cells = []
        class MockCell:
            def __init__(self, px, py):
                self.x, self.y = px, py
        
        for py in range(y + 15, y + h, 35):
            for px in range(x + 15, x + w, 35):
                if cv2.pointPolygonTest(best_contour, (px, py), False) >= 0:
                    mock_cells.append(MockCell(px, py))
                    
        print(f"[3] Tạo lộ trình gặt gồm {len(mock_cells)} điểm bám quanh Contour.")

        # 7. Vẽ trực quan để bạn đánh giá kết quả
        out_img = screen.copy()
        cv2.drawContours(out_img, [best_contour], -1, (0, 255, 0), 3) # Vẽ viền xanh quanh ruộng
        cv2.circle(out_img, (cx, cy), 10, (0, 140, 255), -1) # Vẽ Tâm màu cam
        for c in mock_cells:
            cv2.circle(out_img, (c.x, c.y), 4, (0, 255, 255), -1) # Vẽ các điểm tạo đường gặt
            
        out_path = f"TEST_HSV_RESULT_{os.path.basename(image_path)}"
        cv2.imwrite(out_path, out_img)
        print(f"[4] XUẤT ẢNH THÀNH CÔNG: Mời bạn mở file '{out_path}' lên để kiểm tra!")

if __name__ == "__main__":
    tester = CropDetectionTesterHSV()
    test_image = "test_anh_lua_chin.png" # Nhập đúng tên ảnh của bạn
    if os.path.exists(test_image):
        tester.check_lua_chin(test_image)
    else:
        print(f"Hãy đưa ảnh '{test_image}' vào cùng thư mục để test nhé!")