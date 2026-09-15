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

## עדכון גרסה

```bash
cd ~/CoachAgent
git pull
docker compose up -d --build
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

## שתי התקלות שיקרו

**SSH נתקע בלי שגיאה ברורה.** ספק האינטרנט החליף לך IP בבית, וה-Security Group
עדיין מכיר את הישן. מעדכנים את הכלל בקונסולה (EC2 → Security Groups → Inbound rules
→ `My IP`). **הבעיה לא בשרת** — זה המקום שמבזבזים בו הכי הרבה זמן בחיפוש במקום הלא נכון.

**הכתובת של השרת השתנתה.** `reboot` שומר על ה-IP, אבל `stop` ואחריו `start` מקצה
כתובת חדשה. אם עוצרים את ה-instance מדי פעם — שווה להצמיד Elastic IP.

**ה-container קורס ב-`FileNotFoundError`.** `data/users/gili.md` חסר. הוא לא מגיע
עם `git clone` ולא נמצא ב-image — צריך `scp` כמו למעלה.

## מה שלא נעשה כאן, במכוון

- **ECR** — ה-repo ציבורי, אז ה-image נבנה על ה-instance אחרי `git clone`. אין צורך
  ב-registry, ו-`git pull` מספיק לעדכון.
- **Secrets Manager / SSM** — `.env` מספיק למשתמש יחיד על מכונה אחת. נשקל שוב ב-Phase 7.
- **CI/CD** — פריסה ידנית. אין עדיין מה להצדיק pipeline.
- **buildx / ARM** — ה-instance הוא x86, וה-image של Phase 1 רץ כמו שהוא. יחזור אם
  נעבור ל-Graviton.

## עלות

⚠️ ה-Free Tier של AWS מוגבל בזמן. כשהוא נגמר AWS **לא מכבה כלום ולא מתריע** — הוא
פשוט מתחיל לחייב. מוגדר Budget Alarm (תבנית *Zero spend budget*) שישלח מייל בחיוב
הראשון. אם המייל הזה מגיע — זה לא ספאם.
