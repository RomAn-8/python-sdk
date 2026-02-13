"""MCPServer quickstart example with Yandex.Weather tool.

Run from the repository root:
    uv run mcp-server-demo/mcpserver_quickstart.py
"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from mcp.server.mcpserver import MCPServer

# Load environment variables from .env file
# Ищем .env в директории скрипта и в родительской директории (корень проекта)
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Пробуем загрузить из текущей директории
    load_dotenv()

# Create an MCP server
mcp = MCPServer("Demo")

# Словарь для перевода состояний погоды на русский
WEATHER_CONDITIONS_RU: dict[str, str] = {
    "clear": "ясно",
    "partly-cloudy": "малооблачно",
    "cloudy": "облачно с прояснениями",
    "overcast": "пасмурно",
    "drizzle": "морось",
    "light-rain": "небольшой дождь",
    "rain": "дождь",
    "moderate-rain": "умеренно сильный дождь",
    "heavy-rain": "сильный дождь",
    "continuous-heavy-rain": "длительный сильный дождь",
    "showers": "ливень",
    "wet-snow": "дождь со снегом",
    "light-snow": "небольшой снег",
    "snow": "снег",
    "snow-showers": "снегопад",
    "hail": "град",
    "thunderstorm": "гроза",
    "thunderstorm-with-rain": "гроза с дождём",
    "thunderstorm-with-hail": "гроза с градом",
}


# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


# Add a weather tool backed by Yandex.Weather
@mcp.tool()
async def get_weather(city: str, unit: str = "celsius") -> str:
    """Get real weather for a city using Yandex.Weather.

    Reads API key from YANDEX_WEATHER_API_KEY environment variable and:
    1) Resolves the city name to coordinates via Yandex Geocoder.
    2) Queries current weather from Yandex.Weather API.
    """
    city = (city or "").strip()
    if not city:
        return "Город не указан."

    api_key = os.getenv("YANDEX_WEATHER_API_KEY", "").strip()
    if not api_key:
        return "YANDEX_WEATHER_API_KEY не задан в переменных окружения."

    unit = (unit or "celsius").strip().lower()
    unit_label = "°C" if unit.startswith("c") else "°F"

    # --- 1. Геокодер: город -> координаты (используем Nominatim от OpenStreetMap) ---
    # Это бесплатный геокодер, не требует API ключа
    geocode_url = "https://nominatim.openstreetmap.org/search"
    geocode_params = {
        "q": city,
        "format": "json",
        "limit": 1,
        "accept-language": "ru",
    }
    geocode_headers = {
        "User-Agent": "MCP-Weather-Server/1.0",  # Требуется Nominatim
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            geo_resp = await client.get(
                geocode_url, params=geocode_params, headers=geocode_headers
            )
            geo_resp.raise_for_status()
            geo_data_raw: Any = geo_resp.json()
        except Exception as e:
            return f"Ошибка геокодера для города '{city}': {e}"

        try:
            if (
                not geo_data_raw
                or not isinstance(geo_data_raw, list)
                or len(geo_data_raw) == 0  # type: ignore[arg-type]
            ):
                return f"Город '{city}' не найден."

            geo_data = cast(list[dict[str, Any]], geo_data_raw)
            first_result: dict[str, Any] = geo_data[0]
            lat: str | None = first_result.get("lat")
            lon: str | None = first_result.get("lon")

            if not lat or not lon:
                return f"Не удалось получить координаты для города '{city}'."
        except Exception as e:
            return f"Не удалось разобрать координаты города '{city}': {e}"

        # --- 2. Погода по координатам ---
        weather_url = "https://api.weather.yandex.ru/v2/forecast"
        weather_params: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "limit": 1,
            "hours": False,
            "lang": "ru_RU",
        }
        weather_headers = {
            "X-Yandex-Weather-Key": api_key,
        }

        try:
            w_resp = await client.get(
                weather_url,
                params=weather_params,
                headers=weather_headers,
            )
            w_resp.raise_for_status()
            w_data: dict[str, Any] = w_resp.json()
        except Exception as e:
            return f"Ошибка запроса к API Яндекс.Погоды: {e}"

    try:
        fact = w_data["fact"]
        temp_c = fact.get("temp")
        condition_en = fact.get("condition", "нет данных")
        # Переводим состояние на русский
        condition = WEATHER_CONDITIONS_RU.get(
            condition_en, condition_en
        )  # Если нет в словаре, оставляем как есть
        humidity = fact.get("humidity")
        wind_speed = fact.get("wind_speed")
    except Exception as e:
        return f"Не удалось распарсить ответ Яндекс.Погоды: {e}"

    # Переводим в °F, если запрошена не цельсия
    if temp_c is not None and not unit.startswith("c"):
        try:
            temp_c = float(temp_c)
            temp = round((temp_c * 9 / 5) + 32)
        except Exception:
            temp = temp_c
    else:
        temp = temp_c

    parts = [
        f"Погода в {city}: {temp}{unit_label}",
        f"Состояние: {condition}",
    ]
    if humidity is not None:
        parts.append(f"Влажность: {humidity}%")
    if wind_speed is not None:
        parts.append(f"Ветер: {wind_speed} м/с")

    return "; ".join(parts)


# Add a news tool backed by NewsAPI
@mcp.tool()
async def get_news(topic: str, count: int = 5) -> str:
    """Get news articles on a specific topic using NewsAPI.
    
    Reads API key from NEWSAPI_KEY environment variable and:
    1) Queries NewsAPI for articles matching the topic.
    2) Returns top news articles in Russian language.
    
    Args:
        topic: News topic to search for (e.g., "технологии", "политика", "спорт")
        count: Number of articles to return (default: 5, max: 100)
    """
    topic = (topic or "").strip()
    if not topic:
        return "Тема новостей не указана."
    
    api_key = os.getenv("NEWSAPI_KEY", "").strip()
    if not api_key:
        return "NEWSAPI_KEY не задан в переменных окружения."
    
    # Ограничиваем количество новостей
    count = max(1, min(count, 100))
    
    # NewsAPI endpoint для поиска новостей
    news_url = "https://newsapi.org/v2/everything"
    news_params = {
        "q": topic,
        "language": "ru",
        "sortBy": "publishedAt",
        "pageSize": count,
        "apiKey": api_key,
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            news_resp = await client.get(news_url, params=news_params)
            news_resp.raise_for_status()
            news_data: dict[str, Any] = news_resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "Ошибка авторизации NewsAPI. Проверьте API ключ."
            elif e.response.status_code == 429:
                return "Превышен лимит запросов к NewsAPI. Попробуйте позже."
            return f"Ошибка запроса к NewsAPI: {e}"
        except Exception as e:
            return f"Ошибка при запросе новостей: {e}"
    
    try:
        articles = news_data.get("articles", [])
        if not articles:
            return f"Новости по теме '{topic}' не найдены."
        
        # Формируем список новостей
        news_list: list[str] = []
        for i, article in enumerate(articles[:count], 1):
            title = article.get("title", "Без заголовка")
            description = article.get("description", "")
            url = article.get("url", "")
            source = article.get("source", {}).get("name", "Неизвестный источник")
            published = article.get("publishedAt", "")
            
            # Форматируем дату (если есть)
            date_str = ""
            if published:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    date_str = dt.strftime("%d.%m.%Y %H:%M")
                except Exception:
                    date_str = published[:10] if len(published) >= 10 else ""
            
            news_item = f"{i}. {title}"
            if description:
                news_item += f"\n   {description[:200]}{'...' if len(description) > 200 else ''}"
            if source:
                news_item += f"\n   Источник: {source}"
            if date_str:
                news_item += f" ({date_str})"
            if url:
                news_item += f"\n   {url}"
            
            news_list.append(news_item)
        
        return "\n\n".join(news_list)
    
    except Exception as e:
        return f"Не удалось обработать ответ NewsAPI: {e}"


# Docker container management tools
DOCKER_WEB_DIR = Path(r"D:\vetonline\consultvet\docker-web")
DOCKER_SHOT_DIR = Path(r"D:\vetonline\consultvet\docker-shot")
SCREENSHOTS_DIR = Path(r"D:\vetonline\consultvet\screenshots")
CONTAINER_NAME = "consultvet-web"
IMAGE_WEB = "consultvet-web"
IMAGE_SHOT = "consultvet-shot"
SITE_URL = "http://localhost:8080"
SITE_URL_DOCKER = "http://host.docker.internal:8080"


@mcp.tool()
async def site_up() -> str:
    """Поднимает Docker контейнер сайта consultvet-web.
    
    Выполняет docker compose up -d web (или docker run) для поднятия контейнера.
    Затем делает healthcheck (HTTP 200) и возвращает статус + URL.
    
    Returns:
        Строка с результатом операции и URL сайта (например, http://localhost:8080)
    """
    try:
        # Проверяем, есть ли docker-compose.yml в папке docker-web
        compose_file = DOCKER_WEB_DIR / "docker-compose.yml"
        
        if compose_file.exists():
            # Используем docker compose
            process = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "up",
                "-d",
                "web",
                cwd=str(DOCKER_WEB_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Неизвестная ошибка"
                return f"Ошибка при поднятии контейнера через docker compose: {error_msg}"
        else:
            # Используем docker run
            # Проверяем, запущен ли уже контейнер
            check_running = await asyncio.create_subprocess_exec(
                "docker",
                "ps",
                "--filter",
                f"name={CONTAINER_NAME}",
                "--format",
                "{{.Names}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            check_running_stdout, _ = await check_running.communicate()
            is_running = CONTAINER_NAME in check_running_stdout.decode("utf-8", errors="ignore")
            
            if is_running:
                # Контейнер уже запущен, проверяем healthcheck
                pass
            else:
                # Проверяем, существует ли контейнер (но остановлен)
                check_exists = await asyncio.create_subprocess_exec(
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    f"name={CONTAINER_NAME}",
                    "--format",
                    "{{.Names}}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                check_exists_stdout, _ = await check_exists.communicate()
                exists = CONTAINER_NAME in check_exists_stdout.decode("utf-8", errors="ignore")
                
                if exists:
                    # Контейнер существует, но остановлен - запускаем его
                    process = await asyncio.create_subprocess_exec(
                        "docker",
                        "start",
                        CONTAINER_NAME,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode != 0:
                        error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Неизвестная ошибка"
                        return f"Ошибка при запуске существующего контейнера: {error_msg}"
                else:
                    # Контейнера нет - создаём новый
                    process = await asyncio.create_subprocess_exec(
                        "docker",
                        "run",
                        "-d",
                        "--name",
                        CONTAINER_NAME,
                        "-p",
                        "8080:80",
                        IMAGE_WEB,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode != 0:
                        error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Неизвестная ошибка"
                        return f"Ошибка при создании контейнера через docker run: {error_msg}"
        
        # Ждём немного, чтобы контейнер успел запуститься
        await asyncio.sleep(3)
        
        # Делаем healthcheck
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(SITE_URL)
                if response.status_code == 200:
                    return f"✅ Сайт успешно поднят. URL: {SITE_URL}"
                else:
                    return f"⚠️ Контейнер запущен, но сайт вернул статус {response.status_code}. URL: {SITE_URL}"
        except httpx.RequestError as e:
            return f"⚠️ Контейнер запущен, но healthcheck не прошёл: {e}. URL: {SITE_URL}"
        except Exception as e:
            return f"⚠️ Контейнер запущен, но ошибка при проверке: {e}. URL: {SITE_URL}"
            
    except Exception as e:
        return f"Ошибка при поднятии сайта: {e}"


@mcp.tool()
async def site_screenshot() -> str:
    """Создаёт скриншот сайта через одноразовый Docker контейнер.
    
    Запускает контейнер consultvet-shot, который открывает сайт,
    сохраняет PNG в примонтированную папку и завершает работу.
    
    Returns:
        Путь к сохранённому PNG файлу (например, D:\\vetonline\\consultvet\\screenshots\\site.png)
    """
    try:
        # Создаём папку для скриншотов, если её нет
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        
        screenshot_path = SCREENSHOTS_DIR / "site.png"
        
        # Запускаем одноразовый контейнер для скриншота
        # Монтируем папку скриншотов в контейнер
        # Скрипт screenshot.py ожидает: <url> <output_png>
        # output_png должен быть полным путём внутри контейнера: /screenshots/site.png
        process = await asyncio.create_subprocess_exec(
            "docker",
            "run",
            "--rm",
            "-v",
            f"{SCREENSHOTS_DIR}:/screenshots",
            IMAGE_SHOT,
            SITE_URL_DOCKER,  # URL сайта внутри контейнера (http://host.docker.internal:8080)
            "/screenshots/site.png",  # Полный путь к файлу внутри контейнера
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        
        # Декодируем вывод для отладки
        stdout_text = stdout.decode("utf-8", errors="ignore") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="ignore") if stderr else ""
        
        if process.returncode != 0:
            error_details = f"STDOUT: {stdout_text}\nSTDERR: {stderr_text}" if (stdout_text or stderr_text) else "Неизвестная ошибка"
            return f"Ошибка при создании скриншота (код {process.returncode}):\n{error_details}"
        
        # Проверяем, что файл создан
        if screenshot_path.exists():
            return str(screenshot_path)
        else:
            # Если файл не создан, но процесс завершился успешно, выводим логи для отладки
            debug_info = f"STDOUT: {stdout_text}\nSTDERR: {stderr_text}" if (stdout_text or stderr_text) else ""
            return f"⚠️ Скриншот не был создан по пути {screenshot_path}.\n{debug_info}"
            
    except Exception as e:
        return f"Ошибка при создании скриншота: {e}"


@mcp.tool()
async def site_down() -> str:
    """Останавливает Docker контейнер сайта consultvet-web.
    
    Выполняет docker compose stop web (или docker stop) для остановки контейнера.
    
    Returns:
        Строка с результатом операции
    """
    try:
        # Проверяем, есть ли docker-compose.yml в папке docker-web
        compose_file = DOCKER_WEB_DIR / "docker-compose.yml"
        
        if compose_file.exists():
            # Используем docker compose
            process = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "stop",
                "web",
                cwd=str(DOCKER_WEB_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Неизвестная ошибка"
                return f"Ошибка при остановке контейнера через docker compose: {error_msg}"
            
            return "✅ Сайт остановлен (docker compose stop web)"
        else:
            # Используем docker stop
            process = await asyncio.create_subprocess_exec(
                "docker",
                "stop",
                CONTAINER_NAME,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Неизвестная ошибка"
                # Если контейнер не найден, это тоже нормально
                if "No such container" in error_msg or "not found" in error_msg.lower():
                    return "ℹ️ Контейнер не был запущен"
                return f"Ошибка при остановке контейнера: {error_msg}"
            
            return "✅ Сайт остановлен (docker stop)"
            
    except Exception as e:
        return f"Ошибка при остановке сайта: {e}"


@mcp.tool()
async def git_branch(repo_path: str | None = None) -> str:
    """Получить текущую ветку git-репозитория.
    
    Выполняет команду 'git branch --show-current' в указанном репозитории
    или в текущей директории MCP сервера (python-sdk).
    
    Args:
        repo_path: Путь к репозиторию (опционально). Если не указан, используется
                   директория python-sdk. Можно указать абсолютный путь или путь
                   относительно текущей директории.
    
    Returns:
        Название текущей ветки или сообщение об ошибке
    """
    try:
        # Определяем путь к репозиторию
        if repo_path:
            # Если указан путь, используем его
            repo_root = Path(repo_path).resolve()
            if not repo_root.exists():
                return f"Ошибка: путь {repo_path} не существует"
            if not repo_root.is_dir():
                return f"Ошибка: {repo_path} не является директорией"
        else:
            # По умолчанию используем корень python-sdk (где находится этот файл)
            repo_root = Path(__file__).resolve().parent.parent
        
        # Выполняем git branch --show-current
        process = await asyncio.create_subprocess_exec(
            "git",
            "branch",
            "--show-current",
            cwd=str(repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="ignore") if stderr else "Неизвестная ошибка"
            # Проверяем, является ли это git репозиторием
            if "not a git repository" in error_msg.lower():
                return f"Ошибка: {repo_root} не является git репозиторием"
            return f"Ошибка при выполнении git команды: {error_msg}"
        
        branch_name = stdout.decode("utf-8", errors="ignore").strip()
        if not branch_name:
            return "Не удалось определить текущую ветку (возможно, репозиторий в detached HEAD состоянии)"
        
        return branch_name
        
    except FileNotFoundError:
        return "Ошибка: git не установлен или не найден в PATH"
    except Exception as e:
        return f"Ошибка при получении текущей ветки: {e}"


@mcp.tool()
async def get_pr_diff(owner: str, repo: str, pr_number: int, github_token: str) -> str:
    """Получить diff (unified diff) для Pull Request через GitHub API.
    
    Args:
        owner: Владелец репозитория (например, "RomAn-8")
        repo: Название репозитория (например, "nikita_ai")
        pr_number: Номер PR
        github_token: GitHub Personal Access Token или GITHUB_TOKEN
    
    Returns:
        Unified diff строка или сообщение об ошибке
    """
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = {
            "Accept": "application/vnd.github.v3.diff",
            "Authorization": f"token {github_token}",
            "User-Agent": "MCP-GitHub-Tool/1.0",
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.text
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Ошибка: PR #{pr_number} не найден в репозитории {owner}/{repo}"
        elif e.response.status_code == 401:
            return "Ошибка: Неверный GitHub token (401 Unauthorized)"
        return f"Ошибка GitHub API: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Ошибка при получении diff PR: {e}"


@mcp.tool()
async def get_pr_files(owner: str, repo: str, pr_number: int, github_token: str) -> str:
    """Получить список измененных файлов в Pull Request через GitHub API.
    
    Args:
        owner: Владелец репозитория (например, "RomAn-8")
        repo: Название репозитория (например, "nikita_ai")
        pr_number: Номер PR
        github_token: GitHub Personal Access Token или GITHUB_TOKEN
    
    Returns:
        JSON строка со списком файлов и их статусами (added, modified, removed) или сообщение об ошибке
    """
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {github_token}",
            "User-Agent": "MCP-GitHub-Tool/1.0",
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            files_data = response.json()
            
            # Форматируем результат для удобства
            result = []
            for file_info in files_data:
                result.append({
                    "filename": file_info.get("filename", ""),
                    "status": file_info.get("status", ""),  # added, modified, removed, renamed
                    "additions": file_info.get("additions", 0),
                    "deletions": file_info.get("deletions", 0),
                    "changes": file_info.get("changes", 0),
                    "patch": file_info.get("patch", ""),  # небольшой патч для контекста
                })
            
            import json
            return json.dumps(result, ensure_ascii=False, indent=2)
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Ошибка: PR #{pr_number} не найден в репозитории {owner}/{repo}"
        elif e.response.status_code == 401:
            return "Ошибка: Неверный GitHub token (401 Unauthorized)"
        return f"Ошибка GitHub API: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Ошибка при получении файлов PR: {e}"


@mcp.tool()
async def get_pr_info(owner: str, repo: str, pr_number: int, github_token: str) -> str:
    """Получить метаинформацию о Pull Request через GitHub API.
    
    Args:
        owner: Владелец репозитория (например, "RomAn-8")
        repo: Название репозитория (например, "nikita_ai")
        pr_number: Номер PR
        github_token: GitHub Personal Access Token или GITHUB_TOKEN
    
    Returns:
        JSON строка с информацией о PR (title, description, author, branches) или сообщение об ошибке
    """
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {github_token}",
            "User-Agent": "MCP-GitHub-Tool/1.0",
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            pr_data = response.json()
            
            # Извлекаем нужную информацию
            result = {
                "number": pr_data.get("number"),
                "title": pr_data.get("title", ""),
                "body": pr_data.get("body", ""),
                "state": pr_data.get("state", ""),  # open, closed
                "author": pr_data.get("user", {}).get("login", ""),
                "base_branch": pr_data.get("base", {}).get("ref", ""),
                "head_branch": pr_data.get("head", {}).get("ref", ""),
                "created_at": pr_data.get("created_at", ""),
                "updated_at": pr_data.get("updated_at", ""),
                "mergeable": pr_data.get("mergeable"),
                "draft": pr_data.get("draft", False),
            }
            
            import json
            return json.dumps(result, ensure_ascii=False, indent=2)
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Ошибка: PR #{pr_number} не найден в репозитории {owner}/{repo}"
        elif e.response.status_code == 401:
            return "Ошибка: Неверный GitHub token (401 Unauthorized)"
        return f"Ошибка GitHub API: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return f"Ошибка при получении информации о PR: {e}"


# ==================== Google Sheets Helper Functions ====================

def _get_sheets_service():
    """Создание клиента Google Sheets API с service account."""
    credentials_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "").strip()
    if not credentials_path:
        raise ValueError("GOOGLE_SHEETS_CREDENTIALS_PATH не задан в переменных окружения")
    
    creds_path = Path(credentials_path)
    if not creds_path.exists():
        raise ValueError(f"Файл credentials не найден: {credentials_path}")
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    creds = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=SCOPES
    )
    service = build('sheets', 'v4', credentials=creds)
    return service


def _get_sheet_gid(spreadsheet_id: str, sheet_name: str) -> int | None:
    """Получение GID листа для формирования deep-link."""
    try:
        service = _get_sheets_service()
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = spreadsheet.get('sheets', [])
        for sheet in sheets:
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']
        return None
    except Exception as e:
        return None


def _get_or_create_sheet_name(spreadsheet_id: str, preferred_name: str) -> str:
    """Получить название листа, если он существует, иначе вернуть первый лист или создать новый."""
    try:
        service = _get_sheets_service()
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = spreadsheet.get('sheets', [])
        
        # Проверяем, существует ли лист с предпочитаемым названием
        for sheet in sheets:
            if sheet['properties']['title'] == preferred_name:
                return preferred_name
        
        # Если лист не найден, используем первый доступный лист
        if sheets:
            return sheets[0]['properties']['title']
        
        # Если листов нет, создаем новый
        requests = [{
            'addSheet': {
                'properties': {
                    'title': preferred_name
                }
            }
        }]
        body = {'requests': requests}
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        return preferred_name
    except Exception as e:
        # В случае ошибки возвращаем предпочитаемое название
        return preferred_name


def _validate_date(date_str: str) -> bool:
    """Валидация формата даты DD-MM-YYYY."""
    if not date_str or not isinstance(date_str, str):
        return False
    pattern = r'^\d{2}-\d{2}-\d{4}$'
    if not re.match(pattern, date_str):
        return False
    try:
        day, month, year = date_str.split('-')
        datetime(int(year), int(month), int(day))
        return True
    except (ValueError, TypeError):
        return False


def _validate_time(time_str: str) -> bool:
    """Валидация формата времени HH:MM."""
    if not time_str or not isinstance(time_str, str):
        return False
    pattern = r'^\d{2}:\d{2}$'
    if not re.match(pattern, time_str):
        return False
    try:
        hour, minute = time_str.split(':')
        hour_int = int(hour)
        minute_int = int(minute)
        if hour_int < 0 or hour_int > 23 or minute_int < 0 or minute_int > 59:
            return False
        return True
    except (ValueError, TypeError):
        return False


def _find_max_reg_id(service, spreadsheet_id: str, sheet_name: str) -> int:
    """Поиск максимального ID_записи на листе 'Записи'."""
    try:
        # Читаем колонку A (ID_записи), начиная со строки 2 (пропускаем заголовок)
        range_name = f"{sheet_name}!A2:A"
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        max_id = 0
        for row in values:
            if row and row[0]:
                try:
                    reg_id = int(row[0])
                    if reg_id > max_id:
                        max_id = reg_id
                except (ValueError, TypeError):
                    continue
        return max_id
    except Exception:
        return 0


def _get_user_fio(service, spreadsheet_id: str, sheet_name: str, username: str) -> str | None:
    """Получение ФИО пользователя по username."""
    try:
        # Читаем весь лист
        range_name = f"{sheet_name}!A2:F"  # A=Username, B=ФИО (индекс 1)
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        for row in values:
            if row and len(row) > 0:
                try:
                    row_username = row[0] if len(row) > 0 else ""  # Колонка A - Username
                    if row_username == username and len(row) > 1:
                        return row[1] if row[1] else None  # Колонка B - ФИО
                except (ValueError, TypeError):
                    continue
        return None
    except Exception:
        return None


def _validate_priority(priority: str) -> bool:
    """Валидация приоритета задачи (high/middle/low)."""
    if not priority or not isinstance(priority, str):
        return False
    return priority.lower() in ["high", "middle", "low"]


# ==================== Google Sheets MCP Tools ====================

@mcp.tool()
async def user_get(username: str) -> str:
    """Получить данные пользователя по username.
    
    Args:
        username: Username пользователя из Telegram
        
    Returns:
        JSON строка с данными пользователя или сообщение об ошибке
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        sheet_name = os.getenv("SHEETS_USERS_SHEET", "Пользователи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{sheet_name}!A2:F"  # A=Username, B=ФИО, C=Телефон, D=Статус, E=Дата_регистрации, F=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        for row in values:
            if row and len(row) > 0:
                try:
                    row_username = row[0] if len(row) > 0 else ""
                    if row_username == username:
                        user_data = {
                            "username": row_username,
                            "fio": row[1] if len(row) > 1 else "",
                            "phone": row[2] if len(row) > 2 else "",
                            "status": row[3] if len(row) > 3 else "",
                            "date_reg": row[4] if len(row) > 4 else "",
                            "note": row[5] if len(row) > 5 else ""
                        }
                        return json.dumps(user_data, ensure_ascii=False)
                except (ValueError, TypeError):
                    continue
        
        return "Ошибка: Пользователь не найден"
    except Exception as e:
        return f"Ошибка при получении данных пользователя: {e}"


@mcp.tool()
async def user_register(username: str, fio: str, phone: str) -> str:
    """Зарегистрировать или обновить данные пользователя.
    
    Args:
        username: Username из Telegram
        fio: ФИО пользователя
        phone: Телефон пользователя
        
    Returns:
        JSON строка со статусом операции
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        sheet_name = os.getenv("SHEETS_USERS_SHEET", "Пользователи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{sheet_name}!A2:F"  # A=Username, B=ФИО, C=Телефон, D=Статус, E=Дата_регистрации, F=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        # Ищем пользователя
        row_index = None
        for i, row in enumerate(values):
            if row and len(row) > 0:
                try:
                    row_username = row[0] if len(row) > 0 else ""
                    if row_username == username:
                        row_index = i + 2  # +2 потому что начинаем с строки 2 и индексация с 0
                        break
                except (ValueError, TypeError):
                    continue
        
        today = datetime.now().strftime("%d-%m-%Y")
        new_row = [username, fio, phone, "active", today, ""]
        
        if row_index is None:
            # Добавляем новую строку
            body = {'values': [new_row]}
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_name}!A:F",
                valueInputOption='RAW',
                body=body
            ).execute()
            return json.dumps({"status": "registered"}, ensure_ascii=False)
        else:
            # Обновляем существующую строку
            body = {'values': [new_row]}
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_name}!A{row_index}:F{row_index}",
                valueInputOption='RAW',
                body=body
            ).execute()
            return json.dumps({"status": "updated"}, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при регистрации пользователя: {e}"


@mcp.tool()
async def user_block(username: str) -> str:
    """Заблокировать пользователя.
    
    Args:
        username: Username пользователя из Telegram
        
    Returns:
        Статус операции
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        sheet_name = os.getenv("SHEETS_USERS_SHEET", "Пользователи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{sheet_name}!A2:F"  # A=Username, B=ФИО, C=Телефон, D=Статус, E=Дата_регистрации, F=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        for i, row in enumerate(values):
            if row and len(row) > 0:
                try:
                    row_username = row[0] if len(row) > 0 else ""
                    if row_username == username:
                        row_index = i + 2
                        body = {'values': [["blocked"]]}
                        service.spreadsheets().values().update(
                            spreadsheetId=spreadsheet_id,
                            range=f"{sheet_name}!D{row_index}",  # Колонка D - Статус
                            valueInputOption='RAW',
                            body=body
                        ).execute()
                        return "Пользователь заблокирован"
                except (ValueError, TypeError):
                    continue
        
        return "Ошибка: Пользователь не найден"
    except Exception as e:
        return f"Ошибка при блокировке пользователя: {e}"


@mcp.tool()
async def user_unblock(username: str) -> str:
    """Разблокировать пользователя.
    
    Args:
        username: Username пользователя из Telegram
        
    Returns:
        Статус операции
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        sheet_name = os.getenv("SHEETS_USERS_SHEET", "Пользователи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{sheet_name}!A2:F"  # A=Username, B=ФИО, C=Телефон, D=Статус, E=Дата_регистрации, F=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        for i, row in enumerate(values):
            if row and len(row) > 0:
                try:
                    row_username = row[0] if len(row) > 0 else ""
                    if row_username == username:
                        row_index = i + 2
                        body = {'values': [["active"]]}
                        service.spreadsheets().values().update(
                            spreadsheetId=spreadsheet_id,
                            range=f"{sheet_name}!D{row_index}",  # Колонка D - Статус
                            valueInputOption='RAW',
                            body=body
                        ).execute()
                        return "Пользователь разблокирован"
                except (ValueError, TypeError):
                    continue
        
        return "Ошибка: Пользователь не найден"
    except Exception as e:
        return f"Ошибка при разблокировке пользователя: {e}"


@mcp.tool()
async def user_delete(username: str) -> str:
    """Удалить регистрацию пользователя из Google Sheets.
    
    Args:
        username: Username пользователя из Telegram
        
    Returns:
        Статус операции
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        sheet_name = os.getenv("SHEETS_USERS_SHEET", "Пользователи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{sheet_name}!A2:F"  # A=Username, B=ФИО, C=Телефон, D=Статус, E=Дата_регистрации, F=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        # Получаем sheet_id для удаления строки
        sheet_gid = _get_sheet_gid(spreadsheet_id, sheet_name)
        
        for i, row in enumerate(values):
            if row and len(row) > 0:
                try:
                    row_username = row[0] if len(row) > 0 else ""
                    if row_username == username:
                        row_index = i + 2  # +2 потому что начинаем с строки 2 и индексация с 0
                        
                        # Удаляем строку через batchUpdate
                        requests = [{
                            'deleteDimension': {
                                'range': {
                                    'sheetId': sheet_gid,
                                    'dimension': 'ROWS',
                                    'startIndex': row_index - 1,  # Индексация с 0
                                    'endIndex': row_index
                                }
                            }
                        }]
                        
                        body = {'requests': requests}
                        service.spreadsheets().batchUpdate(
                            spreadsheetId=spreadsheet_id,
                            body=body
                        ).execute()
                        
                        return json.dumps({"status": "deleted", "username": username}, ensure_ascii=False)
                except (ValueError, TypeError):
                    continue
        
        return "Ошибка: Пользователь не найден"
    except Exception as e:
        return f"Ошибка при удалении пользователя: {e}"


@mcp.tool()
async def reg_create(username: str, date: str, time: str, note: str = "") -> str:
    """Создать запись на тренировку.
    
    Args:
        username: Username пользователя из Telegram
        date: Дата в формате DD-MM-YYYY
        time: Время в формате HH:MM
        note: Примечание к записи (опционально)
        
    Returns:
        JSON строка с данными созданной записи
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        users_sheet = os.getenv("SHEETS_USERS_SHEET", "Пользователи").strip()
        regs_sheet = os.getenv("SHEETS_REGS_SHEET", "Записи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        # Валидация
        if not _validate_date(date):
            return "Ошибка: Неверный формат даты. Используйте DD-MM-YYYY"
        if not _validate_time(time):
            return "Ошибка: Неверный формат времени. Используйте HH:MM"
        
        service = _get_sheets_service()
        
        # Проверка пользователя
        user_data_str = await user_get(username)
        if user_data_str.startswith("Ошибка"):
            return "Ошибка: Пользователь не найден. Сначала зарегистрируйтесь"
        
        user_data = json.loads(user_data_str)
        if user_data.get("status") == "blocked":
            return "Ошибка: Пользователь заблокирован"
        
        fio = user_data.get("fio", "")
        
        # Проверка на дубликат активной записи
        range_name = f"{regs_sheet}!A2:H"  # A=ID_записи, B=Username, C=ФИО, D=Дата, E=Время, F=Статус, G=Обновлено, H=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        for row in values:
            if row and len(row) > 5:
                try:
                    row_username = row[1] if len(row) > 1 else ""  # Колонка B - Username
                    row_date = row[3] if len(row) > 3 else ""  # Колонка D - Дата
                    row_time = row[4] if len(row) > 4 else ""  # Колонка E - Время
                    row_status = row[5] if len(row) > 5 else ""  # Колонка F - Статус
                    
                    if (row_username == username and 
                        row_date == date and 
                        row_time == time and 
                        row_status == "Активна"):
                        return "Ошибка: У вас уже есть активная запись на это время"
                except (ValueError, TypeError):
                    continue
        
        # Генерация reg_id
        max_id = _find_max_reg_id(service, spreadsheet_id, regs_sheet)
        reg_id = max_id + 1
        
        # Добавление записи
        now = datetime.now().strftime("%d-%m-%Y %H:%M")
        new_row = [reg_id, username, fio, date, time, "Активна", now, note or ""]  # A=ID, B=Username, C=ФИО, D=Дата, E=Время, F=Статус, G=Обновлено, H=Примечание
        body = {'values': [new_row]}
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{regs_sheet}!A:H",
            valueInputOption='RAW',
            body=body
        ).execute()
        
        # Получение номера строки для формирования ссылки
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{regs_sheet}!A2:A"
        ).execute()
        row_count = len(result.get('values', []))
        row_number = row_count + 1  # +1 потому что заголовок
        
        # Формирование ссылок
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        sheet_gid = _get_sheet_gid(spreadsheet_id, regs_sheet)
        if sheet_gid is not None:
            row_url = f"{sheet_url}/edit#gid={sheet_gid}&range=A{row_number}"
        else:
            row_url = sheet_url
        
        result_data = {
            "reg_id": reg_id,
            "sheet_url": sheet_url,
            "row_url": row_url,
            "date": date,
            "time": time,
            "fio": fio
        }
        return json.dumps(result_data, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при создании записи: {e}"


@mcp.tool()
async def reg_find_by_user(username: str) -> str:
    """Найти все активные записи пользователя.
    
    Args:
        username: Username пользователя из Telegram
        
    Returns:
        JSON массив записей
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        regs_sheet = os.getenv("SHEETS_REGS_SHEET", "Записи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{regs_sheet}!A2:H"  # A=ID_записи, B=Username, C=ФИО, D=Дата, E=Время, F=Статус, G=Обновлено, H=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        active_regs = []
        for row in values:
            if row and len(row) > 5:
                try:
                    row_username = row[1] if len(row) > 1 else ""  # Колонка B - Username
                    row_status = row[5] if len(row) > 5 else ""  # Колонка F - Статус
                    
                    if row_username == username and row_status == "Активна":
                        reg_data = {
                            "reg_id": int(row[0]) if row[0] else 0,
                            "date": row[3] if len(row) > 3 else "",
                            "time": row[4] if len(row) > 4 else "",
                            "status": row_status,
                            "updated": row[6] if len(row) > 6 else "",
                            "fio": row[2] if len(row) > 2 else ""
                        }
                        active_regs.append(reg_data)
                except (ValueError, TypeError):
                    continue
        
        return json.dumps(active_regs, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при поиске записей: {e}"


@mcp.tool()
async def reg_reschedule(reg_id: int, new_date: str, new_time: str) -> str:
    """Перенести запись на другое время.
    
    Args:
        reg_id: ID записи
        new_date: Новая дата в формате DD-MM-YYYY
        new_time: Новое время в формате HH:MM
        
    Returns:
        JSON строка с обновленными данными записи
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        regs_sheet = os.getenv("SHEETS_REGS_SHEET", "Записи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        # Валидация
        if not _validate_date(new_date):
            return "Ошибка: Неверный формат даты. Используйте DD-MM-YYYY"
        if not _validate_time(new_time):
            return "Ошибка: Неверный формат времени. Используйте HH:MM"
        
        service = _get_sheets_service()
        range_name = f"{regs_sheet}!A2:H"  # A=ID_записи, B=Username, C=ФИО, D=Дата, E=Время, F=Статус, G=Обновлено, H=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        row_index = None
        current_username = None
        
        for i, row in enumerate(values):
            if row and len(row) > 0:
                try:
                    row_reg_id = int(row[0])
                    if row_reg_id == reg_id:
                        row_index = i + 2
                        current_username = row[1] if len(row) > 1 else None
                        break
                except (ValueError, TypeError):
                    continue
        
        if row_index is None:
            return "Ошибка: Запись не найдена"
        
        # Проверка на конфликт с другой активной записью
        for row in values:
            if row and len(row) > 5:
                try:
                    row_reg_id = int(row[0])
                    row_username = row[1] if len(row) > 1 else ""
                    row_date = row[3] if len(row) > 3 else ""
                    row_time = row[4] if len(row) > 4 else ""
                    row_status = row[5] if len(row) > 5 else ""
                    
                    if (row_reg_id != reg_id and
                        row_username == current_username and
                        row_date == new_date and
                        row_time == new_time and
                        row_status == "Активна"):
                        return "Ошибка: У вас уже есть активная запись на это время"
                except (ValueError, TypeError):
                    continue
        
        # Обновление записи
        now = datetime.now().strftime("%d-%m-%Y %H:%M")
        # Обновляем Дата и Время
        body = {'values': [[new_date, new_time]]}
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{regs_sheet}!D{row_index}:E{row_index}",
            valueInputOption='RAW',
            body=body
        ).execute()
        # Обновляем Обновлено
        body = {'values': [[now]]}
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{regs_sheet}!G{row_index}",  # Колонка G - Обновлено
            valueInputOption='RAW',
            body=body
        ).execute()
        
        # Формирование ссылки
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        sheet_gid = _get_sheet_gid(spreadsheet_id, regs_sheet)
        if sheet_gid is not None:
            row_url = f"{sheet_url}/edit#gid={sheet_gid}&range=A{row_index}"
        else:
            row_url = sheet_url
        
        result_data = {
            "reg_id": reg_id,
            "date": new_date,
            "time": new_time,
            "status": "Активна",
            "updated": now,
            "row_url": row_url
        }
        return json.dumps(result_data, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при переносе записи: {e}"


@mcp.tool()
async def reg_cancel(reg_id: int) -> str:
    """Отменить и удалить запись из Google Sheets.
    
    Args:
        reg_id: ID записи
        
    Returns:
        Статус операции
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        regs_sheet = os.getenv("SHEETS_REGS_SHEET", "Записи").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID не задан в переменных окружения"
        
        service = _get_sheets_service()
        range_name = f"{regs_sheet}!A2:H"  # A=ID_записи, B=Username, C=ФИО, D=Дата, E=Время, F=Статус, G=Обновлено, H=Примечание
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        # Получаем sheet_id для удаления строки
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheet_gid = _get_sheet_gid(spreadsheet_id, regs_sheet)
        
        for i, row in enumerate(values):
            if row and len(row) > 0:
                try:
                    row_reg_id = int(row[0])
                    if row_reg_id == reg_id:
                        row_index = i + 2  # +2 потому что начинаем с строки 2 и индексация с 0
                        
                        # Удаляем строку через batchUpdate
                        requests = [{
                            'deleteDimension': {
                                'range': {
                                    'sheetId': sheet_gid,
                                    'dimension': 'ROWS',
                                    'startIndex': row_index - 1,  # Индексация с 0
                                    'endIndex': row_index
                                }
                            }
                        }]
                        
                        body = {'requests': requests}
                        service.spreadsheets().batchUpdate(
                            spreadsheetId=spreadsheet_id,
                            body=body
                        ).execute()
                        
                        return json.dumps({"status": "deleted", "reg_id": reg_id}, ensure_ascii=False)
                except (ValueError, TypeError):
                    continue
        
        return "Ошибка: Запись не найдена"
    except Exception as e:
        return f"Ошибка при отмене записи: {e}"


# ==================== Task Management MCP Tools ====================

@mcp.tool()
async def task_create(date: str, time: str, task: str, priority: str) -> str:
    """Создать задачу в Google Sheets.
    
    Args:
        date: Дата в формате DD-MM-YYYY
        time: Время в формате HH:MM
        task: Описание задачи
        priority: Приоритет задачи (high/middle/low)
        
    Returns:
        JSON строка с данными созданной задачи и ссылкой на строку
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID_2", "").strip()
        if not spreadsheet_id:
            # Fallback на основной spreadsheet_id, если второй не задан
            spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        preferred_sheet_name = os.getenv("SHEETS_TASKS_SHEET", "Список задач").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID_2 не задан в переменных окружения"
        
        # Валидация
        if not _validate_date(date):
            return "Ошибка: Неверный формат даты. Используйте DD-MM-YYYY"
        if not _validate_time(time):
            return "Ошибка: Неверный формат времени. Используйте HH:MM"
        if not _validate_priority(priority):
            return "Ошибка: Неверный приоритет. Используйте high, middle или low"
        
        service = _get_sheets_service()
        
        # Получаем или создаем лист
        tasks_sheet = _get_or_create_sheet_name(spreadsheet_id, preferred_sheet_name)
        
        # Добавление задачи
        # A=Статус (FALSE), B=Дата, C=Время, D=Задача, E=Приоритет
        # Используем USER_ENTERED для правильной интерпретации boolean как checkbox
        new_row = [False, date, time, task, priority.lower()]
        body = {'values': [new_row]}
        append_result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{tasks_sheet}!A:E",
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        # Получаем номер добавленной строки из ответа
        updated_range = append_result.get('updates', {}).get('updatedRange', '')
        if updated_range:
            # Извлекаем номер строки из диапазона (например, "Список задач!A5:E5" -> 5)
            match = re.search(r'!A(\d+):', updated_range)
            if match:
                row_number = int(match.group(1))
            else:
                # Fallback: получаем номер строки через подсчет
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"{tasks_sheet}!A2:A"
                ).execute()
                row_count = len(result.get('values', []))
                row_number = row_count + 1  # +1 потому что заголовок
        else:
            # Fallback: получаем номер строки через подсчет
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"{tasks_sheet}!A2:A"
            ).execute()
            row_count = len(result.get('values', []))
            row_number = row_count + 1  # +1 потому что заголовок
        
        # Устанавливаем формат checkbox для колонки A в новой строке
        sheet_gid = _get_sheet_gid(spreadsheet_id, tasks_sheet)
        if sheet_gid is not None:
            try:
                # Устанавливаем формат checkbox для ячейки A в новой строке
                requests = [{
                    'repeatCell': {
                        'range': {
                            'sheetId': sheet_gid,
                            'startRowIndex': row_number - 1,  # Индексация с 0
                            'endRowIndex': row_number,
                            'startColumnIndex': 0,  # Колонка A
                            'endColumnIndex': 1
                        },
                        'cell': {
                            'dataValidation': {
                                'condition': {
                                    'type': 'BOOLEAN'
                                },
                                'showCustomUi': True,
                                'strict': True
                            }
                        },
                        'fields': 'dataValidation'
                    }
                }]
                
                body_update = {'requests': requests}
                service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body=body_update
                ).execute()
            except Exception as e:
                # Если не удалось установить формат checkbox, продолжаем работу
                pass  # Игнорируем ошибку форматирования
        
        # Формирование ссылок
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        sheet_gid = _get_sheet_gid(spreadsheet_id, tasks_sheet)
        if sheet_gid is not None:
            row_url = f"{sheet_url}/edit#gid={sheet_gid}&range=A{row_number}"
        else:
            row_url = sheet_url
        
        result_data = {
            "row_number": row_number,
            "completed": False,
            "date": date,
            "time": time,
            "task": task,
            "priority": priority.lower(),
            "row_url": row_url
        }
        return json.dumps(result_data, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при создании задачи: {e}"


@mcp.tool()
async def task_list(priority: str | None = None, completed: bool | None = None, date_from: str | None = None, date_to: str | None = None) -> str:
    """Получить список задач с фильтрацией.
    
    Args:
        priority: Фильтр по приоритету (high/middle/low, опционально)
        completed: Фильтр по статусу выполнения (true/false, опционально)
        date_from: Начальная дата для фильтрации (DD-MM-YYYY, опционально)
        date_to: Конечная дата для фильтрации (DD-MM-YYYY, опционально)
        
    Returns:
        JSON строка с массивом задач
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID_2", "").strip()
        if not spreadsheet_id:
            # Fallback на основной spreadsheet_id, если второй не задан
            spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        preferred_sheet_name = os.getenv("SHEETS_TASKS_SHEET", "Список задач").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID_2 не задан в переменных окружения"
        
        # Валидация фильтров
        if priority and not _validate_priority(priority):
            return "Ошибка: Неверный приоритет. Используйте high, middle или low"
        if date_from and not _validate_date(date_from):
            return "Ошибка: Неверный формат date_from. Используйте DD-MM-YYYY"
        if date_to and not _validate_date(date_to):
            return "Ошибка: Неверный формат date_to. Используйте DD-MM-YYYY"
        
        service = _get_sheets_service()
        
        # Получаем или создаем лист
        tasks_sheet = _get_or_create_sheet_name(spreadsheet_id, preferred_sheet_name)
        range_name = f"{tasks_sheet}!A2:E"  # A=Статус, B=Дата, C=Время, D=Задача, E=Приоритет
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        tasks = []
        for i, row in enumerate(values):
            if not row or len(row) < 4:  # Минимум: статус, дата, время, задача
                continue
            
            try:
                # Парсинг строки
                # A=Статус (TRUE/FALSE или текст), B=Дата, C=Время, D=Задача, E=Приоритет
                row_completed = False
                if len(row) > 0:
                    completed_val = row[0]
                    if isinstance(completed_val, bool):
                        row_completed = completed_val
                    elif isinstance(completed_val, str):
                        row_completed = completed_val.lower() in ["true", "1", "да", "выполнено"]
                
                row_date = row[1] if len(row) > 1 else ""
                row_time = row[2] if len(row) > 2 else ""
                row_task = row[3] if len(row) > 3 else ""
                row_priority = row[4].lower() if len(row) > 4 and row[4] else ""
                
                # Фильтрация
                if priority and row_priority != priority.lower():
                    continue
                if completed is not None and row_completed != completed:
                    continue
                if date_from:
                    try:
                        from_day, from_month, from_year = date_from.split('-')
                        row_day, row_month, row_year = row_date.split('-')
                        from_date = datetime(int(from_year), int(from_month), int(from_day))
                        row_date_obj = datetime(int(row_year), int(row_month), int(row_day))
                        if row_date_obj < from_date:
                            continue
                    except (ValueError, TypeError):
                        continue
                if date_to:
                    try:
                        to_day, to_month, to_year = date_to.split('-')
                        row_day, row_month, row_year = row_date.split('-')
                        to_date = datetime(int(to_year), int(to_month), int(to_day))
                        row_date_obj = datetime(int(row_year), int(row_month), int(row_day))
                        if row_date_obj > to_date:
                            continue
                    except (ValueError, TypeError):
                        continue
                
                row_number = i + 2  # +2 потому что начинаем с строки 2 и индексация с 0
                tasks.append({
                    "row_number": row_number,
                    "completed": row_completed,
                    "date": row_date,
                    "time": row_time,
                    "task": row_task,
                    "priority": row_priority
                })
            except (ValueError, TypeError) as e:
                continue
        
        return json.dumps(tasks, ensure_ascii=False)
    except Exception as e:
        return f"Ошибка при получении списка задач: {e}"


@mcp.tool()
async def task_delete(row_number: int) -> str:
    """Удалить задачу из Google Sheets.
    
    Args:
        row_number: Номер строки в Google Sheets (начиная с 2, так как строка 1 - заголовок)
        
    Returns:
        JSON строка со статусом операции
    """
    try:
        spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID_2", "").strip()
        if not spreadsheet_id:
            # Fallback на основной spreadsheet_id, если второй не задан
            spreadsheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
        preferred_sheet_name = os.getenv("SHEETS_TASKS_SHEET", "Список задач").strip()
        
        if not spreadsheet_id:
            return "Ошибка: SHEETS_SPREADSHEET_ID_2 не задан в переменных окружения"
        
        if row_number < 2:
            return "Ошибка: Номер строки должен быть >= 2 (строка 1 - заголовок)"
        
        service = _get_sheets_service()
        
        # Получаем или создаем лист
        tasks_sheet = _get_or_create_sheet_name(spreadsheet_id, preferred_sheet_name)
        
        # Проверка существования строки
        range_name = f"{tasks_sheet}!A{row_number}:E{row_number}"
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        
        if not values or not values[0]:
            return "Ошибка: Задача не найдена"
        
        # Проверяем, сколько всего строк данных (не считая заголовок)
        all_data_range = f"{tasks_sheet}!A2:E"
        all_data_result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=all_data_range
        ).execute()
        all_rows = all_data_result.get('values', [])
        # Подсчитываем только непустые строки с их номерами
        non_empty_rows = [i + 2 for i, row in enumerate(all_rows) if row and any(cell for cell in row if cell and str(cell).strip())]
        total_data_rows = len(non_empty_rows)
        
        # Если это последняя (единственная) строка данных, очищаем её вместо удаления
        # (Google Sheets не позволяет удалить все строки данных, оставив только заголовок)
        if total_data_rows <= 1 and row_number in non_empty_rows:
            # Очищаем строку вместо удаления
            clear_range = f"{tasks_sheet}!A{row_number}:E{row_number}"
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=clear_range
            ).execute()
            result_data = {"status": "cleared", "row_number": row_number, "message": "Строка очищена (последняя строка данных)"}
            return json.dumps(result_data, ensure_ascii=False)
        
        # Если строка не найдена в непустых строках, но существует - тоже очищаем
        if row_number not in non_empty_rows and values and values[0]:
            # Строка существует, но возможно пустая - очищаем
            clear_range = f"{tasks_sheet}!A{row_number}:E{row_number}"
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=clear_range
            ).execute()
            result_data = {"status": "cleared", "row_number": row_number, "message": "Строка очищена"}
            return json.dumps(result_data, ensure_ascii=False)
        
        # Обычное удаление строки
        # Получаем sheet_id для удаления строки
        sheet_gid = _get_sheet_gid(spreadsheet_id, tasks_sheet)
        if sheet_gid is None:
            return "Ошибка: Не удалось найти лист"
        
        # Пытаемся удалить строку, при ошибке очищаем
        try:
            requests_list = [{
                'deleteDimension': {
                    'range': {
                        'sheetId': sheet_gid,
                        'dimension': 'ROWS',
                        'startIndex': row_number - 1,  # Индексация с 0
                        'endIndex': row_number
                    }
                }
            }]
            
            body = {'requests': requests_list}
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body
            ).execute()
            
            result_data = {"status": "deleted", "row_number": row_number}
            return json.dumps(result_data, ensure_ascii=False)
        except HttpError as delete_error:
            # Если ошибка о невозможности удалить все строки - очищаем
            error_str = str(delete_error)
            if "delete all non-frozen rows" in error_str or "not possible to delete" in error_str:
                clear_range = f"{tasks_sheet}!A{row_number}:E{row_number}"
                service.spreadsheets().values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=clear_range
                ).execute()
                result_data = {"status": "cleared", "row_number": row_number, "message": "Строка очищена (последняя строка данных)"}
                return json.dumps(result_data, ensure_ascii=False)
            # Иначе пробрасываем ошибку дальше
            raise
    except HttpError as e:
        return f"Ошибка Google Sheets API: {e}"
    except Exception as e:
        return f"Ошибка при удалении задачи: {e}"


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"


# Add a prompt
@mcp.prompt()
def greet_user(name: str, style: str = "friendly") -> str:
    """Generate a greeting prompt"""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    return f"{styles.get(style, styles['friendly'])} for someone named {name}."


# Run with streamable HTTP transport
if __name__ == "__main__":
    # If you connect from a browser-based client (like MCP Inspector in "Direct" mode),
    # you must enable CORS and expose the Mcp-Session-Id header.
    from starlette.middleware.cors import CORSMiddleware

    import uvicorn

    # IMPORTANT: Do not mount the returned app into another Starlette app.
    # The Streamable HTTP transport relies on the Starlette lifespan to run
    # its internal session manager (task group). If you mount it, the mounted
    # app's lifespan won't run and you'll get:
    # "Task group is not initialized. Make sure to use run()."
    #
    # Endpoint will be available at http://127.0.0.1:8000/mcp
    app = mcp.streamable_http_app(json_response=True)

    app = CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        expose_headers=["Mcp-Session-Id"],
    )

    uvicorn.run(app, host="127.0.0.1", port=8000)