,# מסמך TODO – Coach Agent

> רשימת משימות לפי Phase, מבוססת על ה-Roadmap ב-[מסמך דרישות.md](מסמך%20דרישות.md) וה-[מסמך ארכיטקטורה.md](מסמך%20ארכיטקטורה.md). טיוטה — Phase 1 מפורק לפרטים, שאר ה-Phases ברמת כותרת בלבד ויפורקו בתורם.

## Phase 1 — סוכן בסיסי בצ'אט (טלגרם) + זיכרון פר-משתמש

**היקף:** לולאת שיחה בסיסית מקצה לקצה. **בלי** tools (לא Nutrition, לא Food Log, לא Document). **בלי** DB — קבצים בלבד. משתמש יחיד.

**החלטות נעולות לשלב הזה:**

- ערוץ: טלגרם בלבד 
- הרצה: polling
- אחסון מסמך הוראות למשתמש: קובץ (JSON/Markdown) לפי `user_id`, לא DB.
- סטאק: Python + `python-telegram-bot` + Anthropic SDK + LangGraph (שכבת התזמור/agent orchestration נבנית כגרף — nodes/edges/state — במקום agent loop ידני).

**משימות:**

- [x] שלד repo — תיקיית פרויקט, `.env` (Telegram token, Anthropic API key), `requirements.txt`.
- [x] Telegram skeleton — בוט שמקבל הודעה ומחזיר echo (בלי LLM), לוודא שהחיבור עובד.
- [x] Claude API wrapper — פונקציה `call_agent(messages, system_prompt) -> reply`, נבדקת בנפרד מטלגרם.
- [x] LangGraph graph בסיסי — הקמת graph פשוט (node אחד לפי שלב: assemble prompt → קריאה ל-LLM → תשובה) שעוטף את `call_agent`, כבסיס להרחבה עתידית (tools, ענפים מותנים) ב-Phase 2 ואילך.
- [x] חיבור ל-LangSmith — הפעלת tracing על ה-LangGraph graph (משתני סביבה `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY`), כדי לראות בפועל את זרימת ה-nodes, הפרומפטים והתשובות של כל אינטראקציה.
- [x] קובץ `general_instructions.md` — מסמך הוראות כללי (אישיות, כללי עבודה, גבולות, סגנון אימון).
- [x] קובץ הוראות פר-משתמש — `users/{user_id}.md` (מטרות, מגבלות, היסטוריה בסיסית). (Phase 1: משתמש יחיד, קובץ קבוע `users/gili.md`; מעבר ל-ID דינמי כשתהיה תמיכה ברב-משתמשים.)
- [x] הרכבת prompt — מיזוג general + user לכדי system prompt אחד.
- [x] זיכרון שיחה קצר-טווח — `dict[user_id] -> list[messages]` בזיכרון (לא persistent, נעלם בריסטארט — מקובל לשלב זה).
- [x] חיבור מלא — הודעה נכנסת מטלגרם → prompt assembly → Claude → תשובה → טלגרם.
- [x] בדיקה ידנית — שינוי `users/<id>.md` ווידוא שהתגובה משתנה בהתאם.
- [x] Dockerfile בסיסי — הרצת הבוט (polling) בתוך container במקום ישירות על המחשב; היכרות מוקדמת עם Docker גם אם עדיין אין orchestration אמיתי (זה מגיע ב-Phase 7 עם Kubernetes). כולל `.dockerignore` שמוציא במפורש את `coach_agent/users/*.md` מה-image (נתונים אישיים — מגיעים ב-runtime דרך volume mount, לא build-time).

**יציאה מה-Phase (Definition of Done):** אפשר לשוחח עם הסוכן דרך טלגרם, הוא עונה לפי ההוראות הכלליות + הוראות פר-משתמש, זוכר את השיחה הנוכחית, שכבת התזמור בנויה כ-LangGraph graph עם tracing ב-LangSmith, והכל רץ בתוך Docker container.

## Phase 2 — חיבור ל-API לבדיקת ערכים תזונתיים

- [x] בחירת ספק API — **USDA FoodData Central** (הושוותה מול Open Food Facts: OFF חזק בברקודים/מוצרים ישראליים אבל חלש במזון גנרי לא-ממותג כמו פרי בודד; USDA הפוך — נבחר USDA כי מזון גנרי היה החשוב יותר. חיפוש לפי ברקוד ב-USDA ממומש כ-full-text search + התאמת `gtinUpc`, כי אין endpoint ייעודי).
- [x] Nutrition Lookup Tool + חיבורו ל-tool-use של ה-LLM (`coach_agent/nutrition.py`, ענף מותנה חדש ב-`graph.py`). כולל גם חיפוש לפי ברקוד (טקסט בלבד — קלט תמונה/סריקה נדחה לעתיד).
- [x] בדיקה: המשתמש שואל "כמה קלוריות בבננה" והסוכן עונה דרך ה-API. נבדק גם עם ברקוד אמיתי ועם זיכרון רב-פנייתי (multi-turn) כדי לוודא שהזיכרון לא נשבר עם הודעות tool-use.

## Phase 3 — זיכרון טבלאי / יומן תזונה

- [ ] בחירת מסד נתונים (SQLite לשלב זה, מעבר ל-Postgres בעתיד אם צריך).
- [ ] סכמה ליומן (טבלה אחת, `meal_type` כעמודה — ראו [[dividing-food-log-table]]).
- [ ] Food Log Tool — כתיבה וקריאה.
- [ ] בדיקה: "אכלתי 2 ביצים" → נרשם; "מה אכלתי היום" → משוחזר מהיומן.

## Phase 4 — פריסה לענן (Cloud Deployment)

**היקף:** הוצאת הבוט (שכבר בנוי כ-Docker container בסוף Phase 1) מהמחשב האישי להרצה רציפה (24/7) בענן. שינוי תשתיתי בלבד — **בלי** שינוי בלוגיקת הסוכן, בלי tools חדשים.

**החלטות נעולות לשלב הזה:**

- ספק ענן: **AWS — EC2 instance**. שים לב: ה-Free Tier של AWS מוגבל בזמן (בניגוד ל-Always Free של Oracle), ואחרי שהוא נגמר המכונה מתחילה לעלות כסף (~5-10$ לחודש). נבחר בכל זאת במודע, מתוך רצון ללמוד את ספק הענן הנפוץ בתעשייה.
- הרצה: polling נשאר כמו שהוא (לא עוברים ל-webhook) — אין צורך ב-endpoint ציבורי/HTTPS.
- שיטת פריסה: SSH ל-instance + הרצת ה-container שכבר קיים מ-Phase 1 (`docker run`/`docker compose`), לא CI/CD אוטומטי בשלב הזה.
- ניהול secrets: קובץ `.env` על המכונה + `--env-file`. **לא** Secrets Manager / SSM Parameter Store בשלב הזה (נשקל שוב ב-Phase 7, כשתהיה תשתית אמיתית).
- ארכיטקטורת מעבד: אם ייבחר instance מסוג Graviton/ARM (`t4g`) — ה-image צריך להיבנות ל-`linux/arm64` (`docker buildx`). ב-instance x86 (`t3`) ה-image הקיים מ-Phase 1 עובד כמו שהוא.

**משימות:**

- [ ] הקמת חשבון AWS + **הגדרת Budget Alarm לפני כל דבר אחר** — ה-Free Tier נגמר בשקט ו-AWS ממשיך לחייב בלי להתריע.
- [ ] יצירת Key Pair + הפעלת EC2 instance (בחירת region, AMI, ו-instance type — `t3.micro` / `t4g.micro`).
- [ ] Security Group — לאפשר SSH נכנס בלבד (רצוי מוגבל ל-IP שלך). אין צורך בפורטים נכנסים נוספים כי מדובר ב-polling.
- [ ] התקנת Docker על ה-instance.
- [ ] העברת `.env` ל-instance ב-`scp` (Telegram token, Anthropic API key, LangSmith key) — לא דרך git.
- [ ] העלאת ה-image ל-instance — build מקומי + push ל-ECR, או build ישירות על ה-instance (להחליט בזמן העבודה). לוודא התאמת architecture.
- [ ] פריסת ה-container עם `--env-file .env`.
- [ ] מדיניות restart — `--restart unless-stopped` (או systemd service) כדי שהבוט יקום אוטומטית אחרי reboot/crash של ה-instance.
- [ ] גישה בסיסית ללוגים — איך בודקים `docker logs` מרחוק דרך SSH כשמשהו משתבש.
- [ ] בדיקת קבלה — הבוט מגיב בטלגרם לאורך זמן כשהמחשב האישי כבוי לגמרי.

**יציאה מה-Phase (Definition of Done):** הבוט רץ ברציפות על EC2 instance ב-AWS ללא תלות במחשב האישי, שורד restart של ה-instance, ויש Budget Alarm פעיל שמתריע לפני חיוב לא צפוי.

## Phase 5 — תמיכה ברב-משתתפים (Multi-user)

**היקף:** המעבר ממשתמש יחיד קבוע (`users/gili.md`) לריבוי משתמשים בו-זמנית על אותו בוט, כל אחד עם הוראות, זיכרון שיחה ויומן תזונה מבודדים משלו. בונה על ה-user_id שכבר קיים כמנגנון (Phase 1) וה-DB שהוקם ב-Phase 3.

**משימות:**

- [ ] מעבר מקובץ הוראות קבוע (`users/gili.md`) ל-user_id דינמי לפי Telegram chat_id.
- [ ] תהליך onboarding — זיהוי משתמש חדש שפונה לראשונה לבוט, ויצירת קובץ/רשומת הוראות עבורו.
- [ ] בידוד זיכרון שיחה קצר-טווח בין משתמשים שונים הפעילים בו-זמנית (`dict[user_id] -> messages`, לוודא שאין דליפה בין שיחות).
- [ ] בידוד יומן התזונה (Phase 3) פר-משתמש במסד הנתונים.
- [ ] בדיקת קבלה — שני משתמשים שונים משוחחים עם הבוט במקביל, כל אחד מקבל תשובות לפי ההיסטוריה וההוראות האישיות שלו בלבד.

**יציאה מה-Phase (Definition of Done):** מספר משתמשים יכולים לשוחח עם אותו בוט בו-זמנית, כל אחד עם הוראות, זיכרון שיחה ויומן תזונה נפרדים ומבודדים לחלוטין.

## Phase 6 — הכנת מסמכים משותפת (מטרות/דיאגרמות)

- [ ] הגדרת פורמט אחסון למסמכים (קבצים בסגנון Markdown, כמו מסמכי הפרויקט עצמו).
- [ ] Document Tool — יצירה/עריכה/שליפה.
- [ ] תהליך שיחה מודרך ליצירת מסמך מטרות.

## Phase 7 — מעבר לפלטפורמה רחבה יותר (ווב/אפליקציה)

- [ ] בחירת טכנולוגיית ממשק.
- [ ] שכבת ממשק חדשה שמדברת מול אותו Agent Orchestrator (ללא שינוי בליבה — זו הנקודה של שכבת הממשק המנותקת).
- [ ] מעבר מ-in-memory/קבצים ל-DB אמיתי אם עוד לא בוצע.
- [ ] Kubernetes — פריסה/orchestration בסקאלה (multi-user, high availability), כתחליף ל-instance הבודד מ-Phase 4.

## Phase 8 — תפעול ועלות (Cost & Latency Management)

- [ ] מעקב טוקנים/עלות — לוג של input/output tokens לכל קריאה ל-LLM, וחישוב עלות משוערת לפי תעריפי המודל.
- [ ] Prompt caching — שימוש ב-prompt caching של Claude API על חלקי הפרומפט הקבועים (הוראות כלליות/פר-משתמש) כדי לחסוך עלות ו-latency.
- [ ] בחירת מודל לפי משימה — למשל Haiku לשיחה פשוטה מול Sonnet/Opus למשימות מורכבות יותר (ניתוח תזונתי, הכנת מסמך).
- [ ] מדידת latency — זמן תגובה מקצה לקצה (הודעה נכנסת → תשובה), איתור צוואר הבקבוק (LLM call מול tool calls מול DB).
- [ ] Dashboard/ניטור בסיסי — ריכוז מדדי עלות/latency/שימוש, למשל דרך LangSmith או לוג מובנה.