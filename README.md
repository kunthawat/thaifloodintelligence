# Thailand Flood Intelligence

แอปแผนที่สำหรับติดตามความเสี่ยงน้ำท่วมตามสเปกที่ให้มา โดยแยกข้อมูลตรวจวัด คำเตือนทางการ แบบจำลอง และความพร้อมของแหล่งข้อมูลออกจากกัน ค่าที่หน่วย เวลา สถานี หรือ datum ยังไม่ยืนยันจะไม่ถูกใช้สร้างตัวเลขพยากรณ์

## เริ่มต้นใช้งาน

เครื่อง Windows ที่จัดเตรียมไว้ใน workspace นี้เปิดใช้งานได้ทันทีโดยไม่ต้องใช้ Docker:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_local.ps1 -OpenBrowser
```

เปิดเองที่ `http://127.0.0.1:8899/` ได้เช่นกัน สคริปต์จะเปิด PostgreSQL/PostGIS แบบพกพาและแอปในเครื่องเมื่อยังไม่ทำงาน ฐานข้อมูลและไฟล์ GIS อยู่ใน `local_runtime/` และ `data/static/` ตามลำดับ หากย้าย workspace ไปเครื่องใหม่ ต้องติดตั้ง runtime และนำเข้าข้อมูลใหม่

สถานะปัจจุบัน: PostGIS, HydroBASINS Asia 12 ระดับ, HydroRIVERS Asia และ HydroSHEDS Asia DEM/DIR/ACC นำเข้าแล้ว แผนที่ใช้ MapLibre GL JS กับ OpenFreeMap; ต้องใช้อินเทอร์เน็ตสำหรับแผนที่ฐาน ค้นหาตำบลจากขอบเขต ปภ. และเน้นขอบเขตตำบลที่เลือกได้ ขอบเขตทางการมี 76 จังหวัด 926 อำเภอ และ 7,658 รหัสตำบล โดยรวม 7,778 รูปต้นทางที่มีรหัสซ้ำเป็นขอบเขตหลายส่วน ค่าระดับน้ำและฝนที่สถานีจาก ThaiWater public API รีเฟรชแคชทุก 10 นาที ค่าที่สถานีไม่ใช่ระดับน้ำหรือฝน ณ จุดที่ค้นหา `GET /v1/location/readiness?lat=...&lon=...` แสดงหลักฐานแยกประเภทภัย ส่วน `GET /v1/data-quality` แสดงสถานะแหล่งข้อมูลและสถานะแพลตฟอร์ม

ผลค้นหาจากขอบเขต ปภ. ใช้จุดที่อยู่ภายในรูปตำบล ไม่ใช่พิกัดบ้านแต่ละหลัง หากชื่อตำบลซ้ำ ให้เลือกอำเภอและจังหวัดจากผลค้นหา เมื่อย้ายเครื่อง ให้นำเข้าขอบเขตใหม่ด้วย `python -m scripts.import_dpm_boundaries`.

### ตั้งค่าใหม่บนเครื่องอื่น

ต้องใช้ Python 3.11 ขึ้นไปและ PostgreSQL/PostGIS 16/3.x หากต้องการเก็บข้อมูล:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

ไฟล์ `.env.example` เป็นตัวอย่างทั่วไป หากรัน Python บน Windows โดยตรง ให้ตั้ง `DATABASE_URL` และ `DATABASE_DSN` เป็น `localhost` และตั้ง `DATA_DIR`/`*_DATA_DIR` เป็นโฟลเดอร์ใน workspace แล้วจึงเริ่มฐานข้อมูลและเตรียม schema:

```powershell
python -m db.migrate
python -m app.seed.stations
```

แหล่งข้อมูลและสถานีจะถูกบันทึกใน migrations ของฐานข้อมูลแล้ว คำสั่ง seed สถานีใช้สำหรับนำเข้าซ้ำหลังการตั้งค่าครั้งแรกได้

รันแอป:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

เปิด `http://127.0.0.1:8000` แผนที่ฐาน OpenFreeMap อ้างอิง OpenStreetMap และต้องเชื่อมอินเทอร์เน็ต เอกสาร API อยู่ที่ `/api/docs`; สถานะระบบ แหล่งข้อมูล และ readiness อยู่ที่ `/health` และ `/v1/data-quality`.

## ตรวจและนำเข้าข้อมูล

Health check ติดต่อเฉพาะ endpoint ทางการที่เปิดใช้งาน ตั้ง timeout และรายงาน blocker ต่อแหล่งข้อมูล:

```powershell
python -m scripts.check_sources
python -m scripts.ingest_hii_metadata
python -m scripts.ingest_dwr_warnings
python -m scripts.ingest_rid
python -m scripts.ingest_navy_tide --year 2026
python -m scripts.ingest_tmd_qpe
python -m scripts.import_dpm_boundaries
```

HII archive จะค้นพบจาก catalog ก่อน แล้วจึงนำเข้า resource ที่ได้จาก catalog:

```powershell
python -m scripts.ingest_hii_archive --archive-url "<URL ที่ได้จาก ingest_hii_metadata>" --station-code NAN001
```

ตัวเลือก GIS เก็บไฟล์ต้นฉบับไว้ใต้ `data/static` และปฏิเสธไฟล์ที่ตรวจ CRS, no-data, ความละเอียด หรือ topology ไม่ผ่าน:

```powershell
python -m scripts.bootstrap_terrain --region asia --resolution 3s
python -m scripts.bootstrap_hydrobasins --region asia
python -m scripts.bootstrap_hydrorivers --region asia
```

คำสั่ง GIS ต้องมี `rasterio` สำหรับ GeoTIFF validation และ `pyogrio` สำหรับ shapefile validation/import; โปรแกรมจะรายงาน dependency ที่ขาดโดยไม่ข้ามการตรวจสอบ

## นโยบายข้อมูลและสถานะที่ยังไม่พร้อม

- ค่า missing เช่น `-999`, `999999`, `9999` และ `-` จะไม่กลายเป็นศูนย์
- HII archive ใช้เพื่อประวัติ/สอบเทียบ ไม่ถูกยกเป็นข้อมูลสดปัจจุบัน
- HII legacy numeric station ID ต้องตรงกับรหัสหรือชื่อสถานีจากผลตอบกลับก่อนใช้
- RID `inflow`/`outflow` เก็บเป็น `RID_RAW_*`, ไม่มี unit และถูกล็อกไม่ให้เข้าสมดุลมวล
- QPE ASCII ต้องค้นหา URL ปัจจุบันจากหน้า TMD และตรวจ ZIP/header; หาก unit ไม่มีหลักฐานจะเก็บไฟล์ดิบและไม่สร้าง forcing ฝน
- Navy tide อ่าน PDF รายชั่วโมงแบบ MSL จากลิงก์ของปีปัจจุบัน บันทึกเป็น `FORECAST`; ไม่ใช้เป็นระดับทะเลที่ตรวจวัด และไม่ส่งตรงไปยังระดับประตูน้ำในแผ่นดิน
- GISTDA และ IMERG ถูกปิดไว้จนกว่าจะมี credential/configuration; ผลว่างไม่ใช่หลักฐานว่าไม่มีน้ำท่วมหรือฝน
- คำเตือนที่ระบุจังหวัด อำเภอ หรือตำบลชัดเจนจะจับคู่กับขอบเขต ปภ.; ชื่อซ้ำหรือข้อความกำกวมจะไม่ถูกขยายเป็นคำเตือนทั้งจังหวัด คำเตือนจะอ่านจากฐานข้อมูลที่อัปเดตเบื้องหลังทุก 10 นาทีเพื่อไม่ให้หน้าแอปรอเว็บต้นทาง
- รายงาน DWR เป็นรายการย้อนหลังเรียงจากใหม่ไปเก่า ระบบนำเข้าช่วง 72 ชั่วโมง แต่ถือเป็นคำเตือนปัจจุบันได้เฉพาะรายการที่ออกใน 2 ชั่วโมงล่าสุด รายการเก่าที่ครอบคลุมจุดที่เลือกจะแสดงแยกและติดป้ายว่าเป็นข้อมูลย้อนหลัง
- สถานะภัยแยกเป็น `READY`, `PARTIAL`, `NOT_READY` รายตำแหน่ง ผล `PARTIAL` จากสถานีใกล้เคียงเป็นข้อมูลประกอบเท่านั้น และยังไม่ใช่ระดับความเสี่ยงน้ำท่วม
- HydroRIVERS เก็บ `NEXT_DOWN` และคุณลักษณะต้นฉบับ; ความจุไฮดรอลิกไม่ถูกสมมติ และไม่มีการสร้างคลองเทียมจากโครงข่ายแม่น้ำธรรมชาติ
- ชุด DEM/ลุ่มน้ำ/แม่น้ำที่ดาวน์โหลดและนำเข้าแล้วอยู่ใน `data/static` ส่วนข้อมูลสถานีภาคสนามสดและข้อมูลฝนที่ใช้ประเมินยังไม่ครบ
- ระดับน้ำเสี่ยง เหตุการณ์/คลื่น เวลาถึงจุดสูงสุด ความลึกเฉพาะจุด และความเสี่ยงรายพิกัดจะยังแสดงว่าไม่พร้อมจนกว่าข้อมูลและเกณฑ์ eligibility ที่ระบุในสเปกจะผ่าน
- HII catalog รายงานใบอนุญาต CC Attribution Non-Commercial; ทบทวนสิทธิ์ก่อนใช้งานเชิงพาณิชย์

ตัวอย่าง `.env` ตั้งใจเว้น API keys และรหัสผ่านจริงไว้ให้ผู้ดูแลกำหนดเอง
