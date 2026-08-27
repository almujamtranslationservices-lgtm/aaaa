# 🎬 AI Video Factory

منصة سطح مكتب لتحويل **فكرة** إلى **فيديو كامل** شبه تلقائي:

```
User Idea → Script → Scenes → Prompts → Images → Videos → Voice
→ Music & SFX → Subtitles → Rendering → Thumbnail → SEO → Final MP4
```

مبنية بـ **Python 3.12+** (متوافقة مع 3.11) و **PySide6** و **FFmpeg**، بمعمارية
Modular قابلة للتوسع، ومبدأ **Free-First**: المحلي أولاً، ثم الخدمات المجانية، ثم المدفوعة.

---

## 📊 الحالة الحالية (v0.1.0)

| المرحلة | الحالة | المحتوى |
|---|---|---|
| PHASE 1 — Architecture | ✅ منجزة | Core / Models / Utils / Prompts / Provider ABCs / Demo LLM / CLI |
| PHASE 2 — Database | ✅ منجزة | SQLite + Migrations + Repositories |
| PHASE 3 — GUI | ✅ منجزة | PySide6 كاملة: Dashboard / Project / Scenes / Providers / Settings / Logs |
| PHASE 4 — Project Mgmt | ✅ منجزة | إنشاء/فتح/حفظ تلقائي/نسخ احتياطي/استئناف |
| PHASE 5 — LLM Providers | ✅ منجزة | Ollama (محلي) · Gemini · OpenRouter · OpenAI + Fallback تلقائي |
| PHASE 6 — Scene Generator | ✅ منجزة | إثراء المشاهد + Prompts لكل مشهد (prompt.json + Cache) + Character Bible UI |
| PHASE 7 — Image Providers | ✅ منجزة | Demo (Pillow) · ComfyUI · SD WebUI · HuggingFace · Stability · OpenAI + Cache وDB |
| PHASE 8 — Video Providers | ✅ منجزة | Ken Burns حقيقي (FFmpeg) · ComfyUI i2v (قوالب) · Stability SVD + كاش لكل مشهد |
| PHASE 9 — Voice Providers | ✅ منجزة | Demo (نغمات WAV) · Edge TTS (مجاني) · Piper محلي · ElevenLabs + محول MP3→WAV |
| PHASE 10 — Audio System | ✅ منجزة | مزج voice+music+SFX · **Ducking تلقائي** · Fades · موسيقى وSFX إجرائية |
| PHASE 11 — Subtitles | ✅ منجزة | SRT + ASS كامل التنسيق · توقيتات من الصوت الفعلي · لكل مشهد + موحّد |
| PHASE 12+ — تجميع/رندر | ⬜ حسب الخطة | راجع [TODO.md](TODO.md) |

**يعمل اليوم (225 اختباراً ناجحاً):** الواجهة كاملة + سكربت (سلسلة احتياط) + Prompts +
**صور** + **فيديو MP4 لكل مشهد** + **تعليق صوتي لكل مشهد** + **مزج صوتي كامل لكل مشهد** (mix.wav): موسيقى خلفية تُخفض
تلقائياً أثناء الكلام (sidechain ducking) + SFX + fades — بأصوات Edge مجانية أو
ElevenLabs/Piper/نغمات offline، مع كاش وعزل أعطال + **ترجمات SRT/ASS** مولّدة
من توقيتات النطق الحقيقية لكل مشهد، بخط/ألوان/موضع/حركة قابلة للضبط بالكامل.

لقطات الواجهة: `docs/ui_dashboard.png` · `docs/ui_project_prompts.png` · `docs/ui_characters.png` · `docs/ui_scene_editor.png` · `docs/ui_providers.png`

```bash
python app.py gui        # تشغيل الواجهة
python app.py doctor     # تقرير بيئة كامل (Python/FFmpeg/GPU/مزودون)
python app.py selftest   # فحص استيراد الوحدات الأساسية (+UI عند توفر PySide6)
```

---

## ⚙️ المتطلبات

- **Python 3.11+** (3.12 موصى بها) — <https://www.python.org>
- **FFmpeg** (إلزامي للرندر في المراحل 8+)
- **SQLite** — مضمّن مع Python
- اختياري للتشغيل المحلي: **Ollama**، **ComfyUI**، **Stable Diffusion WebUI**، **Piper TTS**
- **GPU** غير إلزامي — النماذج السحابية والمحلية على CPU تعمل

### تثبيت FFmpeg

| النظام | الأمر |
|---|---|
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| macOS | `brew install ffmpeg` |
| Windows | `winget install Gyan.FFmpeg` أو من [ffmpeg.org](https://ffmpeg.org) ثم أضفه لـ PATH |
| تطوير/اختبار فقط | `pip install imageio-ffmpeg` (نسخة static احتياطية — يكتشفها البرنامج تلقائياً) |

لتحديد مسار مخصص: `AVF_FFMPEG_PATH=/path/to/ffmpeg` في `.env`.

---

## 🚀 التثبيت والتشغيل

```bash
git clone <repo-url> && cd <repo>
bash scripts/setup_dev.sh        # ينشئ .venv ويثبّت requirements.txt (+ Qt stubs للحاويات فقط)
cp .env.example .env             # ثم ضع مفاتيحك (اختياري — Demo Mode يعمل بدونها)

source .venv/bin/activate
python app.py gui                # تشغيل الواجهة 🎬
python app.py doctor             # تحقق من البيئة
python -m pytest                 # تشغيل الاختبارات (225)
```

### أول تجربة خلال دقيقة (Demo Mode)
1. `python app.py gui`
2. **Dashboard → New Project** → املأ الاسم والنوع والمدة (أو اكتب الفكرة لاحقاً)
3. في صفحة **Project**: اكتب الفكرة في مربع **VIDEO IDEA** ثم اضغط **Generate Script**
4. شاهد التقدم الحقيقي في لوحة Progress، ثم عدّل المشاهد في صفحة **Scenes**
   — كل شيء يُحفظ تلقائياً في `projects/<project>/project.json`

على Windows: `python -m venv .venv` ثم `.venv\Scripts\activate` ثم `pip install -r requirements.txt`.

---

## 🔑 إعداد المزودين (API Keys)

لا تُخزَّن المفاتيح في الكود ولا في قاعدة البيانات ولا في اللوجات — فقط `.env`:

```env
GEMINI_API_KEY=...        # مجاني بطاقة ائتمانية محدودة
OPENROUTER_API_KEY=...    # فيه موديلات free
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
STABILITY_API_KEY=...
HUGGINGFACE_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434
COMFYUI_BASE_URL=http://localhost:8188
```

- إخفاء المفاتيح من اللوجات مطبّق في `core/logger.py` (SecretRedactingFilter).
- `.env` مُدرج في `.gitignore` — **لا ترفعه أبداً**.

### Ollama (LLM محلي — مجاني بالكامل)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1
# البرنامج يتصل تلقائياً عبر http://localhost:11434
```

### إعداد المزودين في البرنامج

صفحة **AI Providers** تعرض كل المزودين (Free-First) مع حالة المفتاح وزر
**Test Connection** وعمود **Model** قابل للتحرير (يُحفظ في قاعدة البيانات، ويسقط
على متغير البيئة مثل `OLLAMA_MODEL=` ثم الافتراضي). عند فشل المزود المختار أثناء
توليد السكربت، تنتقل المحاولة تلقائياً للمزود التالي في السلسلة (Ollama → Gemini →
OpenRouter → OpenAI) — والـ Demo كملاذ أخير فقط.```

### ComfyUI (صور/فيديو محلي)

```bash
git clone https://github.com/comfyanonymous/ComfyUI && cd ComfyUI
pip install -r requirements.txt
python main.py --listen 0.0.0.0 --port 8188
```

### Stable Diffusion WebUI (A1111)

شغّله بـ `--api` على المنفذ 7860 وحدد `SD_WEBUI_BASE_URL`.

---

## 🏗️ المعمارية

```
ai_video_factory/
├── app.py                  # مشغّل رفيع: python app.py (doctor/selftest/gui)
├── config/                 # settings.py (طبقات: defaults→json→env) + providers.py (سجل Free-First)
├── core/                   # event_bus, logger, task_manager, pipeline, project_manager, exceptions
├── models/                 # pydantic: Project, Scene+Script, Character, Prompt(15 مكوناً), Audio, Video
├── ai/                     # llm/ image/ video/ voice/ — ABC + demo + factory.py
├── services/               # use-cases مشتركة بين GUI وPipeline (script_service)
├── media/                  # معالجة الصور/الفيديو/الصوت/الترجمة (PHASE 10-12)
├── prompts/                # مولّدات prompts (script/scene/image/video/seo)
├── database/               # SQLite + migrations + repositories
├── ui/                     # PySide6 (PHASE 3)
├── utils/                  # file/time/validation (JSON auto-repair) / ffmpeg engine
├── assets/                 # موسيقى/SFX/خطوط/قوالب
├── projects/               # مشاريع المستخدم (كل مشروع: scenes/scene_XXX/...)
├── output/                 # المخرجات النهائية
└── tests/                  # 107 اختبارات
```

### مبادئ التصميم

1. **EventBus** هو العمود الفقري: كل تقدم/خطأ/حدث يُنشر كحدث، والـ UI (PHASE 3) يشترك به عبر Qt Bridge — لا تجميد إطلاقاً.
2. **TaskManager**: خيوط خلفية + Retry تلقائي + Cancel تعاوني + حفظ حالة المهام في SQLite (استئناف بعد الإغلاق).
3. **Pipeline** بأوزان تقدم حقيقية (Script 10% → Scenes 20% → Images 40% → … → Completed 100%) وسياسات خطأ لكل مرحلة (abort/skip/retry).
4. **Cache System**: كل أصل يُحفظ في `scenes/scene_XXX/{image.png,video.mp4,voice.wav,prompt.json}` — فشل المشهد 6 لا يعيد توليد 1-5.
5. **Character Bible**: وصف منظم لكل شخصية يُحوَّل لـ prompt block يُحقن تلقائياً **مرة واحدة** في كل prompt (Consistency).
6. **Auto-Repair JSON**: مخرجات LLM تمر بكascade إصلاح (fences → smart quotes → trailing commas → python literals) قبل التحقق الصارم بـ pydantic.
7. **لا وظائف وهمية**: أي مزود لم يُنفّذ يرفع `ProviderNotImplementedError` موضحاً رقم المرحلة.

### إضافة مزود جديد (مثال)

```python
# 1) config/providers.py — سجّل المعلومات فقط:
ProviderInfo("myllm", "My Provider", ProviderKind.LLM, ProviderTier.FREE,
             "ai_video_factory.ai.llm.myllm", "MyLLMProvider",
             env_key="MYLLM_API_KEY", requires_api_key=True, implemented=True)

# 2) ai/llm/myllm.py — نفّذ الواجهة:
class MyLLMProvider(LLMProvider):
    async def generate(self, request: LLMRequest) -> str: ...
```

لا شيء آخر يتغير — الـ factory والـ UI والـ fallback chains تلتقطه تلقائياً.

---

## 🧪 الاختبارات

```bash
python -m pytest                 # كل الاختبارات (107)
python -m pytest tests/test_pipeline.py -v
```

التغطية الحالية: JSON auto-repair، Script validation، نماذج البيانات، EventBus،
TaskManager (retry/cancel/persist)، Pipeline (أوزان/أخطاء/إلغاء)، ProjectManager
(حفظ/تحميل/backup/cache)، قاعدة البيانات وRepositories، الـ Prompts (15 مكوناً)،
Demo LLM end-to-end، وFFmpegEngine (بترميز فيديو حقيقي عند توفر ffmpeg).

---

## 🛠️ حل المشاكل

| المشكلة | الحل |
|---|---|
| `FFmpeg not found` | ثبّت FFmpeg أو `pip install imageio-ffmpeg` أو حدد `AVF_FFMPEG_PATH` |
| `ProviderNotImplementedError` | المزود لم يُنفّذ بعد — راجع TODO.md لمرحلته، أو استخدم `demo` |
| `ProviderNotConfiguredError` | ضع المفتاح في `.env` (مثلاً `GEMINI_API_KEY=`) |
| `ImportError: libGL.so.1` (حاويات/سيرفرات فقط) | `bash scripts/setup_qt_stubs.sh .venv/bin/python` — غير مطلوب على أجهزة سطح المكتب |
| Python < 3.11 | حدّث Python؛ الكود يستخدم 3.11+ features |
| اللوجات لا تُكتب | تأكد أن مجلد `logs/` قابل للكتابة (يُنشأ تلقائياً) |

---

## 🔒 الأمان

- المفاتيح في `.env` فقط (مُستثنى من Git)، وتُقرأ عند الاستدعاء.
- فلتر `SecretRedactingFilter` يحجب قيم المفاتيح وأنماطها (`sk-…`, `AIza…`) من كل اللوجات وملفاتها.
- لا مفاتيح في الكود أو قاعدة البيانات — جدول `providers` يخزن **اسم** متغير البيئة فقط.

---

## 🗺️ خارطة الطريق

مزودو LLM الحقيقيون (PHASE 5: Ollama/Gemini/OpenRouter/OpenAI) → Scene Generator (6)
→ صور (7) → فيديو (8) → صوت (9) → Audio (10) → ترجمة (11) → FFmpeg كامل (12)
→ Pipeline الرندر (13) → SEO (14) → Thumbnail (15) → اختبارات موسعة (16) → Packaging (17).

بعد ذلك (مصمم له من الآن): رفع تلقائي ليوتيوب/تيك توك، ترجمة ودبلجة، Lip Sync،
استنساخ صوت، Batch لـ100 فكرة، رندر سحابي — كلها إضافات على نفس الواجهات دون إعادة كتابة.

التفاصيل الكاملة في [TODO.md](TODO.md).
