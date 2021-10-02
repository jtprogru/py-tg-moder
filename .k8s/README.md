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

## Разворачиваем бота

Чтобы развернуть бота в K8s достаточно выполнить это:

```bash
kubectl apply -f deployment.yaml
```


