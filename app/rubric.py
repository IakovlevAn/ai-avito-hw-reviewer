from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    code: str
    section: str
    title: str
    max_points: int
    rule: str
    qualitative: bool = False


RUBRIC: tuple[Criterion, ...] = (
    Criterion("foundation.structure", "Базовый сервис", "Понятная структура проекта", 5, "project_structure"),
    Criterion("foundation.http", "Базовый сервис", "HTTP-сервер запускается", 4, "http_server"),
    Criterion("foundation.env", "Базовый сервис", "Порт читается из окружения", 3, "port_env"),
    Criterion("foundation.flag", "Базовый сервис", "Порт можно изменить флагом запуска", 4, "port_flag"),
    Criterion("foundation.ping", "Базовый сервис", "Проверочная ручка возвращает pong", 4, "ping"),
    Criterion("foundation.health", "Базовый сервис", "Проверка состояния возвращает ответ без тела", 3, "healthcheck"),
    Criterion("foundation.shutdown", "Базовый сервис", "Сервис корректно завершает работу", 4, "graceful_shutdown"),
    Criterion("foundation.log", "Базовый сервис", "При завершении записывается требуемое сообщение", 1, "shutdown_log"),
    Criterion("foundation.readability", "Базовый сервис", "Код читаем и не содержит явных критических дефектов", 2, "readability", True),
    Criterion("data.postgres", "Данные и API", "Подключение к PostgreSQL настраивается", 5, "postgres"),
    Criterion("data.migrations", "Данные и API", "Схема базы создаётся миграциями", 6, "goose"),
    Criterion("data.schema", "Данные и API", "Таблица курьеров соответствует условию", 5, "courier_schema"),
    Criterion("data.get_one", "Данные и API", "Можно получить одного курьера", 5, "get_courier"),
    Criterion("data.get_all", "Данные и API", "Можно получить список курьеров", 3, "get_couriers"),
    Criterion("data.create", "Данные и API", "Можно создать курьера с требуемыми проверками", 6, "post_courier"),
    Criterion("data.update", "Данные и API", "Можно обновить курьера с требуемыми проверками", 5, "put_courier"),
    Criterion("data.sql_safety", "Данные и API", "SQL-запросы используют параметры", 3, "sql_placeholders"),
    Criterion("data.errors", "Данные и API", "Ошибки и ресурсы обрабатываются корректно", 2, "error_handling", True),
    Criterion("architecture.layers", "Архитектура", "Код разделён на понятные слои", 7, "layers"),
    Criterion("architecture.handler_contract", "Архитектура", "HTTP-слой работает через интерфейс", 4, "handler_interface"),
    Criterion("architecture.repository_contract", "Архитектура", "Бизнес-логика работает с базой через интерфейс", 4, "repository_interface"),
    Criterion("architecture.di", "Архитектура", "Зависимости передаются через конструкторы", 5, "constructors"),
    Criterion("architecture.wiring", "Архитектура", "Зависимости собираются в точке запуска", 3, "main_wiring"),
    Criterion("architecture.quality", "Архитектура", "Решение не переусложнено и не дублирует логику", 5, "architecture_quality", True),
    Criterion("architecture.works", "Архитектура", "После изменений проект продолжает работать", 2, "tests"),
)


TOTAL_POINTS = sum(item.max_points for item in RUBRIC)
