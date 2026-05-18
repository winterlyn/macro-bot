"""
app/services/ai_analyzer.py — Gemini 2.0 Flash vision + text food analysis.
Calls Google Gemini API and returns structured nutrition JSON.
Never raises exceptions — all errors returned as error dict.
"""

import json
import logging
import re
import warnings

# Suppress the deprecation warning from google.generativeai
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

from io import BytesIO
from PIL import Image

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from app.core.config import settings

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)

MODEL = "gemini-2.5-flash-lite-preview-06-17"
TEMPERATURE = 0.1
MAX_OUTPUT_TOKENS = 1000

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
    """Remove ```json ... ``` or ``` ... ``` wrappers from AI response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def analyze_food(
    image_bytes: bytes = None,
    text_input: str = None,
) -> dict:
    """
    Analyse food from image bytes and/or text description.

    Returns structured dict with keys: foods_detected, total, confidence, notes
    On failure returns: {"error": "no_food"|"parse_error"|"api_error"|"rate_limit", "message": str}

    Never raises an exception.
    """
    try:
        model = genai.GenerativeModel(
            model_name=MODEL,
            generation_config={
                "temperature": TEMPERATURE,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
            system_instruction=SYSTEM_PROMPT,
        )

        contents = []
        if image_bytes:
            # Convert bytes to PIL Image
            pil_image = Image.open(BytesIO(image_bytes))
            if text_input:
                contents = [f"Konteks dari user: {text_input}", pil_image]
            else:
                contents = ["Analisis semua makanan dalam foto ini.", pil_image]
        else:
            contents = [
                f"User mendeskripsikan makanannya secara teks: {text_input}. "
                "Estimasikan nutrisi berdasarkan deskripsi ini."
            ]

        response = await model.generate_content_async(contents)

        raw_text = response.text or ""
        logger.debug("Raw AI response: %s", raw_text)

        # First parse attempt
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Second attempt: strip markdown fences
        cleaned = _strip_markdown_fences(raw_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse AI response after cleaning:\n%s", cleaned
            )
            return {"error": "parse_error", "message": "Gagal parse respons AI"}

    except GoogleAPIError as e:
        error_message = str(e)
        # Check for rate limit error (429)
        if "429" in error_message or "quota" in error_message.lower() or "rate limit" in error_message.lower():
            logger.warning("Gemini API rate limit hit: %s", e)
            return {"error": "rate_limit", "message": "Rate limit, coba lagi dalam 1 menit"}
        logger.error("Gemini API error: %s", e)
        return {"error": "api_error", "message": str(e)}
    except Exception as e:
        logger.error("Unexpected error in analyze_food: %s", e, exc_info=True)
        return {"error": "api_error", "message": f"Error tak terduga: {e}"}
