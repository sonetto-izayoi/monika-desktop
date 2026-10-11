MONIKA VPET DESKTOP — MAS AUTOSTART (BETA)

CÀI ĐẶT
1. Đóng MAS.
2. Chép cả thư mục “monika vpet” vào: Doki Doki Literature Club/game/Submods/
   Nếu thư mục Submods chưa có, tạo nó. Giữ nguyên tên thư mục và không chỉ chép riêng file .rpy.
3. Cài Python 3 64-bit từ python.org nếu máy chưa có. Trong lúc cài, bật “Add Python to PATH”.
4. Mở CMD trong thư mục “game/Submods/monika vpet” và chạy:
   python -m pip install PySide6 google-genai
5. Mở monika_config.json bằng Notepad, dán Gemini API key vào giá trị gemini_api_key, lưu file.
   Ví dụ: {"gemini_api_key": "DAN_API_KEY_CUA_BAN_VAO_DAY"}
6. Mở MAS. Pet sẽ tự bật và hiện lời chào ngẫu nhiên; double-click vào chibi để mở/ẩn khung chat; kéo chibi để di chuyển; chuột phải để mở menu.
7. Phím tắt toàn hệ thống: Ctrl+Alt+M để ẩn/mở lại Monika. Trong menu chuột phải, chọn “Ẩn Monika” nếu muốn ẩn tạm thời; “Thoát hẳn Monika” sẽ kết thúc chương trình và phím tắt không thể mở lại cho đến khi MAS khởi chạy pet lần nữa.

ẢNH CHIBI
Đặt ảnh PNG nền trong suốt cùng thư mục với monika_desktop.py và đặt tên:
- monika.png (bình thường)
- happy.png (vui)
- thinking.png (đang suy nghĩ)
Nếu chưa có ảnh, chương trình sẽ hiện biểu tượng Monika thay thế.

LƯU Ý
- Cần Python và các thư viện trên máy.
- Nếu tự động mở không hoạt động, đặt biến môi trường MONIKA_PYTHONW trỏ đến đường dẫn đầy đủ của pythonw.exe, ví dụ C:\Users\TEN\AppData\Local\Programs\Python\Python312\pythonw.exe.
- Nếu API key từng bị ghi trực tiếp trong code hoặc gửi qua chat, hãy thu hồi key đó trong Google AI Studio và tạo key mới. Chỉ lưu key mới trên máy của bạn.
- Launcher hiện truyền PID của MAS cho desktop pet và theo dõi tiến trình này; khi MAS đóng hoặc crash, pet sẽ tự thoát. Quit callback của Ren'Py cũng được giữ làm phương án dự phòng.


DEBUG IF AUTO-START DOES NOT WORK
Open game/monika_vpet_autostart.log and game/monika_vpet_desktop.log after launching MAS. These logs are created by the updated launcher and can show whether MAS found the script/Python and why the desktop process failed.

Launcher update: if this MAS/Ren'Py build rejects the child environment, the launcher now retries starting the desktop without an explicit environment mapping.
