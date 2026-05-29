# Huawei B818 Control Panel

FastAPI-приложение для Raspberry Pi, которое управляет Huawei B818 и отдает базовые ручки для проверки здоровья, получения внешнего IP и ротации соединения.

## Эндпоинты

- `GET /health` - проверяет, что роутер доступен и отвечает на запрос статуса.
- `GET /status` - возвращает мониторинговый статус роутера.
- `GET /public-ip` - возвращает внешний IP адрес через `ifconfig.me`.
- `GET /mode/{mode}` - переключает режим сети на `3g` или `4g`.
- `GET /reboot` - перезагружает роутер.
- `GET /rotate` - выполняет ротацию соединения.

## Памятка по Huawei LTE API

Ниже собраны функции библиотеки, которые удобно помнить для будущих ручек или скриптов.

| Действие | Метод библиотеки |
| --- | --- |
| Проверить, отвечает ли роутер | `client.monitoring.status()` |
| Включить/выключить мобильные данные | `client.dial_up.set_mobile_dataswitch(1)` / `client.dial_up.set_mobile_dataswitch(0)` |
| Переключить режим сети | `client.net.set_net_mode(...)` |
| Перезагрузить роутер | `client.device.reboot()` |

Пример для мобильных данных:

```python
from huawei_lte_api.Connection import Connection
from huawei_lte_api.Client import Client

with Connection(ROUTER_URL) as connection:
    client = Client(connection)
    client.dial_up.set_mobile_dataswitch(1)  # on
    client.dial_up.set_mobile_dataswitch(0)  # off
```

### Как работает `GET /rotate`

1. Переключает роутер в режим `3g`.
2. Перезагружает роутер.
3. Поллит состояние роутера, пока он снова не станет доступен.
4. Переключает роутер обратно в режим `4g`.
5. Снова ждёт, пока роутер ответит на проверку здоровья.

### Низкоуровневые ручки

- `GET /status` - посмотреть мониторинговый статус роутера.
- `GET /mode/3g` - переключить роутер в 3G.
- `GET /mode/4g` - переключить роутер в 4G.
- `GET /reboot` - перезагрузить роутер.

## Конфигурация

Приложение читает настройки из локального файла `.env` в корне репозитория.

Скопируй [.env.example](.env.example) в `.env` и укажи реальные значения:

```env
ROUTER_IP=192.168.8.1
ROUTER_LOGIN=admin
ROUTER_PASSWORD=your-password
APP_HOST=0.0.0.0
APP_PORT=8000
```

`ROUTER_PASSWORD` обязателен. Остальные параметры имеют значения по умолчанию.

## Запуск локально

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

После запуска приложение будет доступно на `http://127.0.0.1:8000` или на адресе, который задан в `APP_HOST` и `APP_PORT`.

## Деплой на Raspberry Pi

Для повторяемого деплоя есть Ansible-скелет в [deploy/ansible](deploy/ansible/README.md).