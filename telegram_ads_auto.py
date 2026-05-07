import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
INPUT_FILE = DATA_DIR / "bots.txt"
CHANNEL_FILE = DATA_DIR / "channel.txt"

PROMOTE_URL = "https://t.me/VPN_GROZA_BOT?start=ZankinMaster"
AD_TITLE_PREFIX = "Боты"
MIN_CPM = 0.5
BUDGET = "0.7"
AD_TEXTS = [
    "❌ VPN не работает? ⚡ ВПН ГРОЗА подключается за 1 минуту 📱 Wi-Fi и мобильный интернет 🎁 2 дня для проверки 👉 Перейти к боту сейчас!",
    "🔴 Старый VPN подвел? ⚡ ВПН ГРОЗА для телефона 📱 Wi-Fi и мобильный интернет 🚀 Подключение за 1 минуту 🎁 2 дня проверки 👉 Перейти в бот",
    "❌ VPN тормозит? ⚡ ВПН ГРОЗА быстро подключается на Android и iPhone 📶 Wi-Fi и мобильная сеть 🎁 2 дня для проверки 👉 В бот прямо сейчас",
    "⚡ ВПН ГРОЗА для телефона 📱 Быстрое подключение за 1 минуту 📶 Wi-Fi и мобильный интернет 🎁 2 дня проверки 👉 Перейти к боту сейчас!!",
    "🔴 Не открываются сайты? ⚡ ВПН ГРОЗА поможет подключиться за 1 минуту 📱 Android/iPhone 📶 Wi-Fi 🎁 2 дня для проверки 👉 В бот сейчас!",
    "❌ Нужен рабочий VPN? ⚡ ВПН ГРОЗА для телефона 📶 Wi-Fi и мобильный интернет 🚀 Подключение за 1 минуту 🎁 2 дня 👉 Перейти в бот сейчас!",
    "🔴 VPN снова не работает? ⚡ Попробуйте ВПН ГРОЗА 📱 Android и iPhone 📶 Wi-Fi/моб. интернет 🎁 2 дня проверки 👉 Перейти в бот сейчас!!",
    "❌ Старый VPN не помогает? ⚡ ВПН ГРОЗА для телефона 📶 Wi-Fi и мобильный интернет 🚀 1 минута до подключения 🎁 2 дня 👉 В бот сейчас!!",
    "⚡ ВПН ГРОЗА для Android и iPhone 📶 Wi-Fi и мобильный интернет 🚀 Подключение за 1 минуту 🎁 2 дня для проверки 👉 Перейти в бот сейчас!",
]

BOT_SETTING_RE = re.compile(
    r"^(?:Цена:\s*)?(?P<budget>\d+(?:\.\d+)?)\s*TON\s*---\s*"
    r"(?P<count>\d+)\s*бот\w*\s*---\s*"
    r"(?P<views>\d+)\s*показ\w*\s*в\s*день",
    re.I,
)
BOT_BLOCK_RE = re.compile(r"^Блок\s+(?P<number>\d+)\s*$", re.I)


def source_name(path: Path) -> str:
    return "channel" if path.name.lower() in {"channel.txt", "channels.txt"} else "bots"


def source_title_prefix(path: Path) -> str:
    return "Каналы" if source_name(path) == "channel" else AD_TITLE_PREFIX


def campaign_number(campaign: dict) -> str:
    match = re.search(r"\d+", campaign.get("title", ""))
    return match.group(0) if match else "unknown"


def is_channel_line(line: str) -> bool:
    if line.startswith(("https://t.me/", "http://t.me/", "t.me/", "@")):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_]{5,32}", line))


def normalize_channel(line: str) -> str:
    line = line.strip()
    if line.startswith(("https://t.me/", "http://t.me/", "t.me/", "@")):
        return line
    return f"@{line}"


def campaign_targets(campaign: dict) -> list[str]:
    return campaign.get("bots") or campaign.get("channels") or []


def normalize_cpm(value: str | float | int | None) -> str:
    try:
        cpm = float(value) if value is not None else MIN_CPM
    except (TypeError, ValueError):
        cpm = MIN_CPM
    return str(max(cpm, MIN_CPM)).rstrip("0").rstrip(".")


def make_campaign(
    title: str,
    targets: list[str],
    text: str = "",
    budget: str | None = None,
    daily_views: str | None = None,
    file_number: int | None = None,
    block_number: int | None = None,
) -> dict:
    campaign = {
        "title": title,
        "text": text,
        "bots": targets,
        "channels": targets,
    }
    if budget:
        campaign["budget"] = budget
    if daily_views:
        campaign["daily_views"] = daily_views
    if file_number is not None:
        campaign["file_number"] = file_number
    if block_number is not None:
        campaign["block_number"] = block_number
    return campaign


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def parse_bots_settings_file(path: Path, start_number: int, start_block: int = 1) -> list[dict]:
    if not path.exists():
        return []

    blocks = []
    current_block = None
    current_setting = None
    current_targets: list[str] = []
    in_settings_section = False
    stop_headings = {"НОВЫЕ БОТЫ", "КАНАЛЫ"}

    def flush_block() -> None:
        nonlocal current_block, current_setting, current_targets
        if current_block is None or not current_setting or not current_targets:
            current_targets = []
            return
        blocks.append(
            {
                "number": current_block,
                "targets": current_targets[:],
                "views": current_setting["views"],
            }
        )
        current_block = None
        current_setting = None
        current_targets = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue

        upper_line = line.upper()
        if upper_line.startswith("БОТЫ С НАСТРОЙКАМИ"):
            in_settings_section = True
            continue

        if in_settings_section and upper_line in stop_headings:
            flush_block()
            current_setting = None
            in_settings_section = False
            continue

        block_match = BOT_BLOCK_RE.match(line)
        if block_match:
            in_settings_section = True
            flush_block()
            current_block = int(block_match.group("number"))
            continue

        setting_match = BOT_SETTING_RE.match(line)
        if setting_match:
            in_settings_section = True
            current_setting = setting_match.groupdict()
            continue

        if in_settings_section and current_block is not None and current_setting and is_channel_line(line):
            current_targets.append(normalize_channel(line))

    flush_block()

    campaigns = []
    for block in sorted(blocks, key=lambda item: item["number"]):
        if block["number"] < start_block:
            continue
        number = start_number + len(campaigns)
        campaigns.append(
            make_campaign(
                f"{source_title_prefix(path)} {number}",
                block["targets"],
                text=AD_TEXTS[len(campaigns) % len(AD_TEXTS)],
                budget=BUDGET,
                daily_views=block["views"],
                block_number=block["number"],
            )
        )
    return campaigns


def parse_campaign_file(path: Path, start_number: int, use_file_titles: bool) -> list[dict]:
    if not path.exists():
        return []

    lines = [
        line.strip().lstrip("\ufeff")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    campaigns = []
    targets = []
    ad_text = ""
    has_explicit_campaigns = False
    title_prefix = source_title_prefix(path)
    group_size = 5 if source_name(path) == "channel" else 3

    for line in lines:
        if is_channel_line(line):
            targets.append(normalize_channel(line))
            continue

        title_match = re.fullmatch(r"(?:Каналы|Боты)\s+(\d+)", line, re.I)
        if title_match:
            has_explicit_campaigns = True
            if targets:
                file_number = int(title_match.group(1))
                title = line if use_file_titles else f"{title_prefix} {file_number}"
                campaigns.append(make_campaign(title, targets[:group_size], ad_text, file_number=file_number))
            targets = []
            ad_text = ""
            continue

        has_explicit_campaigns = True
        ad_text = line

    if targets and not has_explicit_campaigns:
        for group in chunks(targets, group_size):
            number = start_number + len(campaigns)
            campaigns.append(
                make_campaign(
                    f"{title_prefix} {number}",
                    group,
                    AD_TEXTS[len(campaigns) % len(AD_TEXTS)],
                    budget=BUDGET,
                    daily_views="1",
                )
            )
        return campaigns

    if targets:
        title = f"{title_prefix} {start_number + len(campaigns)}"
        campaigns.append(make_campaign(title, targets[:group_size], ad_text))

    start_index = next(
        (index for index, campaign in enumerate(campaigns) if campaign.get("file_number") == start_number),
        None,
    )
    if start_index is not None:
        campaigns = campaigns[start_index:]

    for campaign in campaigns:
        campaign.pop("file_number", None)

    return campaigns


def load_campaigns(path: Path, start_number: int, use_file_titles: bool, start_block: int = 1) -> list[dict]:
    path = Path(path)
    campaigns = parse_bots_settings_file(path, start_number, start_block)
    if campaigns:
        return campaigns

    campaigns = parse_campaign_file(path, start_number, use_file_titles)
    if campaigns:
        return campaigns

    raise SystemExit(f"Нет целей в {path}. Заполни файл и запусти скрипт снова.")
