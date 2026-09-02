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
- [ ] Telegram skeleton — בוט שמקבל הודעה ומחזיר echo (בלי LLM), לוודא שהחיבור עובד.
- [ ] Claude API wrapper — פונקציה `call_agent(messages, system_prompt) -> reply`, נבדקת בנפרד מטלגרם.
- [ ] LangGraph graph בסיסי — הקמת graph פשוט (node אחד לפי שלב: assemble prompt → קריאה ל-LLM → תשובה) שעוטף את `call_agent`, כבסיס להרחבה עתידית (tools, ענפים מותנים) ב-Phase 2 ואילך.
- [ ] חיבור ל-LangSmith — הפעלת tracing על ה-LangGraph graph (משתני סביבה `LANGCHAIN_TRACING_V2`/`LANGCHAIN_API_KEY`), כדי לראות בפועל את זרימת ה-nodes, הפרומפטים והתשובות של כל אינטראקציה.
- [ ] קובץ `general_instructions.md` — מסמך הוראות כללי (אישיות, כללי עבודה, גבולות, סגנון אימון).
- [ ] קובץ הוראות פר-משתמש — `users/{user_id}.md` (מטרות, מגבלות, היסטוריה בסיסית).
- [ ] הרכבת prompt — מיזוג general + user לכדי system prompt אחד.
- [ ] זיכרון שיחה קצר-טווח — `dict[user_id] -> list[messages]` בזיכרון (לא persistent, נעלם בריסטארט — מקובל לשלב זה).
- [ ] חיבור מלא — הודעה נכנסת מטלגרם → prompt assembly → Claude → תשובה → טלגרם.
- [ ] בדיקה ידנית — שינוי `users/<id>.md` ווידוא שהתגובה משתנה בהתאם.
- [ ] Dockerfile בסיסי — הרצת הבוט (polling) בתוך container במקום ישירות על המחשב; היכרות מוקדמת עם Docker גם אם עדיין אין orchestration אמיתי (זה מגיע ב-Phase 5 עם Kubernetes).

**יציאה מה-Phase (Definition of Done):** אפשר לשוחח עם הסוכן דרך טלגרם, הוא עונה לפי ההוראות הכלליות + הוראות פר-משתמש, זוכר את השיחה הנוכחית, שכבת התזמור בנויה כ-LangGraph graph עם tracing ב-LangSmith, והכל רץ בתוך Docker container.

## Phase 2 — חיבור ל-API לבדיקת ערכים תזונתיים
- [ ] בחירת ספק API (מענה לשאלה הפתוחה: אילו ערכים בדיוק — קלוריות/מאקרו/מיקרו).
- [ ] Nutrition Lookup Tool + חיבורו ל-tool-use של ה-LLM.
- [ ] בדיקה: המשתמש שואל "כמה קלוריות בבננה" והסוכן עונה דרך ה-API.

## Phase 3 — זיכרון טבלאי / יומן תזונה
- [ ] בחירת מסד נתונים (SQLite לשלב זה, מעבר ל-Postgres בעתיד אם צריך).
- [ ] סכמה ליומן (טבלה אחת, `meal_type` כעמודה — ראו [[dividing-food-log-table]]).
- [ ] Food Log Tool — כתיבה וקריאה.
- [ ] בדיקה: "אכלתי 2 ביצים" → נרשם; "מה אכלתי היום" → משוחזר מהיומן.

## Phase 4 — הכנת מסמכים משותפת (מטרות/דיאגרמות)
- [ ] הגדרת פורמט אחסון למסמכים (קבצים בסגנון Markdown, כמו מסמכי הפרויקט עצמו).
- [ ] Document Tool — יצירה/עריכה/שליפה.
- [ ] תהליך שיחה מודרך ליצירת מסמך מטרות.

## Phase 5 — מעבר לפלטפורמה רחבה יותר (ווב/אפליקציה)
- [ ] בחירת טכנולוגיית ממשק.
- [ ] שכבת ממשק חדשה שמדברת מול אותו Agent Orchestrator (ללא שינוי בליבה — זו הנקודה של שכבת הממשק המנותקת).
- [ ] מעבר מ-in-memory/קבצים ל-DB אמיתי אם עוד לא בוצע.
- [ ] Docker — הרצת האפליקציה כ-container (Dockerfile, image build).
- [ ] Kubernetes — פריסה/orchestration בסקאלה (multi-user, high availability).

## Phase 6 — תפעול ועלות (Cost & Latency Management)
- [ ] מעקב טוקנים/עלות — לוג של input/output tokens לכל קריאה ל-LLM, וחישוב עלות משוערת לפי תעריפי המודל.
- [ ] Prompt caching — שימוש ב-prompt caching של Claude API על חלקי הפרומפט הקבועים (הוראות כלליות/פר-משתמש) כדי לחסוך עלות ו-latency.
- [ ] בחירת מודל לפי משימה — למשל Haiku לשיחה פשוטה מול Sonnet/Opus למשימות מורכבות יותר (ניתוח תזונתי, הכנת מסמך).
- [ ] מדידת latency — זמן תגובה מקצה לקצה (הודעה נכנסת → תשובה), איתור צוואר הבקבוק (LLM call מול tool calls מול DB).
- [ ] Dashboard/ניטור בסיסי — ריכוז מדדי עלות/latency/שימוש, למשל דרך LangSmith או לוג מובנה.
