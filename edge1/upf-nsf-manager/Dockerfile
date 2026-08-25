FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manager.py .
ENV PYTHONUNBUFFERED=1
ENV FORCE_COLOR=1

EXPOSE 9095
CMD ["python", "manager.py"]
