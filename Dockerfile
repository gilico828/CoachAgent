FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY coach_agent/ coach_agent/

CMD ["python", "-m", "coach_agent.main"]
