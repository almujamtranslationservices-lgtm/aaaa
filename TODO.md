# AI Video Factory — TODO / خطة التنفيذ

مرجع التنفيذ المرحلي (spec §33). لا ننتقل لمرحلة تالية قبل نجاح اختبارات المرحلة الحالية.

**مفتاح الحالة:** ✅ منجزة · 🔄 قيد التنفيذ · ⬜ لم تبدأ

---

## PHASE 1 — Project Architecture ✅
- [x] فحص البيئة (Python / FFmpeg / GPU / أدوات)
- [x] بنية الحزم والمجلدات الكاملة (`ai_video_factory/`)
- [x] `config/settings.py` — إعدادات متعددة الطبقات (defaults → settings.json → .env)
- [x] `config/providers.py` — سجل المزودين Free-First (LOCAL → FREE → PAID)
- [x] `core/event_bus.py` — Pub/Sub آمن مع الخيوط
- [x] `core/logger.py` — Log دوّار + إخفاء مفاتيح API تلقائياً + تغذية الـ UI
- [x] `core/exceptions.py` — شجرة أخطاء مركزية
- [x] `core/task_manager.py` — طابور خلفي: Retry / Cancel / Persist / Progress
- [x] `core/pipeline.py` — Pipeline بأوزان تقدم حقيقية + سياسات خطأ (abort/skip/retry)
- [x] `core/project_manager.py` — إنشاء/حفظ/تحميل + AutoSave + Backup + Cache layout
- [x] `models/*` — Project / Scene / Script / Character / Prompt / Audio / Video (pydantic)
- [x] `utils/validation.py` — استخراج JSON + إصلاح تلقائي متدرج لمخرجات LLM
- [x] `utils/ffmpeg_utils.py` — FFmpegEngine (كشف + تنفيذ موحّد)؛ العمليات في PHASE 12
- [x] `prompts/*` — مولّدات Script/Scene/Image/Video/SEO prompts (15 مكوّناً)
- [x] `ai/*/base.py` — واجهات ABC لكل المزودين + DemoLLMProvider كامل
- [x] `ai/factory.py` — مصنع المزودين مع رفض صريح لغير المنفّذ (NotImplemented)
- [x] CLI: `python app.py doctor|selftest|gui|version`
- [x] اختبارات المرحلة ✅

## PHASE 2 — Database ✅
- [x] `database/database.py` — SQLite + WAL + Migrations عبر `PRAGMA user_version`
- [x] الجداول: projects, characters, scenes, prompts, assets, tasks, settings, providers, render_jobs
- [x] `database/repositories.py` — طبقة Repositories كاملة + بروتوكول TaskPersistence
- [x] مرآة Scenes/Characters في DB عند كل حفظ (project.json يبقى مصدر الحقيقة)

## PHASE 3 — GUI ✅
- [x] PySide6 + Dark Theme احترافي (`ui/widgets/styles.py`)
- [x] `ui/widgets/event_bridge.py` — ربط EventBus → Qt Signals (queued cross-thread)
- [x] `ui/widgets/progress_panel.py` — Progress حقيقي: Task/Stage/Elapsed/ETA/Errors
- [x] `ui/main_window.py` — Sidebar + 6 صفحات + Status Bar + تنبيه عند الخروج بمهام نشطة
- [x] `ui/dashboard.py` — New/Open/Recent + System Status + نافذة New Project كاملة (spec §5)
- [x] `ui/project_view.py` — مربع VIDEO IDEA + **Generate Script يعمل فعلياً** + جدول المشاهد
      (زر Generate Everything معطّل بصدق حتى PHASE 13 — spec §39)
- [x] `ui/scene_editor.py` — Timeline بسيط: تحرير/إضافة/حذف/إعادة ترتيب + AutoSave
- [x] `ui/settings_view.py` — كل الإعدادات + اختيار المزودين الافتراضيين (Free-First)
- [x] `ui/provider_view.py` — جدول المزودين + حالة المفاتيح (بدون عرضها) + Test Connection حقيقي
- [x] `ui/logs_view.py` — بث مباشر ملوّن + فلتر مستوى + AutoScroll
- [x] `services/script_service.py` — خدمة توليد السكربت (UI-agnostic، ستخدم الـ Pipeline لاحقاً)
- [x] `app.py` (AppContext) — جذر التركيب/DI + `launch_gui()`
- [x] اختبارات GUI حقيقية offscreen (إنشاء مشروع → توليد سكربت → تحرير مشهد → حفظ) ✅
- [x] لقطات شاشة للواجهة في `docs/`

## PHASE 4 — Project Management ✅ (سُلّمت مبكراً ضمن 1-3)
- [x] إنشاء/فتح/حفظ/حذف + Recent Projects + AutoSave + Backup + Cache layout
- [x] استئناف المهام بعد الإغلاق (TaskRepository.pending() — يُستخدم في PHASE 13)

## PHASE 5 — LLM Integration ✅
- [x] `ai/llm/http_common.py` — طبقة HTTP مشتركة (httpx) + تحويل الأخطاء الموحّد
- [x] `ai/llm/ollama.py` — Ollama محلي كامل (محادثة + فحص `ollama pull` للموديل)
- [x] `ai/llm/gemini.py` — Gemini (المفتاح في Header لا في URL — لا يتسرب للوجات)
- [x] `ai/llm/openrouter.py` + `ai/llm/openai.py` — متوافقان مع OpenAI API
- [x] `ai/llm/chain.py` — LLMChain: Fallback تلقائي LOCAL→FREE→PAID + ChainReport
- [x] اختيار الموديل: DB (صفحة المزودين) → متغير بيئة → افتراضي (لكل مزود)
- [x] `services/script_service` يدعم model + fallback (ديمو كملاذ أخير فقط)
- [x] صفحة AI Providers: عمود Model قابل للتحرير + Test Connection حقيقي للجميع
- [x] اختبارات: 20 اختباراً ضد Mock HTTP (بدون شبكة/مفاتيح) ✅

## PHASE 6 — Scene Generator ✅
- [x] `services/scene_service.py` — إثراء المشاهد (environment/action/lighting/camera)
      عبر LLM (مع fallback offline حتمي عند الفشل أو مع مزوّد demo)
- [x] بناء Prompts كاملة لكل مشهد: صورة (15 مكوّناً + Character Bible مرة واحدة) + فيديو
- [x] حفظ `scenes/scene_XXX/prompt.json` (prompts + seed + وصف الشخصيات + frame) — قابلية إعادة الإنتاج
- [x] Seed حتمي لكل مشهد (sha256(project:scene)) — نفس النتيجة بين التشغيلات
- [x] Cache (spec §21): تخطي المشاهد التي لديها prompt.json — فشل مشهد لا يعيد توليد البقية
      (`force=True` للإعادة الكاملة)
- [x] فشل مشهد واحد → FAILED له فقط والبقية تُكمل
- [x] `ui/character_view.py` — Character Bible: محرر منظم (13 حقلاً) + معاينة حية لبلوك
      الـ prompt الذي سيُحقن + حفظ تلقائي ومرآة DB (replace-all)
- [x] صفحة المشروع: زر **Build Scene Prompts** (خلفي حقيقي عبر TaskManager)
- [x] منطق الشخصيات: مشهد بلا شخصيات لا يُحقن بأي وصف (حقن مرجعي صارم)
- [x] اختبارات: 9 جديدة (خدمة المشاهد + GUI الشخصيات + تدفق الأزرار) ✅

## PHASE 7 — Image Providers ✅
- [x] `ai/http_common.py` — طبقة HTTP مشتركة لكل المزودين (JSON + باينري) بتخطيط أخطاء موحّد
- [x] `ai/image/demo.py` — **DemoImageProvider**: لوحات placeholder حقيقية بـ Pillow
      (تدرّج سينمائي + نجوم + vignette) — حتمية حسب الـ seed وبأبعاد المشروع الدقيقة
- [x] `ai/image/local.py` — **ComfyUI** (بناء workflow API + poll في /history + تحميل /view
      + checkpoint قابل للضبط) و**SD WebUI** (txt2img + base64) — محليان بالكامل
- [x] `ai/image/api.py` — **HuggingFace** (مجاني) + **Stability** (v2beta) + **OpenAI Images**
      (b64_json مع mapping للأبعاد المدعومة)
- [x] `services/image_service.py` — توليد لكل المشاهد: image.png + تسجيل الأصول في DB
      (sha256 + حجم) + حالة image_ready + تقدم لكل مشهد
- [x] Cache (§21): الصورة الموجودة تُتخطى (force للإعادة)؛ فشل مشهد معزول لا يوقف البقية،
      وإعادة المحاولة تولّد الفائت فقط
- [x] UI: قائمة مزود صور مستقلة + زر **Generate Images** (خلفي) + مصغّرات صور في محرر
      المشاهد + إيموجي حالة لكل مشهد في الـ Timeline
- [x] تسجيل الأصول في DB مساعد وليس جوهرياً (فشله لا يُفشل المشهد)
- [x] اختبارات: 18 جديدة (مزودون ضد Mock HTTP + خدمة + تدفق GUI بصور فعلية) ✅

## PHASE 8 — Video Providers ✅
- [x] `FFmpegEngine.image_to_video` — أول عملية FFmpeg حقيقية: **Ken Burns**
      (zoompan: zoom_in/out + pan L/R + static، upscale 3x لحركة سلسة) + `validate_video`
- [x] `ai/video/demo.py` — **DemoVideoProvider**: مقاطع MP4 حقيقية offline بتدوير حركات
      حسب المشهد مع احترام تلميحات الكاميرا من الـ prompts
- [x] `ai/video/local.py` — **ComfyUIVideoProvider** قائم على قالب workflow قابل للتبديل
      (`assets/templates/comfyui_i2v_template.json` أو `COMFYUI_I2V_TEMPLATE`):
      رفع الصورة → /prompt → استطلاع /history → تحميل المقطع؛ استبدال typed
      (أرقام كـ int) وتجريد مفاتيح التوثيق
- [x] `ai/video/api.py` — **StabilityVideoProvider** (SVD): submit → poll 202/200 → تنزيل
      MP4؛ motion_strength → motion_bucket_id
- [x] `services/video_service.py` — video.mp4 لكل مشهد + كاش + عزل فشل + تسجيل أصول
      + تخطي صريح للمشاهد بلا صورة (بدل اعتبارها فاشلة) + حالة video_ready
- [x] UI: قائمة مزود فيديو + زر **Generate Videos** (خلفي) + حدث videos.generated
- [x] اختبارات: 21 جديدة — ترميز حقيقي لكل الحركات الخمس، سلامة MP4 بفك كامل،
      تدفق ComfyUI/Stability ضد Mock HTTP، كاش وعزل الخدمة ✅

## PHASE 9 — Voice Providers ✅
- [x] `media/audio_processor.py` — أول طبقة صوت حقيقية: convert_to_wav (FFmpeg)
      + أدوات WAV بالـ stdlib (مدة/صلاحية/ذروة السعة)
- [x] `ai/voice/demo.py` — **DemoVoiceProvider**: WAV كلامي فعلي (توافقيات + vibrato +
      مغلف مقاطع) بمدة تقديرية من طول النص، حتمي، volume/pitch/speed مطبّقة
- [x] `ai/voice/edge_tts.py` — **EdgeTTSProvider** (مجاني بدون مفاتيح): rate/pitch/volume
      تُحوَّل لصيغة edge، MP3 → WAV عبر FFmpeg مع تنظيف المؤقت
- [x] `ai/voice/elevenlabs.py` — طلب حقيقي (xi-api-key) مع emotion→style/stability وحل
      أسماء أصوات عامة → voice ids
- [x] `ai/voice/local.py` — **Piper** المحلي (WAV مباشرة بدون تحويل)
- [x] `services/voice_service.py` — voice.wav لكل مشهد + كاش + تخطي صريح لمن لا سرد فيه
      + عزل فشل + تمرير VoiceSettings من المشروع
- [x] UI: قائمة مزود صوت + **مختار صوت الراوي** (أصوات عربية/إنجليزية شائعة، قابل
      للتحرير لأي voice id) + زر **Generate Voice** (خلفي)
- [x] اختبارات: 16 جديدة (نغمات demo الحتمية، تحويل MP3→WAV حقيقي، محاكاة edge/11L/Piper
      بمحتوى MP3/WAV فعلي، كاش وعزل الخدمة) ✅ — 201 إجمالاً

## PHASE 10 — Audio System ✅
- [x] `FFmpegEngine.mix_audio` — المزج الحقيقي: voice + music + SFX في باس ستيريو
      موحّد مع `alimiter` (لا قطع صوتي)، الموسيقى تُ loop تلقائياً وتُقلَّم للمدة
- [x] **Ducking تلقائي أثناء الكلام** عبر sidechaincompress (صوت الراوي يقود
      ضغط الموسيقى) مع attack/release مضبوطين وduck_level_db → ratio mapping
- [x] Fade in/out للموسيقى (curves=tri) + مستويات مستقلة لكل مسار
- [x] مولّدات offline: موسيقى ambient (كورد متطور بـ LFOs) + SFX إجرائية
      (wind/tone/rumble/shimmer من وصف المشهد) — حتمية وبلا اعتماديات
- [x] `services/audio_service.py` — music bed على مستوى المشروع (مسار المستخدم من
      assets/music أو المولّدة) + sfx.wav لكل مشهد + **mix.wav لكل مشهد** بكاش
      وعزل أعطال + MusicSettings كاملة (volume/fades/ducking)
- [x] UI: زر **Mix Audio** (خلفي) + حدث audio.mixed
- [x] اختبارات: 11 جديدة — أهمها اختبار سلوكي يقيس أن الموسيقى تنخفض فعلاً أثناء
      الكلام (وتعود بعدة) مقابل عينة تحكم بلا ducking ✅ — 212 إجمالاً

## PHASE 11 — Subtitles ✅
- [x] `media/subtitle_processor.py` — تقسيم السرد إلى cues (جمل ثم التفاف بحرفي
      بلا كسر كلمات أبداً) وتوزيع التوقيتات نسبياً على طول كل cue
- [x] **التوقيت من الصوت الفعلي**: voice.wav للمشهد يحدد نافذة الترجمة (وإلا تقدير
      مدة الكلام) — وليس مجرد مدة المشهد
- [x] كاتبا **SRT وASS** كاملان: ASS يحترم كل SubtitleSettings (خط/حجم/موضع
      bottom-center-top/ألوان &HBGR/حد/خلفية صندوقية شبه شفافة/حركات fade-pop-slide)
- [x] `services/subtitle_service.py` — subtitle.srt لكل مشهد + subtitles.srt/ass
      موحّد بتوقيتات مطلقة على تايم لاين التجميع + كاش + تخطي صريح لما بلا سرد
- [x] UI: زر **Subtitles** (خلفي) + حدث subtitles.generated
- [x] 13 اختباراً جديداً (توقيت من WAV حقيقي، رتابة وترتيب، ألوان ASS، خدمة/كاش) ✅

## PHASE 12 — FFmpeg Engine (كامل) ✅
- [x] `concat_videos` — تطبيع كل مقطع (scale+pad+setsar+fps+yuv420p) ثم concat
      filter بإعادة ترميز: مقاطع بأبعاد مختلفة تُدمج في تدفق واحد سليم؛ الأبعاد
      الافتراضية من أول مقطع أو تُفرض صراحةً
- [x] `burn_subtitles` — حرق SRT/ASS عبر subtitles filter مع force_style (حقول
      ASS بفواصل)؛ الصوت يُنسخ كما هو إن وُجد
- [x] `scale_video` + `mux_audio` (فيديو copy + صوت AAC + shortest) + `extract_thumbnail`
      (إطار واحد بجودة q=2) — كلها لمتطلبات التجميع والرندر
- [x] **probe عبر PyAV fallback**: لا حاجة لثنائي ffprobe — نفس شكل المخرجات
      تماماً (استُخدمت مكتبة av المجمعة؛ أضيفت لـ requirements)
- [x] (image_to_video وmix_audio نُفّذا فعلاً في PHASE 8 و10)
- [x] 11 اختباراً سلوكياً: أبعاد/مدد مقيسة بـ probe، والحرق يُثبَت **بتغير بكسلات
      الإطار فعلاً** قبل/بعد ✅ — 236 إجمالاً

## PHASE 13 — Rendering Pipeline ✅
- [x] `services/render_service.py` — الرندر النهائي الحقيقي: ضمان مقاطع كل
      المشاهد (بديل Ken Burns للصور فقط) → concat بتطبيع → مسار صوتي كامل
      (mix لكل مشهد مع pad/trim لمدة المشهد + صمت حقيقي للفارغ) → mux AAC →
      **حرق الترجمة** (force_style من SubtitleSettings أو styling مدمج لـ ASS)
      → thumbnail → `output/final.mp4` + حالات COMPLETED/DONE
- [x] `build_standard_pipeline` (services/standard_pipeline.py) — 13 مرحلة حقيقية
       بأوزان PIPELINE_PLAN: script→scenes→prompts→images→videos→voice→sfx→mix→
       subtitles→timeline→render→export (render_info.json + تسجيل DB + حدث
       render.completed)
- [x] **تفعيل زر 🎬 Generate Everything** — مهممة خلفية واحدة تشغّل الـ pipeline
      كاملاً بتقدم حقيقي موزون؛ كل مرحلة بكاشها
- [x] **Resume بعد الإغلاق**: إعادة التشغيل تتخطى المراحل المنتهية عبر كاش
      الخدمات (مُثبت باختبار) + `ProjectManager.export_package` حقيقي
- [x] `FFmpegEngine.concat_audio` (pad/trim لكل مقطع ثم دمج) — القطعة الناقصة
- [ ] Batch queue (100 فكرة) — مؤجل لما بعد PHASE 14-15 (أولوية المخرج النهائي)
- [x] 9 اختبارات جديدة أهمها **E2E: فكرة مجردة → final.mp4** عبر كل المراحل
      الحقيقية + استئناف + سقوط مشاهد ناقصة الأصول ✅ — 245 إجمالاً

## PHASE 14 — SEO ⬜
- [ ] SEO Generator (title/description/tags/hashtags/chapters) قابل للتحرير

## PHASE 15 — Thumbnail ⬜
- [ ] مولّد 1280×720 + نص جريء + قابل للتحرير

## PHASE 16 — Testing موسّع ⬜
- [ ] اختبارات تكامل Pipeline كاملة في Demo Mode على مدخلات حقيقية (ffmpeg فعلي)

## PHASE 17 — Packaging ⬜
- [ ] PyInstaller + تعليمات التوزيع

---

## قرارات هندسية مسجّلة
1. **الجذر:** حزمة `ai_video_factory/` + مشغّل رفيع `app.py` (يدعم أيضاً `python -m ai_video_factory`).
2. **مصدر الحقيقة:** `project.json` هو المرجع، وقاعدة SQLite مرآة للqueries/الاستئناف.
3. **Free-First:** الترتيب LOCAL→FREE→PAID مفروض في السجل، والسلاسل في `default_chain()`.
4. **لا وظائف وهمية:** كل مزود غير منفّذ يرفع `ProviderNotImplementedError` مع رقم المرحلة،
   وزر Generate Everything معطّل حتى تسليم PHASE 13.
5. **الكود متوافق مع Python 3.11+** (بيئة التطوير الحالية 3.11.2، والهدف الإنتاجي 3.12+).
6. **FFmpeg احتياطي:** `imageio-ffmpeg` للتطوير/الاختبار فقط؛ التثبيت الفعلي يُوثّق في README.
7. **GUI لا يتجمد:** كل عمل ثقيل في TaskManager (خيوط) والتقدم عبر EventBus→QtBridge (queued).
8. **headless testing:** `scripts/setup_qt_stubs.sh` يبني stubs للمكتبات الناقصة في الحاويات فقط
   (ليست مطلوبة على أجهزة حقيقية).
9. **Fallback الـ LLM:** السلسلة تتبع LOCAL→FREE→PAID بين المزودين المنفّذين والمُهيّأين فقط؛
   مزوّد `demo` لا يُستخدم تلقائياً إلا كملاذ أخير (حتى لا يخفي أعطال المزودين الحقيقيين).
