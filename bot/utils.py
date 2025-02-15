import qrcode
from uuid import uuid4
from datetime import datetime, timedelta
from bot.repo.database import db

async def generate_qr(user_id):
    code = str(uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=1)

    await db.get_db().execute("INSERT INTO qr_codes (code, user_id, expires_at) VALUES ($1, $2, $3)", code, user_id, expires_at)

    img = qrcode.make(f"WATER_CODE:{code}")
    img.save("qr.png")
    return "qr.png"
