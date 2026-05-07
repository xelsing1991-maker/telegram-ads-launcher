import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
BOTS_FILE = DATA_DIR / "bots.txt"
CHANNEL_FILE = DATA_DIR / "channel.txt"


def run(command: list[str]) -> None:
    print("Running:", " ".join(command))
    subprocess.run(command, check=False)


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        raise SystemExit("No console input.")
    return value or default


def ask_input_file() -> Path:
    source = ask("Источник: 1 - боты, 2 - каналы", "1")
    if source == "1":
        return BOTS_FILE
    if source == "2":
        return CHANNEL_FILE
    raise SystemExit(f"Неизвестный источник: {source}")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    BOTS_FILE.touch(exist_ok=True)
    CHANNEL_FILE.touch(exist_ok=True)

    print("Лаунчер Telegram Ads")
    print("1. Добавлять объявления из боты\\каналы")
    print("2. Проверить ботов и удалить плохих в low-bots.txt low-channel.txt")
    print("3. Калибровать координаты проверки ботов")
    mode = ask("Режим", "1")

    if mode == "1":
        input_file = ask_input_file()
        start_block = ask("Стартовый блок", "1")
        start_number = ask("Стартовый номер объявления", start_block)
        run([
            sys.executable,
            "telegram_ads_screen_auto.py",
            "--input",
            str(input_file),
            "--start-block",
            start_block,
            "--start-number",
            start_number,
        ])
        return

    if mode == "2":
        input_file = ask_input_file()
        start_block = ask("Стартовый блок", "1")
        limit = ask("Сколько проверить, 0 значит все", "0")
        run([
            sys.executable,
            "telegram_bot_checker.py",
            "--input",
            str(input_file),
            "--start-block",
            start_block,
            "--limit",
            limit,
        ])
        return

    if mode == "3":
        run([sys.executable, "telegram_bot_checker.py", "--calibrate"])
        return

    raise SystemExit(f"Неизвестный режим: {mode}")


if __name__ == "__main__":
    main()
