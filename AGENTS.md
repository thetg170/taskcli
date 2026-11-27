# Hướng dẫn cho AI Agent

- Đọc `BECADOC.md` trước khi sử dụng `taskcli`.
- Quy trình phát triển: tạo `feature/*` từ `develop`, commit và merge lại `develop`; giữ nguyên `main`. Khi được yêu cầu push, cập nhật cả hai remote `origin` (GitLab) và `old-origin` (GitHub).
- Khi người dùng yêu cầu báo cáo công việc, mặc định báo cáo theo sprint 2 tuần (mốc 23/11–04/12/2026), dùng mẫu **Báo cáo sprint theo dự án** trong `BECADOC.md`. Bắt đầu ngay bằng `Dự án 1: ...`, không có tiêu đề báo cáo hay tên nhân viên. Giữ nguyên tên task, đánh số từng task; sau tiêu đề dự án và sau danh sách task có một dòng trống, các trường còn lại xuống dòng sát nhau. Nếu sprint chưa kết thúc, chỉ ghi kết quả đã xác minh đến ngày hiện tại.
- Dùng tài khoản đang đăng nhập (`taskcli whoami`), khoảng ngày người dùng yêu cầu, dữ liệu task, chi tiết task và logtime thực tế; không cố định tên nhân viên hoặc ngày.
- Không tự suy đoán phần trăm, kết quả, vướng mắc hay deadline. Phân biệt kết quả đã xác minh và việc tiếp theo đề xuất. Nếu chưa có dữ liệu, ghi rõ chưa ghi nhận.
