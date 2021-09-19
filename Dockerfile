FROM python:3.9-slim-buster

WORKDIR /bot
ARG TOKEN
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TELEGRAM_BOT_TOKEN=$TOKEN

RUN apt-get update \
    && apt-get install gcc python3-dev -y \
    && pip install --upgrade pip

COPY ./requirements.txt .
RUN pip3 install -r requirements.txt

COPY ./entrypoint.sh .

COPY ./src/ .

ENTRYPOINT ["/bot/entrypoint.sh"]
