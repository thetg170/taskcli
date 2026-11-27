# Hướng dẫn cho AI Agent

- Đọc `BECADOC.md` trước khi sử dụng `taskcli`.
- Quy trình phát triển: tạo `feature/*` từ `develop`, commit và merge lại `develop`; giữ nguyên `main`. Khi được yêu cầu push, cập nhật cả hai remote `origin` (GitLab) và `old-origin` (GitHub).
- Khi người dùng yêu cầu báo cáo công việc tuần, luôn dùng mẫu ở mục **Báo cáo tuần theo dự án** trong `BECADOC.md`, trừ khi người dùng yêu cầu định dạng khác. Task phải đánh số, các trường còn lại xuống dòng sát nhau, không chèn dòng trống giữa chúng.
- Dùng tài khoản đang đăng nhập (`taskcli whoami`), khoảng ngày người dùng yêu cầu, dữ liệu task, chi tiết task và logtime thực tế; không cố định tên nhân viên hoặc ngày.
- Không tự suy đoán phần trăm, kết quả, vướng mắc hay deadline. Phân biệt kết quả đã xác minh và việc tiếp theo đề xuất. Nếu chưa có dữ liệu, ghi rõ chưa ghi nhận.
