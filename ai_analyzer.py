"""
ai_analyzer.py — GPT-4o-mini vision + text food analysis.
Calls OpenAI API and returns structured nutrition JSON.
Never raises exceptions — all errors are returned as dict.
"""

import base64
import json
import logging
import re

from openai import AsyncOpenAI, APIError

from config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.openai_api_key)

MODEL = "gpt-4o-mini"
MAX_TOKENS = 1000
TEMPERATURE = 0.1

SYSTEM_PROMPT = """Kamu adalah ahli gizi klinis dan food analyst berpengalaman.
Spesialisasimu adalah estimasi porsi dan komposisi makronutrisi dari foto makanan.

REFERENSI YANG KAMU GUNAKAN:
- Makanan Indonesia: DKBM (Daftar Komposisi Bahan Makanan) Kemenkes RI
- Makanan internasional: USDA FoodData Central
- Makanan kemasan: estimasi berdasarkan label kategori produk standar

ATURAN ESTIMASI PORSI:
- Piring makan standar Indonesia = diameter 26cm, kapasitas nasi ~200-250g
- Mangkok bakso/soto standar = 500ml
- Gelas minum standar = 250ml
- Centong nasi standar = 100-120g nasi matang
- Sendok makan = 15ml, sendok teh = 5ml
- Gunakan objek referensi dalam foto (tangan, sendok, meja) untuk kalibrasi ukuran
- Estimasi KONSERVATIF untuk protein (lebih baik under-estimate)
- Jika makanan tertutup kuah/saus, estimasi isi berdasarkan jenis sajian umum

ATURAN PENAMAAN:
- Spesifik: bukan "nasi" tapi "nasi putih pulen matang"
- Bukan "ayam goreng" tapi "ayam goreng tepung crispy bagian paha"
- Sertakan metode masak jika terlihat/bisa disimpulkan

CONFIDENCE:
- high: foto jelas, identifikasi pasti, estimasi ±10%
- medium: beberapa item atau foto agak blur, estimasi ±20%
- low: foto sangat blur / makanan tidak jelas, estimasi ±30%

OUTPUT: Kembalikan HANYA raw JSON, tanpa markdown, tanpa teks apapun di luar JSON:
{
  "foods_detected": [
    {
      "name": "nama spesifik",
      "portion": "misal: 200g / 1 centong besar / setengah piring",
      "calories": 000,
      "protein_g": 00.0,
      "carbs_g": 00.0,
      "fat_g": 00.0,
      "fiber_g": 0.0
    }
  ],
  "total": {
    "calories": 000,
    "protein_g": 00.0,
    "carbs_g": 00.0,
    "fat_g": 00.0,
    "fiber_g": 0.0
  },
  "confidence": "high/medium/low",
  "notes": "asumsi penting atau ketidakpastian (string kosong jika tidak ada)"
}

Jika foto tidak mengandung makanan:
{"error": "no_food", "message": "Foto ini tidak mengandung makanan."}"""


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    text = text.strip()
    # Remove opening fence (```json or ```)
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def analyze_food(
    image_bytes: bytes = None,
    text_input: str = None,
) -> dict:
    """
    Analyse food from an image (bytes) and/or text description.

    Returns a dict with keys:
        foods_detected, total, confidence, notes
    or an error dict:
        {"error": "no_food"|"parse_error"|"api_error", "message": str}

    Never raises an exception.
    """
    try:
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode()
            content: list = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                }
            ]
            if text_input:
                content.append(
                    {"type": "text", "text": f"Konteks dari user: {text_input}"}
                )
            else:
                content.append(
                    {"type": "text", "text": "Analisis semua makanan dalam foto ini."}
                )

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ]
        else:
            # Text-only mode
            user_text = (
                f"User mendeskripsikan makanannya secara teks: {text_input}. "
                "Estimasikan nutrisi berdasarkan deskripsi ini."
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ]

        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )

        raw_text = response.choices[0].message.content or ""
        logger.debug("Raw AI response: %s", raw_text)

        # First parse attempt
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Second attempt after stripping markdown fences
        cleaned = _strip_markdown_fences(raw_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse AI response after cleaning: %s", cleaned)
            return {
                "error": "parse_error",
                "message": "Gagal parse respons AI",
            }

    except APIError as e:
        logger.error("OpenAI API error: %s", e)
        return {"error": "api_error", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.error("Unexpected error in analyze_food: %s", e, exc_info=True)
        return {"error": "api_error", "message": f"Error tak terduga: {e}"}
