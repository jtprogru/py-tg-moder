# K8s

Как запустить этого бота в Kubernetes.

## Чокуда

Идем к [BotFather](https://t.me/BotFather), создаем бота и получаем токен.

## Создаем секрет

В секрете у нас хранится токен для запуска бота. Создать его можно так:

```bash
echo '1234567890:tokentString' | base64

MTIzNDU2Nzg5MDplcnR5dWlpdXl0cmUK
```

Получившаяся строка и есть наш зашифрованный в `base64` токен.

Берем эту строку и запихиваем в файлик `secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: py-tg-moder-secret
  type: Opaque
  data:
    tg_token: MTIzNDU2Nzg5MDplcnR5dWlpdXl0cmUK
```

И собственно говоря применяем файлик в K8s с помощью `kubectl`:

```bash
kubectl apply -f secrets.yaml
```

## Проверяем секрет

Проверить, что секрет создан корректно можно вот так:

```bash
kubectl get secret py-tg-moder-secret
```

## Авторизация в ghcr.io

Docker image для этого бота лежит НЕ в `hub.docker.com`, а в `ghcr.io`. Следовательно надо авторизоваться там вот таким образом:

```bash
kubectl create secret docker-registry ghcrio-auth-secret \ 
  --docker-username=<github_login> \
  --docker-password=<github_pat> \
  --docker-email=<github_email> \
  --docker-server=ghcr.io
```

Где надо вписать:

- `<github_login>` - твой логин от GitHub;
- `<github_pat>` - PAT который можно получить в разделе [Tokens](https://github.com/settings/tokens);
- `<github_email>` - твой email от GitHub;

## Разворачиваем бота

Чтобы развернуть бота в K8s достаточно выполнить это:

```bash
kubectl apply -f deployment.yaml
```

После чего через некоторое время (в зависимости от скорости доступа в Интернет) будет запущен бот!


