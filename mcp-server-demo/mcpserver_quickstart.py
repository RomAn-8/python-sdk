"""MCPServer quickstart example with Yandex.Weather tool.

Run from the repository root:
    uv run mcp-server-demo/mcpserver_quickstart.py
"""

import asyncio
import os
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

# Load environment variables from .env file
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