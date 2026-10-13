FROM python:3.12-slim
WORKDIR /app
COPY server.py pharmacies.json PRIVACY.md ./
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
USER nobody
CMD ["python", "server.py", "--http"]
