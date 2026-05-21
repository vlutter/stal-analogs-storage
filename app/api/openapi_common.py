"""Общие фрагменты OpenAPI-документации для Swagger."""

AUTH_DESCRIPTION = (
    "Требуется заголовок `Authorization: Bearer <API_TOKEN>`. "
    "Токен задаётся переменной окружения `API_TOKEN`."
)

COMMON_RESPONSES: dict[int, dict] = {
    403: {
        "description": "Отсутствует или неверный Bearer-токен в заголовке Authorization.",
    },
    503: {
        "description": (
            "Google Sheets временно недоступен (ошибка репозитория). "
            "Повторите запрос позже."
        ),
    },
}
