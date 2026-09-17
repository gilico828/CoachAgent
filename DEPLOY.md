# DEPLOY — הרצת הבוט על השרת

הבוט רץ 24/7 על EC2 instance ב-AWS (region `eu-central-1`, Ubuntu 24.04, x86_64),
כ-container יחיד שמנוהל ב-`docker-compose.yml`. הרצה ב-polling — אין endpoint ציבורי
ואין פורטים נכנסים חוץ מ-SSH.

## התחברות

```powershell
ssh -i "$env:USERPROFILE\.ssh\coach-agent-key.pem" ubuntu@<PUBLIC_IP>
```

המפתח הפרטי יושב ב-`~/.ssh/coach-agent-key.pem` ואין לו עותק אצל AWS. אין בפרויקט
העתק שלו וגם לא אמור להיות.

## מה יושב על השרת

```
~/CoachAgent/            # git clone של ה-repo
├── .env                 # לא ב-git — מגיע ב-scp
└── data/users/gili.md   # לא ב-git ולא ב-image — מגיע ב-scp, מחובר כ-volume
```

שני הקבצים האלה מוחרגים במכוון: `.env` מכיל מפתחות, ו-`gili.md` הוא מידע אישי
שאסור שייאפה לתוך image. הם מועברים ידנית:

```powershell
cd (Get-Item "$env:USERPROFILE\OneDrive\*\CoathAgent").FullName
$key = "$env:USERPROFILE\.ssh\coach-agent-key.pem"
scp -i $key .env ubuntu@<PUBLIC_IP>:~/CoachAgent/.env
scp -i $key coach_agent/users/gili.md ubuntu@<PUBLIC_IP>:~/CoachAgent/data/users/gili.md
```

**כשמוסיפים מפתח חדש ל-`.env` המקומי — חייבים scp מחדש.** `config.py` קורא כל
מפתח עם `os.environ[...]`, כך ש-`.env` חסר-מפתח מפיל את הקונטיינר ב-import עם
`KeyError`, לפני שורת לוג אחת משלנו. הסימן מבחוץ זהה לכל תקלה אחרת ב-polling:
הבוט פשוט שותק. `GROQ_API_KEY` (תמלול קולי, Phase 10) הוא המקרה האחרון שבו זה
רלוונטי — deploy של הגרסה הזו בלי לעדכן את `.env` בשרת ייכשל בהפעלה.

## עדכון גרסה

```bash
cd ~/CoachAgent
git pull
docker compose up -d --build
docker compose ps          # STATUS = Up
docker compose logs --tail 20
```

**הפריסה לא נגמרת ב-`Built`.** `docker compose up` מסיים בהצלחה גם כשהבוט קורס
ב-import מיד אחרי, כי מבחינת docker ה-container אכן עלה. הקריסה מופיעה רק בלוג,
וב-polling אין פורט שייכשל ואין בקשה שתחזיר שגיאה — הסימן היחיד מבחוץ הוא שהבוט
מפסיק לענות בטלגרם. שתי השורות האחרונות הן חלק מהפריסה, לא בדיקה אופציונלית.

לוודא `RestartCount=0` — container שקורס בלולאה מציג `Up` בין נפילה לנפילה:

```bash
docker inspect coachagent-bot-1 --format "{{.RestartCount}}"
```

## סטטוס ולוגים

```bash
cd ~/CoachAgent
docker compose ps        # מחפשים STATUS = Up
docker compose logs -f   # Ctrl+C עוצר את הצפייה, לא את הבוט
```

## אחרי reboot

לא צריך לעשות כלום. `docker` מופעל ב-boot ול-container יש `restart: unless-stopped`.
**שתי השכבות נדרשות** — אם רק אחת מוגדרת, הבוט ייעלם בשקט אחרי אתחול.

נבדק בפועל: אחרי `sudo reboot` ה-container חזר לבד תוך שנייה.

## התקלות שיקרו

**SSH נתקע בלי שגיאה ברורה.** ספק האינטרנט החליף לך IP בבית, וה-Security Group
עדיין מכיר את הישן. מעדכנים את הכלל בקונסולה (EC2 → Security Groups → Inbound rules
→ `My IP`). **הבעיה לא בשרת** — זה המקום שמבזבזים בו הכי הרבה זמן בחיפוש במקום הלא נכון.

**הכתובת של השרת השתנתה.** `reboot` שומר על ה-IP, אבל `stop` ואחריו `start` מקצה
כתובת חדשה. אם עוצרים את ה-instance מדי פעם — שווה להצמיד Elastic IP.

**ה-container קורס ב-`FileNotFoundError`.** `data/users/gili.md` חסר. הוא לא מגיע
עם `git clone` ולא נמצא ב-image — צריך `scp` כמו למעלה.

**ה-container קורס ב-`AttributeError` או `ImportError` אחרי rebuild שעבר חלק.**
תלות לא נעולה ב-`requirements.txt` קיבלה גרסה חדשה. `--build` מריץ `pip install`
מחדש ומושך את **העדכני ביותר** שמותר לפי הקובץ — כלומר הגרסאות נקבעות בזמן
ה-build, לא בזמן הכתיבה. שני rebuild של אותו commit בדיוק יכולים להוליד שני
image שונים.

זה קרה בפועל: `anthropic` היה ללא נעילה, rebuild משך את 1.0 שהסירה את
Text Completions API, ו-`wrap_anthropic` של langsmith עדיין ניגש ל-
`client.completions` — הבוט קרס ב-import לפני שהגיע לטלגרם. הקוד לא השתנה;
**rebuild לבדו הספיק.**

מזהים לפי כך שה-traceback יושב בתוך `site-packages` ולא בקוד שלנו. מאבחנים
בהשוואה מול ה-image הקודם:

```bash
docker compose exec bot pip freeze
```

מתקנים בנעילת הגרסה ב-`requirements.txt` — לא בהתקנה ידנית בתוך ה-container,
שנמחקת ב-rebuild הבא.

⚠️ **אין rollback ל-image הקודם.** `--build` דורס את התג `coachagent-bot:latest`,
והישן נשאר dangling ונמחק ב-prune. עד שיהיה registry, הדרך חזרה היא לנעול את
הגרסה ולבנות מחדש — ולכן שווה להסתכל בלוג *לפני* שסוגרים את הטרמינל.

## מה שלא נעשה כאן, במכוון

- **ECR** — ה-repo ציבורי, אז ה-image נבנה על ה-instance אחרי `git clone`. אין צורך
  ב-registry, ו-`git pull` מספיק לעדכון.
- **Secrets Manager / SSM** — `.env` מספיק למשתמש יחיד על מכונה אחת. נשקל שוב ב-Phase 7.
- **CI/CD** — פריסה ידנית. אין עדיין מה להצדיק pipeline.
- **lockfile (`pip-compile` / `uv lock`)** — היה מונע את תקלת הגרסאות לגמרי, ולא
  רק את המקרה שכבר נשרף. הנעילות הנקודתיות ב-`requirements.txt` מטפלות בתלויות
  הישירות אבל לא בתלויות-של-תלויות, ששם הסחיפה הבאה תגיע. נכון לעכשיו זה נדחה
  כי הנעילה הנוכחית מספיקה למכונה אחת — אבל זו כנראה המשימה הבאה כשזה יכאב שוב.
- **buildx / ARM** — ה-instance הוא x86, וה-image של Phase 1 רץ כמו שהוא. יחזור אם
  נעבור ל-Graviton.

## עלות

⚠️ ה-Free Tier של AWS מוגבל בזמן. כשהוא נגמר AWS **לא מכבה כלום ולא מתריע** — הוא
פשוט מתחיל לחייב. מוגדר Budget Alarm (תבנית *Zero spend budget*) שישלח מייל בחיוב
הראשון. אם המייל הזה מגיע — זה לא ספאם.
