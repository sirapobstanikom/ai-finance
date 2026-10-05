# AI_VI

ระบบวิจัยปัจจัยพื้นฐานส่วนบุคคล ระยะ MVP รับไฟล์ที่วางเอง สร้างความรู้และ investment thesis แล้วตอบคำถามจากส่วนที่เกี่ยวข้อง ตัวเลขที่เปลี่ยนถูกจับด้วยโค้ด

ค่าเริ่มต้นใช้ SQLite เพื่อให้รันบนเครื่องนี้ได้ทันที ถ้าต้องการ Postgres ให้เปิด `docker compose up -d` แล้วตั้ง `DATABASE_URL` ใน `.env`

## เริ่มใช้

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m uvicorn aivi.main:create_app --factory --host 127.0.0.1 --port 8000
```

เปิด http://127.0.0.1:8000 แล้วเข้าสู่ระบบ ค่าเริ่มต้นสำหรับเครื่องพัฒนาคือ
`admin` / `1234` เปลี่ยน `ADMIN_USERNAME`, `ADMIN_PASSWORD` และ
`SESSION_SECRET` ใน `.env` ก่อนเปิดให้เครื่องอื่นเข้าถึง

หน้าหลักแยกเป็น:

- `/chat` เลือกหุ้นแล้วถาม AI
- `/set-fetch` กดดึงข้อมูลจาก SET และตรวจซ้ำด้วย hash
- `/company-data` รวม snapshot จาก SET, metric, knowledge และเอกสารรายบริษัท

รายการ endpoint อยู่ที่ http://127.0.0.1:8000/docs

แก้ `API_TOKEN` ใน `.env` ก่อนเรียก API ตั้ง `GEMINI_API_KEY` เมื่อต้องการให้คำถามที่ต้องให้เหตุผลเรียกโมเดล บัญชีแชท Pro ไม่ถูกเรียกจากโปรเซสนี้

การดึงข้อมูล SET ใช้ API ทางการซึ่งต้องสมัคร data product และใส่
`SET_API_KEY` ใน `.env` ระบบรองรับ security profile และ delayed quote
โดยไม่พยายามข้ามระบบสิทธิ์ของเว็บไซต์ ถ้ากดซ้ำและ JSON เหมือนเดิม
ระบบคืนสถานะว่าเป็นข้อมูลซ้ำและไม่สร้าง snapshot ใหม่

## เส้นทางหลัก

- `POST /companies` สร้างบริษัท
- `POST /companies/{ticker}/documents` วางไฟล์ `.txt`, `.md`, หรือ `.pdf`
- `POST /companies/{ticker}/thesis` บันทึก thesis
- `POST /companies/{ticker}/knowledge` บันทึกความรู้ที่คุณยืนยันแล้ว
- `POST /companies/{ticker}/chat` ถาม
- `POST /conversations/{id}/close` สรุปความจำ
- `GET /companies/{ticker}/changes` ดูส่วนต่างตัวเลข
- `POST /proposals/{id}/approve` อนุมัติการเขียนจากเอเจนต์
- `POST /companies/{ticker}/export` สร้าง `exports/companies/{ticker}/investment-thesis.md`

บรรทัดตัวเลขในไฟล์ที่ parser อ่านได้เอง:

```
METRIC revenue_growth_yoy 2024 0.10
METRIC revenue_growth_yoy 2025 0.04
```

หรือตาราง `| metric | period | value |`

## สิ่งที่ MVP ยังไม่ทำ

ตัวเก็บข่าว, scheduler, เสียง, แอปมือถือ, sandbox คนละโปรเซส, และ embedding ตาราง `watchlist_items` มีแล้ว แต่ยังไม่มีงานตามรอบ
