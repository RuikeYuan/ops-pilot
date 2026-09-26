FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home ops && mkdir /app/data && chown ops:ops /app/data
COPY --chown=ops:ops control ./control
COPY --chown=ops:ops web ./web
COPY --chown=ops:ops server.py ./
USER ops
EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
